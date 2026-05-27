from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
from typing import Any

from lib.trackman_review import build_trackman_review_candidate

_ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_stem(value: Any) -> str:
    raw = str(value or "sample")
    stem = _SAFE_STEM_RE.sub("_", raw).strip("_-")
    if not stem:
        stem = "sample"
    if stem == raw:
        return stem
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"


def _candidate_stems(candidates: list[dict[str, Any]]) -> list[str]:
    used: set[str] = set()
    stems: list[str] = []
    for index, candidate in enumerate(candidates):
        stem = _safe_stem(candidate.get("sampleId"))
        if stem in used:
            digest = hashlib.sha1(f"{candidate.get('sampleId')}:{index}".encode("utf-8")).hexdigest()[:8]
            stem = f"{stem}_{digest}"
        used.add(stem)
        stems.append(stem)
    return stems


def _clean_generated_outputs(candidate_dir: Path) -> None:
    if not candidate_dir.exists():
        return
    for pattern in ("*.html", "*.trackman_review.json"):
        for path in candidate_dir.glob(pattern):
            if path.is_file() or path.is_symlink():
                path.unlink()
    asset_dir = candidate_dir / "trackman_assets"
    if not asset_dir.exists():
        return
    for path in asset_dir.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()


def _asset_name_for(stem: str, source_path: Path, asset_dir: Path) -> str:
    name = source_path.name or f"{stem}.trackman"
    target = asset_dir / name
    if not target.exists():
        return name
    try:
        if target.resolve() == source_path.resolve():
            return name
    except OSError:
        pass
    return f"{stem}_{name}"


def _link_trackman_photo(candidate: dict[str, Any], candidate_dir: Path) -> str | None:
    raw_path = candidate.get("trackmanPhotoPath")
    if not raw_path:
        return None

    source_path = Path(str(raw_path))
    if source_path.suffix.lower() not in _ALLOWED_IMAGE_SUFFIXES:
        return None
    if not source_path.exists() or not source_path.is_file():
        return None

    asset_dir = candidate_dir / "trackman_assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset_name = _asset_name_for(_safe_stem(candidate.get("sampleId")), source_path, asset_dir)
    asset_path = asset_dir / asset_name

    if not asset_path.exists():
        try:
            asset_path.symlink_to(source_path)
        except OSError:
            return None

    return os.path.relpath(asset_path, start=candidate_dir)


def _index(candidates: list[dict[str, Any]], stems: list[str]) -> str:
    rows = []
    for candidate, stem in zip(candidates, stems):
        sample_id = html.escape(str(candidate["sampleId"]))
        photo = html.escape(str(candidate.get("trackmanPhoto") or ""))
        status = html.escape(str(candidate.get("reviewStatus") or ""))
        usable = html.escape(str(candidate.get("metricsUsable")))
        rows.append(
            "<tr>"
            f"<td><a href='candidates/{html.escape(stem)}.html'>{sample_id}</a></td>"
            f"<td>{photo}</td>"
            f"<td>{status}</td>"
            f"<td>{usable}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>TrackMan Review</title>"
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:24px;line-height:1.45;}"
        "table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ddd;padding:8px;text-align:left;}"
        "th{background:#f6f6f6;}"
        "</style></head><body>"
        "<h1>TrackMan Review</h1>"
        "<table><thead><tr><th>Sample</th><th>Photo</th><th>Status</th><th>Metrics usable</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</body></html>"
    )


def _photo_section(photo_href: str | None) -> str:
    if not photo_href:
        return ""

    escaped_href = html.escape(photo_href)
    if photo_href.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic")):
        return (
            "<section><h2>TrackMan Image</h2>"
            f"<a href='{escaped_href}'><img src='{escaped_href}' alt='TrackMan image' "
            "style='max-width:100%;height:auto;border:1px solid #ddd'></a>"
            "</section>"
        )
    return f"<section><h2>TrackMan Image</h2><p><a href='{escaped_href}'>{escaped_href}</a></p></section>"


def _candidate_fields_table(candidate: dict[str, Any]) -> str:
    fields = candidate.get("candidateFields") if isinstance(candidate.get("candidateFields"), dict) else {}
    field_order = candidate.get("fieldOrder") if isinstance(candidate.get("fieldOrder"), list) else list(fields)
    rows = []
    for key in field_order:
        field = fields.get(key) if isinstance(fields.get(key), dict) else {}
        candidates = field.get("rawCandidates") if isinstance(field.get("rawCandidates"), list) else []
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(key))}</code></td>"
            f"<td>{html.escape(str(field.get('displayNameZh') or ''))}</td>"
            f"<td>{html.escape(str(field.get('displayNameEn') or ''))}</td>"
            f"<td>{html.escape(str(field.get('normalizedUnit') or ''))}</td>"
            f"<td>{html.escape(', '.join(str(value) for value in candidates))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>Field</th><th>中文参数</th><th>English</th><th>Unit</th><th>OCR candidates</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _candidate_page(candidate: dict[str, Any], stem: str, photo_href: str | None) -> str:
    sample_id = html.escape(str(candidate["sampleId"]))
    fields = html.escape(json.dumps(candidate["candidateFields"], ensure_ascii=False, indent=2))
    corrected_template = html.escape(json.dumps(candidate.get("correctedFieldTemplate") or {}, ensure_ascii=False, indent=2))
    ocr_text = html.escape(str(candidate.get("ocrText") or ""))
    raw_photo_path = html.escape(str(candidate.get("trackmanPhotoPath") or ""))
    candidate_json = html.escape(f"{stem}.trackman_review.json")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>TrackMan Review {sample_id}</title>"
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:24px;line-height:1.45;}"
        "pre{background:#f6f6f6;border:1px solid #ddd;padding:12px;overflow:auto;}"
        "table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top;}"
        "th{background:#f6f6f6;}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}"
        "section{margin-top:24px;}"
        "</style></head><body>"
        f"<p><a href='../index.html'>Back to index</a> | <a href='{candidate_json}'>Candidate JSON</a></p>"
        f"<h1>{sample_id}</h1>"
        "<p><strong>OCR candidate only until human confirmation.</strong> "
        "Only accepted reviews with metricsUsable=true can feed M2 physics.</p>"
        f"<section><h2>Review Gate</h2><pre>reviewStatus: {html.escape(str(candidate.get('reviewStatus') or ''))}\n"
        f"metricsUsable: {html.escape(str(candidate.get('metricsUsable')))}</pre></section>"
        f"{_photo_section(photo_href)}"
        f"<section><h2>Original Photo Path</h2><pre>{raw_photo_path}</pre></section>"
        f"<section><h2>TrackMan Parameters</h2>{_candidate_fields_table(candidate)}</section>"
        f"<section><h2>Corrected Field Template</h2><pre>{corrected_template}</pre></section>"
        f"<section><h2>Candidate Fields JSON</h2><pre>{fields}</pre></section>"
        f"<section><h2>OCR Text</h2><pre>{ocr_text}</pre></section>"
        "</body></html>"
    )


def render_trackman_review_pages(ocr_report_path: Path | str, output_dir: Path | str) -> dict[str, Any]:
    ocr_report_path = Path(ocr_report_path)
    output_dir = Path(output_dir)
    candidate_dir = output_dir / "candidates"
    report = _read_json(ocr_report_path)

    _clean_generated_outputs(candidate_dir)
    candidates = [
        build_trackman_review_candidate(item)
        for item in report.get("items", [])
        if isinstance(item, dict)
    ]
    stems = _candidate_stems(candidates)

    for candidate, stem in zip(candidates, stems):
        photo_href = _link_trackman_photo(candidate, candidate_dir)
        _write_json(candidate_dir / f"{stem}.trackman_review.json", candidate)
        _write_text(candidate_dir / f"{stem}.html", _candidate_page(candidate, stem, photo_href))

    _write_text(output_dir / "index.html", _index(candidates, stems))
    result = {
        "version": "1.0",
        "ocrReportPath": str(ocr_report_path),
        "outputDir": str(output_dir),
        "candidateCount": len(candidates),
    }
    _write_json(output_dir / "trackman_review_report.json", result)
    return result


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Render TrackMan OCR confirmation pages")
    parser.add_argument(
        "--ocr-report",
        type=Path,
        default=annotation_root / "work/stage1_trackman_ocr/stage1_trackman_ocr_report.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=annotation_root / "previews/trackman_review",
    )
    args = parser.parse_args(argv)
    print(json.dumps(render_trackman_review_pages(args.ocr_report, args.output_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
