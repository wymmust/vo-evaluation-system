"""Local web server with direct data_dir/log_dir path evaluation.

Run from the repository root:

    python -m voeval server

The plain static page cannot read absolute local paths because browsers block
that access. This server keeps the same browser UI, but reads the fixed input
files on the local Python side when the user fills data_dir/log_dir path boxes.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PACKAGE_ROOT / "visualization"

from .core import EvaluationConfig
from .io import load_vloc_evaluation_bundle, load_vloc_evaluation_bundle_from_text, load_vo_evaluation_bundle, load_vo_evaluation_bundle_from_text
from .reports import evaluate_vloc_bundle, evaluate_vo_bundle
from .reports.export import _jsonable_report, report_to_json

LAST_REPORT: dict | None = None  # stored as _jsonable_report dict (JSON-safe)


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
    LAST_REPORT = _jsonable_report(report)
    return _light_report(report)


def evaluate_bundle_payload(payload: dict) -> dict:
    """Evaluate file-content upload request and return the light report."""

    global LAST_REPORT
    entry_mode = str(payload.get("entryMode") or payload.get("entry_mode") or "").strip()
    if not entry_mode:
        raise ValueError("entryMode is required")

    config_data = json.loads(payload.get("configJson") or "{}") if isinstance(payload.get("configJson"), str) else (payload.get("config") or payload.get("configJson") or {})
    config = EvaluationConfig(**{key: value for key, value in config_data.items() if key in EvaluationConfig.__dataclass_fields__})

    if entry_mode == "vo":
        bundle = load_vo_evaluation_bundle_from_text(
            imu_text=payload.get("imuText") or "",
            vo_text=payload.get("estimateText") or "",
            calib_raw_text=payload.get("calibRawText") or "",
            imu_name=payload.get("imuName") or "imu.txt",
            vo_name=payload.get("estimateName") or "vo.txt",
            calib_raw_name=payload.get("calibRawName") or "calib_raw.yaml",
        )
        report = evaluate_vo_bundle(bundle, config)
    else:
        bundle = load_vloc_evaluation_bundle_from_text(
            imu_text=payload.get("imuText") or "",
            vloc_text=payload.get("estimateText") or "",
            home_point_text=payload.get("homePointText") or "",
            calib_raw_text=payload.get("calibRawText") or "",
            imu_name=payload.get("imuName") or "imu.txt",
            vloc_name=payload.get("estimateName") or "vloc.txt",
            home_point_name=payload.get("homePointName") or "home_point.txt",
            calib_raw_name=payload.get("calibRawName") or "calib_raw.yaml",
        )
        report = evaluate_vloc_bundle(bundle, config)
    LAST_REPORT = _jsonable_report(report)
    return _light_report(report)


def get_report_slice(slice_name: str) -> object:
    """Return a full report slice after a local-path evaluation."""

    if LAST_REPORT is None:
        raise RuntimeError("No report has been evaluated yet")
    if slice_name == "full_report":
        return LAST_REPORT
    if slice_name == "trajectory_exports":
        return LAST_REPORT.get("trajectory_exports") or {}
    if slice_name in {"per_pose", "config"}:
        return LAST_REPORT.get(slice_name, [] if slice_name != "config" else {})
    raise ValueError(f"Unknown report slice: {slice_name}")


def _light_report(report: dict) -> dict:
    """Return the initial light payload used by the browser UI."""

    skip_keys = {"per_pose", "trajectory_exports"}
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
            "config",
            "trajectory_exports",
        ],
    }
    return json.loads(report_to_json(light))


class LocalEvaluationHandler(SimpleHTTPRequestHandler):
    """Serve web UI and local path evaluation APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path).path
        if parsed == "/api/evaluate-paths":
            try:
                length = int(self.headers.get("Content-Length") or "0")
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                report = evaluate_paths_payload(payload)
                self._send_json({"ok": True, "report": report})
            except Exception as exc:  # pragma: no cover - exercised through browser/manual server use
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        elif parsed == "/api/evaluate-bundle":
            try:
                length = int(self.headers.get("Content-Length") or "0")
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                report = evaluate_bundle_payload(payload)
                self._send_json({"ok": True, "report": report})
            except Exception as exc:  # pragma: no cover - exercised through browser/manual server use
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return
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
    parser = argparse.ArgumentParser(
        prog="python -m voeval server",
        description="Serve web UI with local data_dir/log_dir path evaluation.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open browser on start")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), LocalEvaluationHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving VO evaluation web UI on {url}")
    print("Local path evaluation API is enabled for this machine.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
