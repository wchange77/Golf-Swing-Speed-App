from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class LaunchState:
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    spin_rpm: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Environment:
    gravity_mps2: float = 9.80665
    air_density_kg_m3: float = 1.225
    wind_mps: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ground_plane_height_m: float = 0.0


@dataclass(frozen=True)
class BallProperties:
    mass_kg: float = 0.04593
    radius_m: float = 0.021335
    cd: float = 0.25
    cl: float = 0.16

    @property
    def area_m2(self) -> float:
        return math.pi * self.radius_m * self.radius_m


def mph_to_mps(value: float) -> float:
    return float(value) * 0.44704


def yd_to_m(value: float) -> float:
    return float(value) * 0.9144


def rpm_to_rad_per_second(value: float) -> float:
    return float(value) * 2.0 * math.pi / 60.0


def decompose_launch_velocity(*, speed_mps: float, launch_angle_deg: float, launch_direction_deg: float = 0.0) -> tuple[float, float, float]:
    speed = float(speed_mps)
    launch = math.radians(float(launch_angle_deg))
    direction = math.radians(float(launch_direction_deg))
    horizontal = speed * math.cos(launch)
    vx = horizontal * math.sin(direction)
    vy = speed * math.sin(launch)
    vz = horizontal * math.cos(direction)
    return vx, vy, vz


def _vec_add(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(x + y for x, y in zip(a, b))


def _vec_scale(a: tuple[float, ...], scale: float) -> tuple[float, ...]:
    return tuple(x * scale for x in a)


def _norm3(v: tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _acceleration(
    state: tuple[float, float, float, float, float, float],
    *,
    environment: Environment,
    ball: BallProperties,
    spin_rpm: tuple[float, float, float],
) -> tuple[float, float, float]:
    vx, vy, vz = state[3], state[4], state[5]
    wx, wy, wz = environment.wind_mps
    rel = (vx - wx, vy - wy, vz - wz)
    speed = _norm3(rel)
    ax = 0.0
    ay = -float(environment.gravity_mps2)
    az = 0.0
    if speed > 1e-9:
        drag_k = 0.5 * environment.air_density_kg_m3 * ball.cd * ball.area_m2 / ball.mass_kg
        ax += -drag_k * speed * rel[0]
        ay += -drag_k * speed * rel[1]
        az += -drag_k * speed * rel[2]
        if ball.cl != 0.0:
            lift_k = 0.5 * environment.air_density_kg_m3 * ball.cl * ball.area_m2 / ball.mass_kg
            lift = lift_k * speed * speed
            backspin_factor = max(-2.0, min(2.0, spin_rpm[1] / 3000.0))
            sidespin_factor = max(-2.0, min(2.0, spin_rpm[2] / 3000.0))
            ay += lift * backspin_factor
            ax += lift * sidespin_factor
    return ax, ay, az


def _derivative(
    state: tuple[float, float, float, float, float, float],
    *,
    environment: Environment,
    ball: BallProperties,
    spin_rpm: tuple[float, float, float],
) -> tuple[float, float, float, float, float, float]:
    ax, ay, az = _acceleration(state, environment=environment, ball=ball, spin_rpm=spin_rpm)
    return state[3], state[4], state[5], ax, ay, az


def _rk4_step(
    state: tuple[float, float, float, float, float, float],
    dt: float,
    *,
    environment: Environment,
    ball: BallProperties,
    spin_rpm: tuple[float, float, float],
) -> tuple[float, float, float, float, float, float]:
    k1 = _derivative(state, environment=environment, ball=ball, spin_rpm=spin_rpm)
    k2 = _derivative(_vec_add(state, _vec_scale(k1, dt / 2.0)), environment=environment, ball=ball, spin_rpm=spin_rpm)
    k3 = _derivative(_vec_add(state, _vec_scale(k2, dt / 2.0)), environment=environment, ball=ball, spin_rpm=spin_rpm)
    k4 = _derivative(_vec_add(state, _vec_scale(k3, dt)), environment=environment, ball=ball, spin_rpm=spin_rpm)
    return tuple(
        value + (dt / 6.0) * (k1[index] + 2.0 * k2[index] + 2.0 * k3[index] + k4[index])
        for index, value in enumerate(state)
    )


def _frame(index: int, time_s: float, state: tuple[float, float, float, float, float, float]) -> dict[str, Any]:
    return {
        "frameIndex": index,
        "timeSeconds": round(time_s, 6),
        "source": "predicted_physics",
        "labelEligible": False,
        "worldMeters": {
            "x": round(state[0], 6),
            "height": round(state[1], 6),
            "z": round(state[2], 6),
        },
        "velocityMps": {
            "x": round(state[3], 6),
            "y": round(state[4], 6),
            "z": round(state[5], 6),
        },
    }


def _interpolate_landing(
    previous: tuple[float, float, float, float, float, float],
    current: tuple[float, float, float, float, float, float],
    *,
    ground: float,
) -> tuple[float, float, float, float, float, float]:
    y0 = previous[1]
    y1 = current[1]
    if abs(y1 - y0) < 1e-12:
        alpha = 1.0
    else:
        alpha = max(0.0, min(1.0, (ground - y0) / (y1 - y0)))
    return tuple(previous[i] + alpha * (current[i] - previous[i]) for i in range(6))


def simulate_trajectory(
    launch: LaunchState,
    *,
    environment: Environment | None = None,
    ball: BallProperties | None = None,
    dt: float = 0.002,
    max_time: float = 12.0,
) -> dict[str, Any]:
    environment = environment or Environment()
    ball = ball or BallProperties()
    if dt <= 0 or not math.isfinite(dt):
        raise ValueError("dt must be positive and finite")
    if max_time <= 0 or not math.isfinite(max_time):
        raise ValueError("max_time must be positive and finite")
    state = (
        float(launch.position[0]),
        float(launch.position[1]),
        float(launch.position[2]),
        float(launch.velocity[0]),
        float(launch.velocity[1]),
        float(launch.velocity[2]),
    )
    spin = tuple(float(value) for value in launch.spin_rpm)
    ground = float(environment.ground_plane_height_m)
    frames = [_frame(0, 0.0, state)]
    apex = state[1]
    previous_state = state
    previous_time = 0.0
    descending_seen = state[4] <= 0.0
    landing_state = state
    landing_time = 0.0

    steps = int(math.ceil(max_time / dt))
    for step in range(1, steps + 1):
        current_time = step * dt
        current = _rk4_step(previous_state, dt, environment=environment, ball=ball, spin_rpm=spin)
        apex = max(apex, current[1])
        if current[4] <= 0.0:
            descending_seen = True
        if descending_seen and current[1] <= ground and current_time > 0.0:
            landing_state = _interpolate_landing(previous_state, current, ground=ground)
            if abs(current[1] - previous_state[1]) < 1e-12:
                alpha = 1.0
            else:
                alpha = max(0.0, min(1.0, (ground - previous_state[1]) / (current[1] - previous_state[1])))
            landing_time = previous_time + alpha * dt
            frames.append(_frame(len(frames), landing_time, landing_state))
            break
        frames.append(_frame(len(frames), current_time, current))
        previous_state = current
        previous_time = current_time
    else:
        landing_state = previous_state
        landing_time = previous_time

    x0, y0, z0 = state[0], state[1], state[2]
    side = landing_state[0] - x0
    carry = landing_state[2] - z0
    landing = {
        "xMeters": round(landing_state[0], 6),
        "heightMeters": round(landing_state[1], 6),
        "zMeters": round(landing_state[2], 6),
        "timeSeconds": round(landing_time, 6),
    }
    return {
        "version": "1.0",
        "modelFamily": "RK4_drag_magnus",
        "coefficientPolicy": "constant_coefficients_baseline",
        "coefficientProvenance": [
            "CONTEXT.md highest principle: RK4 + gravity + drag + Magnus baseline, calibrated against TrackMan/video evidence later",
        ],
        "assumptions": {
            "coordinates": "x lateral, y height, z forward",
            "spinConvention": "spin_rpm=(unused, backspin_lift, sidespin_lateral) for baseline M2 fitting",
            "coefficientsCalibrated": False,
            "windMetersPerSecond": list(environment.wind_mps),
        },
        "ball": {
            "massKg": ball.mass_kg,
            "radiusMeters": ball.radius_m,
            "areaM2": ball.area_m2,
            "cd": ball.cd,
            "cl": ball.cl,
        },
        "environment": {
            "gravityMps2": environment.gravity_mps2,
            "airDensityKgM3": environment.air_density_kg_m3,
            "groundPlaneHeightMeters": environment.ground_plane_height_m,
        },
        "flightTimeSeconds": round(landing_time, 6),
        "carryMeters": round(carry, 6),
        "sideMeters": round(side, 6),
        "apexMeters": round(apex, 6),
        "landingFrame": frames[-1]["frameIndex"],
        "landing": landing,
        "frames": frames,
    }
