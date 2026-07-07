"""Directory and text bundle loaders for SF VO/VLOC workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .calibration import Calibration, HomePoint
from .parsers import parse_calib_raw_fixed, parse_home_point_fixed, parse_imu_fixed, parse_vloc_fixed, parse_vo_fixed
from .trajectory import Trajectory


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

    return SfVlocBundle(
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
def load_vloc_evaluation_bundle_from_text(
    imu_text: str,
    vloc_text: str,
    home_point_text: str,
    calib_raw_text: str,
    imu_name: str = "imu.txt",
    vloc_name: str = "vloc.txt",
    home_point_name: str = "home_point.txt",
    calib_raw_name: str = "calib_raw.yaml",
) -> SfVlocBundle:
    """从文本内容解析 VLOC 评估 bundle（无需本地目录）。

    供 `/api/evaluate-bundle` 端点调用，浏览器上传文件内容后直接解析。
    内部调用相同的 parse_*_fixed() 函数，保证与目录加载结果数值一致。

    Parameters
    ----------
    imu_text : str
        imu.txt 文件内容
    vloc_text : str
        vloc.txt 文件内容
    home_point_text : str
        home_point.txt 文件内容
    calib_raw_text : str
        calib_raw.yaml 文件内容
    imu_name, vloc_name, home_point_name, calib_raw_name : str
        原始文件名（用于日志和 report inputs 可追溯）

    Returns
    -------
    SfVlocBundle
        与 load_vloc_evaluation_bundle() 返回值结构一致
    """

    return SfVlocBundle(
        nav=parse_imu_fixed(imu_text, name=imu_name),
        vloc=parse_vloc_fixed(vloc_text, name=vloc_name),
        home_point=parse_home_point_fixed(home_point_text, name=home_point_name),
        calibration=parse_calib_raw_fixed(calib_raw_text, name=calib_raw_name),
        data_dir=Path("."),
        log_dir=Path("."),
        files={
            "nav": Path(imu_name),
            "estimate": Path(vloc_name),
            "home_point": Path(home_point_name),
            "calib_raw": Path(calib_raw_name),
        },
    )
def load_vo_evaluation_bundle(data_dir: str | Path, log_dir: str | Path) -> SfVoBundle:
    """读取 VO 评估目录。

    固定目录契约：
    - data_dir/imu.txt
    - log_dir/vo.txt
    - log_dir/calib_raw.yaml

    这个入口不接受 vloc.txt，也不会调用旧的自动表头识别 parser。
    """

    data_path = _require_directory(data_dir, "data_dir")
    log_path = _require_directory(log_dir, "log_dir")
    imu_path = _required_bundle_file(data_path, "imu.txt", "data_dir/imu.txt")
    vo_path = _required_bundle_file(log_path, "vo.txt", "log_dir/vo.txt")
    calib_path = _required_bundle_file(log_path, "calib_raw.yaml", "log_dir/calib_raw.yaml")

    return SfVoBundle(
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
def load_vo_evaluation_bundle_from_text(
    imu_text: str,
    vo_text: str,
    calib_raw_text: str,
    imu_name: str = "imu.txt",
    vo_name: str = "vo.txt",
    calib_raw_name: str = "calib_raw.yaml",
) -> SfVoBundle:
    """从文本内容解析 VO 评估 bundle（无需本地目录）。

    供 `/api/evaluate-bundle` 端点调用，浏览器上传文件内容后直接解析。
    内部调用相同的 parse_*_fixed() 函数，保证与目录加载结果数值一致。

    Parameters
    ----------
    imu_text : str
        imu.txt 文件内容
    vo_text : str
        vo.txt 文件内容
    calib_raw_text : str
        calib_raw.yaml 文件内容
    imu_name, vo_name, calib_raw_name : str
        原始文件名（用于日志和 report inputs 可追溯）

    Returns
    -------
    SfVoBundle
        与 load_vo_evaluation_bundle() 返回值结构一致
    """

    return SfVoBundle(
        nav=parse_imu_fixed(imu_text, name=imu_name),
        vo=parse_vo_fixed(vo_text, name=vo_name),
        calibration=parse_calib_raw_fixed(calib_raw_text, name=calib_raw_name),
        data_dir=Path("."),
        log_dir=Path("."),
        files={
            "nav": Path(imu_name),
            "estimate": Path(vo_name),
            "calib_raw": Path(calib_raw_name),
        },
    )
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
