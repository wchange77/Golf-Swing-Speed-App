from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

_TAIL_BYTES = 2_000_000

_KEY_MAP = {
    "com.apple.quicktime.camera.lens_model": "lensModel",
    "com.apple.quicktime.camera.focal_length.35mm_equivalent": "focalLength35mmEquivalent",
    "com.apple.quicktime.camera.lens_irisfnumber": "lensIrisFNumber",
    "com.apple.quicktime.apple-maker-note.74": "appleMakerNote74",
    "com.apple.quicktime.apple-maker-note.97": "appleMakerNote97",
}


def _iter_boxes(data: bytes, start: int = 0, end: int | None = None):
    end = len(data) if end is None else min(end, len(data))
    offset = start
    while offset + 8 <= end:
        size, kind = struct.unpack(">I4s", data[offset : offset + 8])
        header_size = 8
        if size == 1 and offset + 16 <= end:
            size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
            header_size = 16
        elif size == 0:
            size = end - offset
        if size < header_size or offset + size > end:
            offset += 1
            continue
        yield kind, offset + header_size, offset + size
        offset += size


def _find_box_payload(data: bytes, kind: bytes) -> bytes | None:
    for box_kind, payload_start, payload_end in _iter_boxes(data):
        if box_kind == kind:
            return data[payload_start:payload_end]
    marker = data.find(kind)
    if marker >= 4:
        size = struct.unpack(">I", data[marker - 4 : marker])[0]
        end = marker - 4 + size
        if size >= 8 and end <= len(data):
            return data[marker + 4 : end]
    return None


def _parse_keys(payload: bytes) -> dict[int, str]:
    if len(payload) < 8:
        return {}
    count = struct.unpack(">I", payload[4:8])[0]
    offset = 8
    keys: dict[int, str] = {}
    for index in range(1, count + 1):
        if offset + 8 > len(payload):
            break
        entry_size = struct.unpack(">I", payload[offset : offset + 4])[0]
        entry_end = offset + entry_size
        if entry_size < 8 or entry_end > len(payload):
            break
        namespace = payload[offset + 4 : offset + 8]
        if namespace == b"mdta":
            keys[index] = payload[offset + 8 : entry_end].decode("utf-8", errors="replace")
        offset = entry_end
    return keys


def _decode_data_payload(payload: bytes, output_key: str) -> Any:
    if len(payload) < 8:
        return None
    raw = payload[8:]
    if output_key in {"lensModel", "lensIrisFNumber"}:
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    if output_key == "focalLength35mmEquivalent":
        try:
            if len(raw) == 4:
                return float(struct.unpack(">f", raw)[0])
            return float(raw.rstrip(b"\x00").decode("utf-8", errors="replace"))
        except (TypeError, ValueError):
            return None
    if len(raw) >= 4:
        return int(struct.unpack(">i", raw[-4:])[0])
    return None


def _parse_ilst(payload: bytes, keys: dict[int, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind, item_start, item_end in _iter_boxes(payload):
        index = struct.unpack(">I", kind)[0]
        source_key = keys.get(index)
        output_key = _KEY_MAP.get(source_key or "")
        if not output_key:
            continue
        for child_kind, data_start, data_end in _iter_boxes(payload, item_start, item_end):
            if child_kind != b"data":
                continue
            value = _decode_data_payload(payload[data_start:data_end], output_key)
            if value is not None:
                result[output_key] = value
            break
    return result


def parse_quicktime_lens_metadata(path: Path | str) -> dict[str, Any]:
    movie_path = Path(path)
    with movie_path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - _TAIL_BYTES))
        data = handle.read()
    if not any(key.encode("utf-8") in data for key in _KEY_MAP):
        return {}
    keys_payload = _find_box_payload(data, b"keys")
    ilst_payload = _find_box_payload(data, b"ilst")
    if keys_payload is None or ilst_payload is None:
        return {}
    return _parse_ilst(ilst_payload, _parse_keys(keys_payload))
