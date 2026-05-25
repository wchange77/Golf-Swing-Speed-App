from __future__ import annotations

import struct
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.quicktime_camera_metadata import parse_quicktime_lens_metadata


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _keys_box(keys: list[str]) -> bytes:
    entries = []
    for key in keys:
        payload = b"mdta" + key.encode("utf-8")
        entries.append(struct.pack(">I", len(payload) + 4) + payload)
    return _box(b"keys", b"\x00\x00\x00\x00" + struct.pack(">I", len(keys)) + b"".join(entries))


def _data_box(value: str | int | float) -> bytes:
    if isinstance(value, str):
        payload = value.encode("utf-8")
        data_type = 1
    elif isinstance(value, int):
        payload = struct.pack(">i", value)
        data_type = 21
    else:
        payload = struct.pack(">f", value)
        data_type = 23
    return _box(b"data", struct.pack(">II", data_type, 0) + payload)


def _raw_data_box(payload: bytes) -> bytes:
    return _box(b"data", struct.pack(">II", 1, 0) + payload)


def _ilst_box(values: list[str | int | float]) -> bytes:
    entries = []
    for index, value in enumerate(values, start=1):
        entries.append(_box(struct.pack(">I", index), _data_box(value)))
    return _box(b"ilst", b"".join(entries))


def test_parse_quicktime_lens_metadata_extracts_lens_fields(tmp_path: Path):
    keys = [
        "com.apple.quicktime.camera.lens_model",
        "com.apple.quicktime.camera.focal_length.35mm_equivalent",
        "com.apple.quicktime.camera.lens_irisfnumber",
        "com.apple.quicktime.apple-maker-note.74",
        "com.apple.quicktime.apple-maker-note.97",
    ]
    movie_path = tmp_path / "fixture.mov"
    movie_path.write_bytes(
        b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  "
        + _keys_box(keys)
        + _ilst_box([
            "iPhone 17 Pro Max back camera 6.765mm f/1.78",
            25.0,
            "F1.78",
            2,
            24,
        ])
    )

    metadata = parse_quicktime_lens_metadata(movie_path)

    assert metadata == {
        "lensModel": "iPhone 17 Pro Max back camera 6.765mm f/1.78",
        "focalLength35mmEquivalent": 25.0,
        "lensIrisFNumber": "F1.78",
        "appleMakerNote74": 2,
        "appleMakerNote97": 24,
    }


def test_parse_quicktime_lens_metadata_skips_malformed_focal_payload(tmp_path: Path):
    keys = [
        "com.apple.quicktime.camera.lens_model",
        "com.apple.quicktime.camera.focal_length.35mm_equivalent",
        "com.apple.quicktime.camera.lens_irisfnumber",
    ]
    movie_path = tmp_path / "fixture.mov"
    movie_path.write_bytes(
        b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  "
        + _keys_box(keys)
        + _box(
            b"ilst",
            _box(struct.pack(">I", 1), _data_box("iPhone 17 Pro Max back camera"))
            + _box(struct.pack(">I", 2), _raw_data_box(b"not-a-float"))
            + _box(struct.pack(">I", 3), _data_box("F1.78")),
        )
    )

    metadata = parse_quicktime_lens_metadata(movie_path)

    assert metadata == {
        "lensModel": "iPhone 17 Pro Max back camera",
        "lensIrisFNumber": "F1.78",
    }
