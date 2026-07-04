"""Local static-web server with direct data_dir/log_dir path evaluation.

Run from the repository root:

    python static_web/local_server.py --host 127.0.0.1 --port 8766

The plain static page cannot read absolute local paths because browsers block
that access. This server keeps the same browser UI, but reads the fixed input
files on the local Python side when the user fills data_dir/log_dir path boxes.
"""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vo_eval.data_loader import load_vloc_evaluation_bundle, load_vo_evaluation_bundle  # noqa: E402
from vo_eval.processing import EvaluationConfig, evaluate_vloc_bundle, evaluate_vo_bundle  # noqa: E402
from vo_eval.report import report_to_json  # noqa: E402

LAST_REPORT: dict | None = None


def required_local_files(entry_mode: str) -> dict[str, tuple[str, ...]]:
    """Return the fixed file contract for direct local path evaluation."""

    if entry_mode == "vo":
        return {"data": ("imu.txt",), "log": ("vo.txt", "calib_raw.yaml")}
    if entry_mode == "vloc":
        return {"data": ("imu.txt",), "log": ("vloc.txt", "home_point.txt", "calib_raw.yaml")}
    raise ValueError(f"unsupported entry mode: {entry_mode}")


def evaluate_paths_payload(payload: dict) -> dict:
    """Evaluate one data_dir/log_dir request and return the light report."""

    global LAST_REPORT
    entry_mode = str(payload.get("entryMode") or payload.get("entry_mode") or "").strip()
    data_dir = Path(str(payload.get("dataDirPath") or payload.get("data_dir") or "")).expanduser()
    log_dir = Path(str(payload.get("logDirPath") or payload.get("log_dir") or "")).expanduser()
    config_data = payload.get("config") or {}
    if not entry_mode:
        raise ValueError("entryMode is required")
    required_local_files(entry_mode)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"data_dir not found: {data_dir}")
    if not log_dir.is_dir():
        raise FileNotFoundError(f"log_dir not found: {log_dir}")

    config = EvaluationConfig(**{key: value for key, value in config_data.items() if key in EvaluationConfig.__dataclass_fields__})
    if entry_mode == "vo":
        bundle = load_vo_evaluation_bundle(data_dir, log_dir)
        report = evaluate_vo_bundle(bundle, config)
    else:
        bundle = load_vloc_evaluation_bundle(data_dir, log_dir)
        report = evaluate_vloc_bundle(bundle, config)
    LAST_REPORT = report
    return _light_report(report)


def get_report_slice(slice_name: str) -> object:
    """Return a full report slice after a local-path evaluation."""

    if LAST_REPORT is None:
        raise RuntimeError("No report has been evaluated yet")
    if slice_name == "full_report":
        return LAST_REPORT
    if slice_name == "trajectory_exports":
        return LAST_REPORT.get("trajectory_exports") or {}
    if slice_name in {"per_pose", "segment_records", "worst_segments", "config"}:
        return LAST_REPORT.get(slice_name, [] if slice_name != "config" else {})
    raise ValueError(f"Unknown report slice: {slice_name}")


def _light_report(report: dict) -> dict:
    """Match the Pyodide worker's initial light payload."""

    skip_keys = {"per_pose", "segment_records", "trajectory_exports"}
    light = {key: value for key, value in report.items() if key not in skip_keys}
    entry_mode = (report.get("inputs") or {}).get("entry_mode")
    trajectory_exports = report.get("trajectory_exports") or {}
    rpe_per_frame = trajectory_exports.get("rpe_per_frame")
    scale_per_frame = trajectory_exports.get("scale_per_frame")
    if rpe_per_frame is not None:
        light.setdefault("trajectory_exports", {})["rpe_per_frame"] = rpe_per_frame
    if entry_mode == "vo" and scale_per_frame is not None:
        light.setdefault("trajectory_exports", {})["scale_per_frame"] = scale_per_frame
    light["report_layers"] = {
        "initial_payload": "light",
        "omitted": sorted(skip_keys),
        "download_slices_available": [
            "full_report",
            "per_pose",
            "segment_records",
            "worst_segments",
            "config",
            "trajectory_exports",
        ],
    }
    return json.loads(report_to_json(light))


class LocalEvaluationHandler(SimpleHTTPRequestHandler):
    """Serve static_web and local path evaluation APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/evaluate-paths":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            report = evaluate_paths_payload(payload)
            self._send_json({"ok": True, "report": report})
        except Exception as exc:  # pragma: no cover - exercised through browser/manual server use
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/report-slice":
            try:
                slice_name = (parse_qs(parsed.query).get("slice") or ["full_report"])[0]
                self._send_json({"ok": True, "data": get_report_slice(slice_name)})
            except Exception as exc:  # pragma: no cover - exercised through browser/manual server use
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        super().do_GET()

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve static_web with local data_dir/log_dir path evaluation.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), LocalEvaluationHandler)
    print(f"Serving VO evaluation static web on http://{args.host}:{args.port}/")
    print("Local path evaluation API is enabled for this machine.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
