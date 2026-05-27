
from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_physics_core import (
    BallProperties,
    Environment,
    LaunchState,
    decompose_launch_velocity,
    mph_to_mps,
    rpm_to_rad_per_second,
    simulate_trajectory,
    yd_to_m,
)


def test_no_drag_no_magnus_matches_analytic_projectile():
    launch = LaunchState(position=(0.0, 0.0, 0.0), velocity=(0.0, 20.0, 40.0), spin_rpm=(0.0, 0.0, 0.0))
    result = simulate_trajectory(
        launch,
        environment=Environment(gravity_mps2=9.80665),
        ball=BallProperties(cd=0.0, cl=0.0),
        dt=0.002,
        max_time=10.0,
    )

    expected_time = 2.0 * 20.0 / 9.80665
    expected_carry = 40.0 * expected_time
    expected_apex = 20.0**2 / (2.0 * 9.80665)
    assert result["modelFamily"] == "RK4_drag_magnus"
    assert result["flightTimeSeconds"] == pytest.approx(expected_time, abs=0.02)
    assert result["carryMeters"] == pytest.approx(expected_carry, abs=0.8)
    assert result["apexMeters"] == pytest.approx(expected_apex, abs=0.05)
    assert result["landing"]["heightMeters"] <= 0.02
    assert result["frames"][-1]["source"] == "predicted_physics"
    assert all(frame["labelEligible"] is False for frame in result["frames"])


def test_trajectory_stops_after_descending_through_ground_plane():
    launch = LaunchState(position=(0.0, 1.0, 0.0), velocity=(0.0, 2.0, 15.0), spin_rpm=(0.0, 0.0, 0.0))

    result = simulate_trajectory(launch, ball=BallProperties(cd=0.0, cl=0.0), dt=0.005, max_time=10.0)

    assert result["landing"]["heightMeters"] <= 0.02
    assert result["frames"][-1]["worldMeters"]["height"] <= 0.02
    assert result["landingFrame"] == result["frames"][-1]["frameIndex"]
    assert result["apexMeters"] >= 1.0


def test_fixed_coefficients_are_labeled_baseline_not_calibrated():
    launch = LaunchState(position=(0.0, 0.0, 0.0), velocity=(0.0, 18.0, 38.0), spin_rpm=(0.0, 3000.0, 0.0))

    result = simulate_trajectory(launch, dt=0.004, max_time=8.0)

    assert result["coefficientPolicy"] == "constant_coefficients_baseline"
    assert result["assumptions"]["coefficientsCalibrated"] is False
    assert "CONTEXT.md" in " ".join(result["coefficientProvenance"])


def test_drag_reduces_carry_against_no_drag():
    launch = LaunchState(position=(0.0, 0.0, 0.0), velocity=(0.0, 22.0, 55.0), spin_rpm=(0.0, 0.0, 0.0))

    no_drag = simulate_trajectory(launch, ball=BallProperties(cd=0.0, cl=0.0), dt=0.004, max_time=10.0)
    drag = simulate_trajectory(launch, ball=BallProperties(cd=0.25, cl=0.0), dt=0.004, max_time=10.0)

    assert drag["carryMeters"] < no_drag["carryMeters"]


def test_backspin_magnus_changes_apex_and_flight_time():
    base = LaunchState(position=(0.0, 0.0, 0.0), velocity=(0.0, 20.0, 48.0), spin_rpm=(0.0, 0.0, 0.0))
    backspin = LaunchState(position=(0.0, 0.0, 0.0), velocity=(0.0, 20.0, 48.0), spin_rpm=(0.0, 3200.0, 0.0))

    no_spin = simulate_trajectory(base, ball=BallProperties(cd=0.18, cl=0.0), dt=0.004, max_time=10.0)
    with_spin = simulate_trajectory(backspin, ball=BallProperties(cd=0.18, cl=0.18), dt=0.004, max_time=10.0)

    assert with_spin["apexMeters"] != pytest.approx(no_spin["apexMeters"], abs=0.1)
    assert with_spin["flightTimeSeconds"] != pytest.approx(no_spin["flightTimeSeconds"], abs=0.05)


def test_side_spin_direction_changes_lateral_offset_sign():
    right_spin = LaunchState(position=(0.0, 0.0, 0.0), velocity=(0.0, 18.0, 45.0), spin_rpm=(0.0, 0.0, 1800.0))
    left_spin = LaunchState(position=(0.0, 0.0, 0.0), velocity=(0.0, 18.0, 45.0), spin_rpm=(0.0, 0.0, -1800.0))

    right = simulate_trajectory(right_spin, ball=BallProperties(cd=0.18, cl=0.16), dt=0.004, max_time=10.0)
    left = simulate_trajectory(left_spin, ball=BallProperties(cd=0.18, cl=0.16), dt=0.004, max_time=10.0)

    assert right["sideMeters"] * left["sideMeters"] < 0


def test_dt_stability_within_documented_tolerance():
    launch = LaunchState(position=(0.0, 0.0, 0.0), velocity=(1.0, 21.0, 52.0), spin_rpm=(0.0, 2600.0, 400.0))

    coarse = simulate_trajectory(launch, dt=0.002, max_time=10.0)
    fine = simulate_trajectory(launch, dt=0.001, max_time=10.0)

    assert coarse["carryMeters"] == pytest.approx(fine["carryMeters"], rel=0.015)
    assert coarse["apexMeters"] == pytest.approx(fine["apexMeters"], rel=0.015)


def test_unit_conversions_and_launch_decomposition():
    assert mph_to_mps(100.0) == pytest.approx(44.704)
    assert yd_to_m(150.0) == pytest.approx(137.16)
    assert rpm_to_rad_per_second(60.0) == pytest.approx(2.0 * math.pi)

    vx, vy, vz = decompose_launch_velocity(speed_mps=50.0, launch_angle_deg=30.0, launch_direction_deg=10.0)

    assert vy == pytest.approx(25.0)
    assert math.hypot(vx, vz) == pytest.approx(50.0 * math.cos(math.radians(30.0)))
    assert vx > 0
    assert vz > 0
