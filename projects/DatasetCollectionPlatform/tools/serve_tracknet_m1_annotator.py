from __future__ import annotations

import argparse
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from lib.tracknet_m1_web_annotator import AnnotationStore, AnnotationValidationError, AnnotatorHttpApp


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def _content_type(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _safe_asset_path(asset_dir: Path, request_path: str) -> Path | None:
    relative = "index.html" if request_path == "/" else unquote(request_path.lstrip("/"))
    candidate = (asset_dir / relative).resolve()
    asset_root = asset_dir.resolve()
    if candidate != asset_root and asset_root not in candidate.parents:
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate if candidate.exists() else None


def build_handler(app: AnnotatorHttpApp, asset_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._send(*app.handle("GET", parsed.path, b""))
                return
            if parsed.path.startswith("/frame/"):
                task_id = unquote(parsed.path.removeprefix("/frame/"))
                try:
                    frame_path = app.store.frame_path(task_id)
                except AnnotationValidationError as exc:
                    self._send(404, {"Content-Type": "text/plain; charset=utf-8"}, str(exc).encode("utf-8"))
                    return
                self._send(200, {"Content-Type": _content_type(frame_path)}, frame_path.read_bytes())
                return
            if parsed.path.startswith("/video-frame/"):
                parts = parsed.path.removeprefix("/video-frame/").split("/", 1)
                if len(parts) != 2:
                    self._send(404, {"Content-Type": "text/plain; charset=utf-8"}, b"bad video frame path")
                    return
                sample_id = unquote(parts[0])
                try:
                    frame_index = int(unquote(parts[1]))
                    jpeg = app.store.video_frame_jpeg(sample_id, frame_index)
                except (ValueError, AnnotationValidationError) as exc:
                    self._send(404, {"Content-Type": "text/plain; charset=utf-8"}, str(exc).encode("utf-8"))
                    return
                self._send(200, {"Content-Type": "image/jpeg"}, jpeg)
                return
            asset_path = _safe_asset_path(asset_dir, parsed.path)
            if asset_path is None:
                self._send(404, {"Content-Type": "text/plain; charset=utf-8"}, b"not found")
                return
            self._send(200, {"Content-Type": _content_type(asset_path)}, asset_path.read_bytes())

        def do_PUT(self) -> None:
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or "0")
            self._send(*app.handle("PUT", parsed.path, self.rfile.read(length)))

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Serve the TrackNetV6 M1 web annotator")
    parser.add_argument("--tasks", type=Path, default=annotation_root / "review/m1_labelstudio/labelstudio/tracknet_m1_tasks.json")
    parser.add_argument("--export", type=Path, default=annotation_root / "review/m1_labelstudio/labelstudio_export.json")
    parser.add_argument("--asset-dir", type=Path, default=annotation_root / "annotator")
    parser.add_argument("--batch-index", type=Path, default=annotation_root / "work/m1_batch/batch_index.json")
    parser.add_argument("--seeds", type=Path, default=annotation_root / "work/m1_sota_tracking/seeds.json")
    parser.add_argument("--alignment-candidates", type=Path, default=annotation_root / "work/m1_trackman_alignment/candidate_alignment.json")
    parser.add_argument("--reviewed-alignment", type=Path, default=annotation_root / "work/m1_trackman_alignment/reviewed_alignment.json")
    parser.add_argument("--accepted-only", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    store = AnnotationStore(
        args.tasks,
        args.export,
        batch_index_path=args.batch_index,
        seed_path=args.seeds,
        alignment_candidates_path=args.alignment_candidates,
        reviewed_alignment_path=args.reviewed_alignment,
        accepted_only=args.accepted_only,
    )
    app = AnnotatorHttpApp(store, args.asset_dir)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(app, args.asset_dir))
    print(f"TrackNetV6 M1 annotator: http://{args.host}:{args.port}")
    print(f"Tasks: {args.tasks}")
    print(f"Export: {args.export}")
    print(f"Batch index: {args.batch_index}")
    print(f"Seeds: {args.seeds}")
    print(f"Alignment candidates: {args.alignment_candidates}")
    print(f"Reviewed alignment: {args.reviewed_alignment}")
    print(f"Accepted only: {args.accepted_only}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
