from __future__ import annotations

import argparse
import html
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from lib.trackman_review import (
    FIELD_META,
    FIELD_ORDER,
    _utc_now,
    normalize_corrected_trackman_fields,
    validate_reviewed_trackman_metrics,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _safe_sample_id(value: str) -> str:
    if not value or "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"unsafe sample id: {value}")
    return value


def _review_path_for(reviewed_dir: Path, sample_id: str) -> Path:
    return reviewed_dir / f"{_safe_sample_id(sample_id)}.trackman_review.json"


def save_review_payload(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    existing = _read_json(path) if path.exists() else {}
    if not isinstance(payload.get("correctedFields"), dict):
        raise ValueError("correctedFields must be an object")
    review_status = str(payload.get("reviewStatus") or existing.get("reviewStatus") or "needs_review")
    metrics_usable = bool(payload.get("metricsUsable", existing.get("metricsUsable", False)))
    saved = {
        **existing,
        "reviewStatus": review_status,
        "metricsUsable": metrics_usable,
        "needsHumanConfirmation": not metrics_usable,
        "correctedFields": normalize_corrected_trackman_fields(payload["correctedFields"]),
    }
    if payload.get("reviewer") is not None:
        saved["reviewer"] = str(payload["reviewer"])
    if review_status == "accepted" and metrics_usable:
        saved["reviewedAt"] = _utc_now()
    saved["updatedAt"] = _utc_now()
    _write_json(path, saved)
    return saved


class TrackManReviewStore:
    def __init__(self, *, candidates_dir: Path | str, reviewed_dir: Path | str) -> None:
        self.candidates_dir = Path(candidates_dir)
        self.reviewed_dir = Path(reviewed_dir)

    def _candidate_by_sample(self) -> dict[str, dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        if not self.candidates_dir.exists():
            return candidates
        for path in sorted(self.candidates_dir.glob("*.trackman_review.json")):
            try:
                payload = _read_json(path)
            except Exception:
                continue
            sample_id = payload.get("sampleId")
            if isinstance(sample_id, str) and sample_id:
                candidates[sample_id] = payload
        return candidates

    def _review_paths(self) -> list[Path]:
        if not self.reviewed_dir.exists():
            return []
        return sorted(self.reviewed_dir.glob("*.trackman_review.json"))

    def review_for_sample(self, sample_id: str) -> dict[str, Any]:
        path = _review_path_for(self.reviewed_dir, sample_id)
        if not path.exists():
            raise FileNotFoundError(f"review not found: {sample_id}")
        return _read_json(path)

    def save_review_for_sample(self, sample_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return save_review_payload(_review_path_for(self.reviewed_dir, sample_id), payload)

    def editor_state(self) -> dict[str, Any]:
        validation = validate_reviewed_trackman_metrics(self.reviewed_dir)
        status_by_sample = {item["sampleId"]: item["status"] for item in validation["items"]}
        candidates = self._candidate_by_sample()
        samples: list[dict[str, Any]] = []
        for path in self._review_paths():
            payload = _read_json(path)
            sample_id = str(payload.get("sampleId") or path.name[: -len(".trackman_review.json")])
            candidate = candidates.get(sample_id, {})
            samples.append(
                {
                    "sampleId": sample_id,
                    "shotId": payload.get("shotId"),
                    "trackmanPhoto": payload.get("trackmanPhoto") or candidate.get("trackmanPhoto"),
                    "reviewStatus": payload.get("reviewStatus"),
                    "metricsUsable": bool(payload.get("metricsUsable")),
                    "importStatus": status_by_sample.get(sample_id, "not_accepted"),
                }
            )
        return {
            "fieldOrder": FIELD_ORDER,
            "fieldMeta": {
                key: {
                    "displayNameZh": FIELD_META[key]["displayNameZh"],
                    "displayNameEn": FIELD_META[key]["displayNameEn"],
                    "normalizedUnit": FIELD_META[key]["normalizedUnit"],
                }
                for key in FIELD_ORDER
            },
            "samples": samples,
            "validation": validation,
        }

    def photo_path_for_sample(self, sample_id: str) -> Path | None:
        review = self.review_for_sample(sample_id)
        raw_path = review.get("trackmanPhotoPath")
        if not raw_path:
            candidate = self._candidate_by_sample().get(sample_id, {})
            raw_path = candidate.get("trackmanPhotoPath")
        if not raw_path:
            return None
        path = Path(str(raw_path))
        if not path.exists() or not path.is_file():
            return None
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            return None
        return path


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _index_html() -> str:
    return """<!doctype html>
<meta charset="utf-8">
<title>TrackMan Review Editor</title>
<style>
:root{color-scheme:dark;--bg:#101315;--panel:#171c20;--line:#2b343b;--text:#e9eef2;--muted:#9daab4;--cyan:#4dd6ff;--green:#55d77a;--red:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif}
main{display:grid;grid-template-columns:300px minmax(0,1fr);min-height:100vh}
aside{border-right:1px solid var(--line);padding:14px;background:#12171b;overflow:auto}
section{padding:16px;min-width:0}h1{font-size:20px;margin:0 0 12px}h2{font-size:16px;margin:0 0 10px}
button{background:#1f2a31;color:var(--text);border:1px solid var(--line);border-radius:5px;padding:8px 10px;cursor:pointer}
button:hover{border-color:var(--cyan)}button.primary{background:#11465a;border-color:#24799a}
.sample{display:block;width:100%;text-align:left;margin:0 0 7px}.sample small{display:block;color:var(--muted);margin-top:3px}
.status{font-size:12px;color:var(--muted);margin:8px 0 14px}.ok{color:var(--green)}.bad{color:var(--red)}
.layout{display:grid;grid-template-columns:minmax(320px,48%) minmax(0,1fr);gap:14px}.panel{border:1px solid var(--line);background:var(--panel);border-radius:6px;padding:12px;min-width:0}
img{display:block;max-width:100%;height:auto;background:#000;border:1px solid var(--line)}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid var(--line);padding:7px;text-align:left;vertical-align:middle;font-size:13px}th{color:var(--muted);font-weight:600}
input,select{width:100%;background:#0f1418;color:var(--text);border:1px solid var(--line);border-radius:4px;padding:6px}
.row-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}.raw{color:var(--muted);font-size:12px}
@media(max-width:980px){main{grid-template-columns:1fr}.layout{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid var(--line)}}
</style>
<main>
  <aside>
    <h1>TrackMan Editor</h1>
    <div id="summary" class="status"></div>
    <div id="sample-list"></div>
  </aside>
  <section>
    <div class="row-actions">
      <button type="button" id="save-draft">保存草稿</button>
      <button type="button" id="accept" class="primary">确认可用</button>
      <input id="reviewer" style="max-width:180px" placeholder="reviewer" value="wangwei">
      <span id="save-status" class="status"></span>
    </div>
    <div class="layout">
      <div class="panel"><h2 id="sample-title">请选择样本</h2><img id="photo" alt="TrackMan image"></div>
      <div class="panel">
        <h2>20 参数</h2>
        <table><thead><tr><th>参数</th><th>值</th><th>方向</th><th>单位</th><th>OCR候选</th></tr></thead><tbody id="fields"></tbody></table>
      </div>
    </div>
  </section>
</main>
<script>
let state = null;
let current = null;
let saveTimer = null;
let dirty = false;
const draftsBySample = {};
const dirtySamples = new Set();

async function api(path, options={}) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function directionValue(field) {
  if (!field || !field.direction) return '';
  return field.direction;
}

function escapeAttr(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function fieldValueText(value) {
  if (!value) return '';
  if (value.rawValue != null) return String(value.rawValue);
  if (value.normalizedValue != null) return String(value.normalizedValue);
  return '';
}

function renderSamples() {
  document.getElementById('summary').textContent = `${state.samples.length} samples, importable ${state.validation.importableCount}`;
  const box = document.getElementById('sample-list');
  box.innerHTML = '';
  state.samples.forEach(sample => {
    const btn = document.createElement('button');
    btn.className = 'sample';
    btn.innerHTML = `${sample.sampleId}<small>${sample.importStatus} / ${sample.reviewStatus}</small>`;
    btn.onclick = () => loadSample(sample.sampleId).catch(showSaveError);
    box.appendChild(btn);
  });
}

function fieldRow(key, meta, value, candidate) {
  const raw = ((candidate && candidate.rawCandidates) || []).join(', ');
  const displayValue = fieldValueText(value);
  const unit = (value && value.normalizedUnit) || meta.normalizedUnit || '';
  return `<tr data-key="${key}">
    <td>${meta.displayNameZh}<div class="raw">${key}</div></td>
    <td><input class="value" type="text" inputmode="decimal" value="${escapeAttr(displayValue)}"></td>
    <td><select class="direction"><option value="">无</option><option value="left">左</option><option value="right">右</option></select></td>
    <td><input class="unit" value="${escapeAttr(unit)}"></td>
    <td class="raw">${raw}</td>
  </tr>`;
}

async function loadSample(sampleId) {
  await flushPendingSave();
  const review = await api(`/api/reviews/${encodeURIComponent(sampleId)}`);
  if (draftsBySample[review.sampleId]) review.correctedFields = draftsBySample[review.sampleId];
  current = review;
  document.getElementById('sample-title').textContent = review.sampleId;
  document.getElementById('photo').src = `/api/photos/${encodeURIComponent(review.sampleId)}`;
  const tbody = document.getElementById('fields');
  tbody.innerHTML = state.fieldOrder.map(key => fieldRow(key, state.fieldMeta[key], current.correctedFields[key] || {}, current.candidateFields[key] || {})).join('');
  tbody.querySelectorAll('tr').forEach(row => {
    const key = row.dataset.key;
    row.querySelector('.direction').value = directionValue(current.correctedFields[key]);
  });
  tbody.querySelectorAll('input,select').forEach(input => {
    input.addEventListener('input', scheduleAutosave);
    input.addEventListener('change', scheduleAutosave);
  });
  dirty = false;
}

function fieldFromEditor(valueText, unit, direction) {
  const trimmedValue = valueText.trim();
  const field = { normalizedValue: null, normalizedUnit: unit };
  if (trimmedValue !== '') {
    const numericValue = Number(trimmedValue);
    if (Number.isFinite(numericValue)) {
      field.normalizedValue = numericValue;
    } else {
      field.rawValue = trimmedValue;
    }
  }
  if (direction) field.direction = direction;
  return field;
}

function collectFields() {
  const fields = {};
  document.querySelectorAll('#fields tr').forEach(row => {
    const key = row.dataset.key;
    const valueText = row.querySelector('.value').value;
    const unit = row.querySelector('.unit').value;
    const direction = row.querySelector('.direction').value;
    fields[key] = fieldFromEditor(valueText, unit, direction);
  });
  return fields;
}

function cacheCurrentDraft() {
  if (!current) return null;
  const fields = collectFields();
  draftsBySample[current.sampleId] = fields;
  dirtySamples.add(current.sampleId);
  return {sampleId: current.sampleId, fields};
}

function scheduleAutosave() {
  const draft = cacheCurrentDraft();
  if (!draft) return;
  dirty = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveSampleDraft(draft.sampleId, draft.fields, false).catch(showSaveError), 250);
  document.getElementById('save-status').textContent = '等待保存...';
}

function showSaveError(error) {
  const status = document.getElementById('save-status');
  status.textContent = `保存失败: ${error && error.message ? error.message : error}`;
  status.className = 'status bad';
}

async function save(accept) {
  if (!current) return;
  const draft = cacheCurrentDraft();
  if (!draft) return;
  await saveSampleDraft(draft.sampleId, draft.fields, accept);
}

async function saveSampleDraft(sampleId, payloadFields, accept) {
  const status = document.getElementById('save-status');
  status.className = 'status';
  status.textContent = '保存中...';
  const payload = {
    reviewStatus: accept ? 'accepted' : 'needs_review',
    metricsUsable: !!accept,
    reviewer: document.getElementById('reviewer').value || 'wangwei',
    correctedFields: payloadFields,
  };
  const saved = await api(`/api/reviews/${encodeURIComponent(sampleId)}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  if (current && current.sampleId === sampleId) current = saved;
  draftsBySample[sampleId] = saved.correctedFields;
  dirtySamples.delete(sampleId);
  dirty = false;
  state = await api('/api/samples');
  renderSamples();
  status.className = accept ? 'status ok' : 'status';
  status.textContent = accept ? '已确认并保存' : '草稿已保存';
}

async function flushPendingSave() {
  if (!dirty || !current) return;
  clearTimeout(saveTimer);
  const sampleId = current.sampleId;
  const payloadFields = draftsBySample[sampleId] || collectFields();
  await saveSampleDraft(sampleId, payloadFields, false);
}

document.getElementById('save-draft').onclick = () => save(false).catch(showSaveError);
document.getElementById('accept').onclick = () => save(true).catch(showSaveError);
(async function init() {
  state = await api('/api/samples');
  renderSamples();
  if (state.samples[0]) await loadSample(state.samples[0].sampleId);
})();
</script>
"""


class TrackManReviewHandler(BaseHTTPRequestHandler):
    store: TrackManReviewStore

    def _send_headers(self, status: int, content_length: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send(self, status: int, content: bytes, content_type: str) -> None:
        self._send_headers(status, len(content), content_type)
        self.wfile.write(content)

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._send(HTTPStatus.OK, _index_html().encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/samples":
                self._send_json(self.store.editor_state())
                return
            if path.startswith("/api/reviews/"):
                sample_id = unquote(path.removeprefix("/api/reviews/"))
                self._send_json(self.store.review_for_sample(sample_id))
                return
            if path.startswith("/api/photos/"):
                sample_id = unquote(path.removeprefix("/api/photos/"))
                photo = self.store.photo_path_for_sample(sample_id)
                if photo is None:
                    self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
                    return
                content_type = mimetypes.guess_type(str(photo))[0] or "application/octet-stream"
                self._send(HTTPStatus.OK, photo.read_bytes(), content_type)
                return
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._send_headers(HTTPStatus.OK, len(_index_html().encode("utf-8")), "text/html; charset=utf-8")
                return
            if path.startswith("/api/photos/"):
                sample_id = unquote(path.removeprefix("/api/photos/"))
                photo = self.store.photo_path_for_sample(sample_id)
                if photo is None:
                    self._send_headers(HTTPStatus.NOT_FOUND, len(b"not found"), "text/plain; charset=utf-8")
                    return
                content_type = mimetypes.guess_type(str(photo))[0] or "application/octet-stream"
                self._send_headers(HTTPStatus.OK, photo.stat().st_size, content_type)
                return
            self._send_headers(HTTPStatus.NOT_FOUND, len(b"not found"), "text/plain; charset=utf-8")
        except Exception:
            self._send_headers(HTTPStatus.BAD_REQUEST, 0, "application/json; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if not path.startswith("/api/reviews/"):
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            sample_id = unquote(path.removeprefix("/api/reviews/"))
            self._send_json(self.store.save_review_for_sample(sample_id, payload))
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return


def make_handler(store: TrackManReviewStore) -> type[TrackManReviewHandler]:
    class BoundTrackManReviewHandler(TrackManReviewHandler):
        pass

    BoundTrackManReviewHandler.store = store
    return BoundTrackManReviewHandler


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Serve a writable local TrackMan review editor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--candidates-dir", type=Path, default=annotation_root / "previews/trackman_review/candidates")
    parser.add_argument("--reviewed-dir", type=Path, default=annotation_root / "work/trackman_reviewed")
    args = parser.parse_args(argv)
    store = TrackManReviewStore(candidates_dir=args.candidates_dir, reviewed_dir=args.reviewed_dir)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
