from __future__ import annotations

from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

import run_tracknet_m1_predicted_flight


def test_predicted_flight_cli_defaults_to_flight_tracking_batch():
    args = run_tracknet_m1_predicted_flight.parse_args([])

    assert args.trajectories_dir.parts[-3:] == ("work", "m1_flight_tracking_batch", "trajectories")
