"""Directory bundle loaders for SF VO/VLOC workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .calibration import Calibration, HomePoint
from .parsers import parse_calib_raw_fixed, parse_home_point_fixed, parse_imu_fixed, parse_vloc_fixed, parse_vo_fixed
from .trajectory import Trajectory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SfVlocBundle:
    """VLOC 评估入口读取结果。

    这个 bundle 明确代表 VLOC 流程，只包含 vloc.txt，不会尝试读取 vo.txt。
    后续 VLOC 专用预处理会在这个结构上继续做时间插值、NED 和外参转换。
    """

    nav: Trajectory
    vloc: Trajectory
    home_point: HomePoint
    calibration: Calibration
    data_dir: Path
    log_dir: Path
    files: dict[str, Path]


@dataclass(frozen=True)
class SfVoBundle:
    """VO 评估入口读取结果。

    这个 bundle 明确代表 VO 流程，只包含 vo.txt，不会尝试读取 vloc.txt。
    后续 VO 专用预处理会按 reset_count 分段并做每段 Sim3。
    """

    nav: Trajectory
    vo: Trajectory
    calibration: Calibration
    data_dir: Path
    log_dir: Path
    files: dict[str, Path]
def load_vloc_evaluation_bundle(data_dir: str | Path, log_dir: str | Path) -> SfVlocBundle:
    """读取 VLOC 评估目录。

    固定目录契约：
    - data_dir/imu.txt
    - log_dir/vloc.txt
    - log_dir/home_point.txt
    - log_dir/calib_raw.yaml

    这个入口不接受 vo.txt，也不会调用旧的自动表头识别 parser。
    """

    data_path = _require_directory(data_dir, "data_dir")
    log_path = _require_directory(log_dir, "log_dir")
    imu_path = _required_bundle_file(data_path, "imu.txt", "data_dir/imu.txt")
    vloc_path = _required_bundle_file(log_path, "vloc.txt", "log_dir/vloc.txt")
    home_path = _required_bundle_file(log_path, "home_point.txt", "log_dir/home_point.txt")
    calib_path = _required_bundle_file(log_path, "calib_raw.yaml", "log_dir/calib_raw.yaml")

    bundle = SfVlocBundle(
        nav=parse_imu_fixed(imu_path.read_text(encoding="utf-8", errors="replace"), name=str(imu_path)),
        vloc=parse_vloc_fixed(vloc_path.read_text(encoding="utf-8", errors="replace"), name=str(vloc_path)),
        home_point=parse_home_point_fixed(home_path.read_text(encoding="utf-8", errors="replace"), name=str(home_path)),
        calibration=parse_calib_raw_fixed(calib_path.read_text(encoding="utf-8", errors="replace"), name=str(calib_path)),
        data_dir=data_path,
        log_dir=log_path,
        files={
            "nav": imu_path,
            "estimate": vloc_path,
            "home_point": home_path,
            "calib_raw": calib_path,
        },
    )
    _log_loaded_trajectory(bundle.nav, imu_path)
    _log_loaded_trajectory(bundle.vloc, vloc_path)
    logger.debug("--------------------------------------------------------------------------------")
    return bundle
def load_vo_evaluation_bundle(data_dir: str | Path, log_dir: str | Path, vo_filename: str) -> SfVoBundle:
    """读取 VO 评估目录。

    固定目录契约：
    - data_dir/imu.txt
    - log_dir/vo_filename
    - log_dir/calib_raw.yaml

    这个入口不接受 vloc.txt，也不会调用旧的自动表头识别 parser。
    """

    data_path = _require_directory(data_dir, "data_dir")
    log_path = _require_directory(log_dir, "log_dir")
    imu_path = _required_bundle_file(data_path, "imu.txt", "data_dir/imu.txt")
    vo_path = _required_bundle_file(log_path, vo_filename, "log_dir/"+vo_filename)
    calib_path = _required_bundle_file(log_path, "calib_raw.yaml", "log_dir/calib_raw.yaml")

    bundle = SfVoBundle(
        nav=parse_imu_fixed(imu_path.read_text(encoding="utf-8", errors="replace"), name=str(imu_path)),
        vo=parse_vo_fixed(vo_path.read_text(encoding="utf-8", errors="replace"), name=str(vo_path)),
        calibration=parse_calib_raw_fixed(calib_path.read_text(encoding="utf-8", errors="replace"), name=str(calib_path)),
        data_dir=data_path,
        log_dir=log_path,
        files={
            "nav": imu_path,
            "estimate": vo_path,
            "calib_raw": calib_path,
        },
    )
    _log_loaded_trajectory(bundle.nav, imu_path)
    _log_loaded_trajectory(bundle.vo, vo_path)
    logger.debug("--------------------------------------------------------------------------------")
    return bundle
def _require_directory(path: str | Path, label: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        raise NotADirectoryError(f"{label} must be a directory: {resolved}")
    return resolved
def _required_bundle_file(base_dir: Path, filename: str, requirement_label: str) -> Path:
    path = base_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing required file {requirement_label}: {path}")
    return path


def _log_loaded_trajectory(traj: Trajectory, source: str | Path) -> None:
    """Emit evo-style trajectory loading debug line."""

    logger.debug("Loaded %d stamps and poses from: %s", len(traj.stamps), source)
