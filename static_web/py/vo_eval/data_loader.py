"""Data loading and fixed-format parsing for VO/VLOC evaluation."""

from __future__ import annotations

import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

@dataclass(frozen=True)
class EvaluationFormatSpec:
    """公开评估入口格式定义。

    这是新需求的第一层后端约束：页面或自动化流程只能选择这些评估模式。
    注意它和底层单文件 parser 不是同一个概念：
    - sf_vloc/sf_vo 是完整评估模式，需要 data_dir/log_dir 及配套文件；
    - tum 是标准双轨迹文件模式；
    - 旧的 sf/vloc/csv/kitti/xyz 只会作为内部解析工具逐步被迁移或删除，不再作为公开入口。
    """

    mode: str
    label: str
    required_files: tuple[str, ...]
    description: str


EVALUATION_FORMAT_SPECS: dict[str, EvaluationFormatSpec] = {
    "sf_vloc": EvaluationFormatSpec(
        mode="sf_vloc",
        label="SF VLOC",
        required_files=(
            "data_dir/imu.txt",
            "log_dir/vloc.txt",
            "log_dir/home_point.txt",
            "log_dir/calib_raw.yaml",
        ),
        description="SF VLOC 评估：读取 IMU/nav GT、VLOC 输出、home point 和外参标定。",
    ),
    "sf_vo": EvaluationFormatSpec(
        mode="sf_vo",
        label="SF VO",
        required_files=(
            "data_dir/imu.txt",
            "log_dir/vo.txt",
            "log_dir/home_point.txt",
            "log_dir/calib_raw.yaml",
        ),
        description="SF VO 评估：读取 IMU/nav GT、VO 输出、home point 和相机/IMU/body 外参。",
    ),
    "tum": EvaluationFormatSpec(
        mode="tum",
        label="TUM",
        required_files=("ground_truth.tum", "estimate.tum"),
        description="TUM 双轨迹评估：timestamp tx ty tz qx qy qz qw。",
    ),
}


SUPPORTED_EVALUATION_FORMATS: tuple[str, ...] = tuple(EVALUATION_FORMAT_SPECS)


def normalize_evaluation_format(fmt: str) -> str:
    """把用户/页面传入的评估格式规范化为三种公开模式之一。

    当前公开入口要求严格传入 sf_vloc、sf_vo 或 tum，不再把 SF-VLOC、
    sf vo 这类旧前端宽松写法自动转成合法模式。
    """

    normalized = str(fmt).strip()
    if normalized in EVALUATION_FORMAT_SPECS:
        return normalized
    allowed = ", ".join(SUPPORTED_EVALUATION_FORMATS)
    raise ValueError(f"Unsupported evaluation format: {fmt}. Supported evaluation formats: {allowed}")


def get_evaluation_format_spec(fmt: str) -> EvaluationFormatSpec:
    """返回公开评估格式的文件需求和说明。"""

    return EVALUATION_FORMAT_SPECS[normalize_evaluation_format(fmt)]

METRIC_CODE_MAP: tuple[dict[str, str], ...] = (
    {
        "metric": "时间同步 / GT 插值到 estimate",
        "report_field": 'report["association"]',
        "code": "prepare_evaluation_trajectories(); build_associated_trajectories(); interpolate_reference_to_estimate()",
    },
    {
        "metric": "轨迹对齐 / 对齐尺度",
        "report_field": 'report["alignment"]',
        "code": "compute_alignment(); umeyama_alignment(); aggregate_alignment(); apply_alignment()",
    },
    {
        "metric": "ATE 三维位置误差",
        "report_field": 'report["ate_position_m"]; report["ate"]["primary_position_m"]',
        "code": "evaluate_trajectories(): errors/pos_error_m; describe()",
    },
    {
        "metric": "ATE 水平误差",
        "report_field": 'report["ate_horizontal_m"]',
        "code": "evaluate_trajectories(): horizontal_error_m = norm(errors[:, :2]); describe()",
    },
    {
        "metric": "ATE 垂直 / 高度误差",
        "report_field": 'report["ate_vertical_m"]; report["vertical_error_signed_m"]; report["vertical_error_abs_m"]',
        "code": "evaluate_trajectories(): vertical_error_signed_m/errors[:, 2]; describe()",
    },
    {
        "metric": "ATE 姿态误差",
        "report_field": 'report["ate_orientation_deg"]',
        "code": "rotation_errors(); apply_rotation_alignment(); describe()",
    },
    {
        "metric": "ATE yaw 航向误差",
        "report_field": 'report["ate_yaw_deg"]; report["yaw_error_signed_deg"]; report["yaw_error_abs_deg"]',
        "code": "yaw_from_rot(); wrap_pi(); describe()",
    },
    {
        "metric": "RPE 帧数/距离间隔误差",
        "report_field": 'report["rpe_frame_delta"]',
        "code": "rpe_frame_dataframe(); normalize_rpe_delta_config(); relative_error(); describe()",
    },
    {
        "metric": "航程 / 耗时 / 匹配数量 / 覆盖率 / 原始尺度比",
        "report_field": 'report["summary"]',
        "code": "evaluate_trajectories(): summary dict; path_distance(); _gt_coverage_ratio()",
    },
    {
        "metric": "runtime / CPU / 内存 / FPS",
        "report_field": 'report["runtime"]',
        "code": "summarize_runtime(); describe()",
    },
    {
        "metric": "逐帧误差和轨迹可视化数据",
        "report_field": 'report["per_pose"]',
        "code": "evaluate_trajectories(): per_pose DataFrame",
    },
    {
        "metric": "统计口径 count/rmse/mean/median/std/min/max/p95/p99",
        "report_field": "all describe(...) metric summaries",
        "code": "describe(); describe_clean()",
    },
)


@dataclass
class Trajectory:
    """统一后的轨迹数据结构。

    stamps: 秒级时间戳。所有 ns/us/ms 输入都会先归一化到秒。
    positions: N x 3 的位置，单位默认按输入理解为米。
    rotations: 可选 N x 3 x 3 旋转矩阵；没有姿态时仍可计算位置类指标。
    extras: 与轨迹等长的附加字段，例如状态位、速度、reset_count、经纬高、runtime 或 source_index。
    """

    name: str
    stamps: np.ndarray
    positions: np.ndarray
    rotations: np.ndarray | None = None
    extras: dict[str, np.ndarray] = field(default_factory=dict)
    source_format: str = "unknown"

    def __post_init__(self) -> None:
        """进入评估前的最后一道数据标准化。

        代码意义：
        - 所有输入格式最终都会走到 Trajectory，因此这里统一做 shape 校验、类型转换和时间排序。
        - 时间排序很重要：后续 path_distance()、插值、RPE 和断点检测都默认轨迹按时间递增。
        - extras 会跟随相同排序同步重排，确保状态、reset_count、runtime 等字段仍然和位姿一一对应。

        指标影响：
        - 如果这里不排序，summary.duration_s、RPE、尺度窗口和断点检测都会被乱序时间污染。
        - 如果 rotations 维度不一致，姿态 ATE/RPE 会直接变成错误指标，所以这里提前报错。
        """
        self.stamps = np.asarray(self.stamps, dtype=float).reshape(-1)
        self.positions = np.asarray(self.positions, dtype=float)
        if self.positions.ndim != 2 or self.positions.shape[1] != 3:
            raise ValueError("positions must have shape (N, 3)")
        if len(self.stamps) != len(self.positions):
            raise ValueError("stamps and positions must have the same length")
        if self.rotations is not None:
            self.rotations = np.asarray(self.rotations, dtype=float)
            if self.rotations.shape != (len(self.positions), 3, 3):
                raise ValueError("rotations must have shape (N, 3, 3)")
        order = np.argsort(self.stamps)
        self.stamps = self.stamps[order]
        self.positions = self.positions[order]
        if self.rotations is not None:
            self.rotations = self.rotations[order]
        for key, value in list(self.extras.items()):
            arr = np.asarray(value)
            if len(arr) == len(order):
                self.extras[key] = arr[order]

    @property
    def has_rotation(self) -> bool:
        return self.rotations is not None

    @property
    def duration_s(self) -> float:
        if len(self.stamps) < 2:
            return 0.0
        return float(self.stamps[-1] - self.stamps[0])

    @property
    def path_length_m(self) -> float:
        if len(self.positions) < 2:
            return 0.0
        return float(np.sum(np.linalg.norm(np.diff(self.positions, axis=0), axis=1)))


@dataclass(frozen=True)
class HomePoint:
    """SF 评估目录中的 home_point.txt。

    固定格式：longitude latitude altitude_msl。
    这里只负责读取固定三列，后续 NED 转换再使用这个原点。
    """

    longitude: float
    latitude: float
    altitude_msl: float


@dataclass(frozen=True)
class Calibration:
    """SF 评估目录中的 calib_raw.yaml 关键外参。

    只提取需求文档后续坐标变换会用到的 4x4 矩阵。
    """

    t_imu_body: np.ndarray
    t_cam_imu: np.ndarray
    t_cn_cnm1: np.ndarray | None = None


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
    home_point: HomePoint
    calibration: Calibration
    data_dir: Path
    log_dir: Path
    files: dict[str, Path]

VLOC_FIXED_MAX_INTERPOLATION_GAP_S = 1.0
VO_FIXED_MAX_INTERPOLATION_GAP_S = 1.0
VLOC_ALIGNMENT_MODE = "none"
VO_ALIGNMENT_MODE = "sim3"
VLOC_SEGMENT_POLICY = "vo_timestamps"
VO_SEGMENT_POLICY = "segments"
FIXED_TIME_OFFSET_S = 0.0
FIXED_DISCONTINUITY_STEP_M = 100.0
FIXED_DISCONTINUITY_TIME_GAP_S = 5.0
VO_MIN_VALID_SEGMENT_DURATION_S = 10.0
VO_MIN_VALID_SEGMENT_FRAMES = 200
WGS84_A_M = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


IMU_FIXED_COLUMNS = (
    "ts",
    "ts_fcc",
    "status",
    "flight_mode",
    "x",
    "y",
    "z",
    "yaw",
    "pitch",
    "roll",
    "vx",
    "vy",
    "vz",
    "position_reset_count",
    "altitude_reset_count",
    "heading_reset_count",
    "latitude",
    "longitude",
    "altitude",
    "altitude_msl",
    "height",
)

VLOC_FIXED_COLUMNS = (
    "ts",
    "status",
    "num_inliers",
    "reset_count",
    "x",
    "y",
    "z",
    "yaw",
    "pitch",
    "roll",
    "latitude",
    "longitude",
    "height",
)

VO_FIXED_COLUMNS = (
    "ts",
    "num_inliers",
    "x",
    "y",
    "z",
    "yaw",
    "pitch",
    "roll",
    "is_keyframe",
    "time_cost",
    "reset_count",
    "depth_mean",
    "depth_min",
    "depth_max",
)

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


def load_vo_evaluation_bundle(data_dir: str | Path, log_dir: str | Path) -> SfVoBundle:
    """读取 VO 评估目录。

    固定目录契约：
    - data_dir/imu.txt
    - log_dir/vo.txt
    - log_dir/home_point.txt
    - log_dir/calib_raw.yaml

    这个入口不接受 vloc.txt，也不会调用旧的自动表头识别 parser。
    """

    data_path = _require_directory(data_dir, "data_dir")
    log_path = _require_directory(log_dir, "log_dir")
    imu_path = _required_bundle_file(data_path, "imu.txt", "data_dir/imu.txt")
    vo_path = _required_bundle_file(log_path, "vo.txt", "log_dir/vo.txt")
    home_path = _required_bundle_file(log_path, "home_point.txt", "log_dir/home_point.txt")
    calib_path = _required_bundle_file(log_path, "calib_raw.yaml", "log_dir/calib_raw.yaml")

    return SfVoBundle(
        nav=parse_imu_fixed(imu_path.read_text(encoding="utf-8", errors="replace"), name=str(imu_path)),
        vo=parse_vo_fixed(vo_path.read_text(encoding="utf-8", errors="replace"), name=str(vo_path)),
        home_point=parse_home_point_fixed(home_path.read_text(encoding="utf-8", errors="replace"), name=str(home_path)),
        calibration=parse_calib_raw_fixed(calib_path.read_text(encoding="utf-8", errors="replace"), name=str(calib_path)),
        data_dir=data_path,
        log_dir=log_path,
        files={
            "nav": imu_path,
            "estimate": vo_path,
            "home_point": home_path,
            "calib_raw": calib_path,
        },
    )

def parse_imu_fixed(text: str, name: str = "imu.txt") -> Trajectory:
    """按需求文档固定 21 列解析 IMU/nav GT。

    不根据表头猜列名；表头只会被当作非数字说明行跳过。
    yaw/pitch/roll 固定为弧度。
    """

    from .utils import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(text, len(IMU_FIXED_COLUMNS), name, "IMU")
    _require_finite_numeric_table(data, name)
    status = data[:, 2].astype(np.int64)
    extras = {
        "raw_numeric_table": data,
        "ts_fcc": data[:, 1],
        "status": data[:, 2],
        "flight_mode": data[:, 3],
        "vx": data[:, 10],
        "vy": data[:, 11],
        "vz": data[:, 12],
        "position_reset_count": data[:, 13],
        "altitude_reset_count": data[:, 14],
        "heading_reset_count": data[:, 15],
        "latitude": data[:, 16],
        "longitude": data[:, 17],
        "altitude": data[:, 18],
        "altitude_msl": data[:, 19],
        "height": data[:, 20],
        "navi_mode": (status & 0x0F).astype(float),
        "rtk_yaw": ((status & (1 << 22)) != 0).astype(float),
        "rtk_altitude": ((status & (1 << 28)) != 0).astype(float),
    }
    rotations = euler_yaw_pitch_roll_to_matrix(data[:, 7], data[:, 8], data[:, 9])
    return Trajectory(
        name,
        _normalize_timestamps(data[:, 0], "s"),
        data[:, 4:7],
        rotations,
        extras=extras,
        source_format="sf_imu",
    )


def parse_vloc_fixed(text: str, name: str = "vloc.txt") -> Trajectory:
    """按需求文档固定 13 列解析 VLOC 输出。

    不根据表头猜列名；yaw/pitch/roll 固定为角度。
    """

    from .utils import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(text, len(VLOC_FIXED_COLUMNS), name, "VLOC")
    _require_finite_numeric_table(data, name)
    status = data[:, 1].astype(np.int64)
    extras = {
        "raw_numeric_table": data,
        "status": data[:, 1],
        "num_inliers": data[:, 2],
        "reset_count": data[:, 3],
        "latitude": data[:, 10],
        "longitude": data[:, 11],
        "altitude_msl": data[:, 6],
        "height": data[:, 12],
        "vloc_mode": (status & 0x0F).astype(float),
    }
    angles = np.deg2rad(data[:, 7:10])
    rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])
    return Trajectory(
        name,
        _normalize_timestamps(data[:, 0], "s"),
        data[:, 4:7],
        rotations,
        extras=extras,
        source_format="sf_vloc",
    )


def parse_vo_fixed(text: str, name: str = "vo.txt") -> Trajectory:
    """按需求文档固定 14 列解析 VO 输出。

    不根据表头猜列名；yaw/pitch/roll 固定为角度。
    最后三列 depth_mean/depth_min/depth_max 只用于固定格式校验，不参与评估指标。
    兼容旧版 11 列 VO：缺失的 depth 三列会补 0。
    """

    from .utils import euler_yaw_pitch_roll_to_matrix

    data = _read_vo_fixed_numeric_table(text, name)
    _require_finite_numeric_table(data, name)
    extras = {
        "raw_numeric_table": data,
        "num_inliers": data[:, 1],
        "is_keyframe": data[:, 8],
        "time_cost": data[:, 9],
        "reset_count": data[:, 10],
    }
    angles = np.deg2rad(data[:, 5:8])
    rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])
    return Trajectory(
        name,
        _normalize_timestamps(data[:, 0], "s"),
        data[:, 2:5],
        rotations,
        extras=extras,
        source_format="sf_vo",
    )


def _read_vo_fixed_numeric_table(text: str, name: str) -> np.ndarray:
    """读取 VO 固定数字表，兼容旧版 11 列输出。"""

    data = _read_fixed_numeric_table_variants(
        text,
        expected_cols=len(VO_FIXED_COLUMNS),
        legacy_cols=11,
        legacy_padding=(0.0, 0.0, 0.0),
        name=name,
        fmt_name="VO",
    )
    return data


def parse_home_point_fixed(text: str, name: str = "home_point.txt") -> HomePoint:
    """按固定三列解析 home_point.txt：longitude latitude altitude_msl。"""

    data = _read_fixed_numeric_table(text, 3, name, "home_point")
    _require_finite_numeric_table(data, name)
    if len(data) != 1:
        raise ValueError(f"{name}: home_point format expects exactly one numeric row")
    return HomePoint(longitude=float(data[0, 0]), latitude=float(data[0, 1]), altitude_msl=float(data[0, 2]))


def parse_calib_raw_fixed(text: str, name: str = "calib_raw.yaml") -> Calibration:
    """读取 calib_raw.yaml 中后续坐标变换需要的固定 4x4 矩阵。"""

    return Calibration(
        t_imu_body=_extract_fixed_yaml_matrix(text, "T_imu_body", name, required=True),
        t_cam_imu=_extract_fixed_yaml_matrix(text, "T_cam_imu", name, required=True),
        t_cn_cnm1=_extract_fixed_yaml_matrix(text, "T_cn_cnm1", name, required=False),
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


def _read_fixed_numeric_table(text: str, expected_cols: int, name: str, fmt_name: str) -> np.ndarray:
    """读取固定列数字表。

    为了兼容文件首行写死的表头，非数字说明行只允许出现在第一条数据之前。
    真正的数据行必须严格满足固定列数。
    """

    rows: list[list[float]] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [token for token in re.split(r"[\s,;]+", line) if token]
        try:
            values = [float(token) for token in tokens]
        except ValueError:
            if not rows:
                continue
            raise ValueError(f"{name}: {fmt_name} line {line_no} contains non-numeric values after data started")
        if len(values) != expected_cols:
            raise ValueError(f"{name}: {fmt_name} format expects {expected_cols} columns, got {len(values)} on line {line_no}")
        rows.append(values)
    if not rows:
        raise ValueError(f"{name}: {fmt_name} file contains no numeric data rows")
    return np.asarray(rows, dtype=float)


def _read_fixed_numeric_table_variants(
    text: str,
    *,
    expected_cols: int,
    legacy_cols: int,
    legacy_padding: tuple[float, ...],
    name: str,
    fmt_name: str,
) -> np.ndarray:
    """读取固定列数字表，同时兼容一种旧列数。"""

    rows: list[list[float]] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [token for token in re.split(r"[\s,;]+", line) if token]
        try:
            values = [float(token) for token in tokens]
        except ValueError:
            if not rows:
                continue
            raise ValueError(f"{name}: {fmt_name} line {line_no} contains non-numeric values after data started")
        if len(values) == legacy_cols:
            values = values + list(legacy_padding)
        elif len(values) != expected_cols:
            raise ValueError(
                f"{name}: {fmt_name} format expects {expected_cols} columns "
                f"(or legacy {legacy_cols}), got {len(values)} on line {line_no}"
            )
        rows.append(values)
    if not rows:
        raise ValueError(f"{name}: {fmt_name} file contains no numeric data rows")
    return np.asarray(rows, dtype=float)


def _require_finite_numeric_table(data: np.ndarray, name: str) -> None:
    if not np.isfinite(data).all():
        raise ValueError(f"{name}: fixed-format input contains NaN or infinite values")


def _extract_fixed_yaml_matrix(text: str, key: str, name: str, required: bool) -> np.ndarray | None:
    match = re.search(rf"{re.escape(key)}\s*:\s*\[([^\]]+)\]", text, flags=re.DOTALL)
    if not match:
        if required:
            raise ValueError(f"{name}: missing required calibration matrix {key}")
        return None
    values = [float(token) for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", match.group(1))]
    if len(values) != 16:
        raise ValueError(f"{name}: calibration matrix {key} expects 16 values, got {len(values)}")
    return np.asarray(values, dtype=float).reshape(4, 4)


def load_trajectory(source: str | bytes | Path | io.BytesIO, fmt: str = "tum", name: str | None = None) -> Trajectory:
    """从文件、上传对象或纯文本中读取单条 TUM 轨迹。"""
    text, inferred_name = _read_text(source)
    return load_trajectory_from_text(text, fmt=fmt, name=name or inferred_name)


def load_trajectory_from_text(text: str, fmt: str = "tum", name: str = "trajectory") -> Trajectory:
    """把文本轨迹读成 Trajectory。

    当前单文件入口只保留 TUM。
    SF VLOC/VO 主流程必须走目录入口：
    - load_vloc_evaluation_bundle()
    - load_vo_evaluation_bundle()
    """
    lines = _meaningful_lines(text)
    if not lines:
        raise ValueError(f"{name}: empty trajectory file")

    normalized_fmt = fmt.lower()
    if normalized_fmt == "tum":
        return _parse_tum_numeric_table(lines, name)
    raise ValueError(f"Unsupported trajectory format: {fmt}")

def _read_text(source: str | bytes | Path | io.BytesIO) -> tuple[str, str]:
    """把各种输入源统一转成文本和文件名。

    支持：
    - Path: 本地文件路径。
    - bytes / BytesIO: Streamlit 上传文件或浏览器上传内容。
    - 普通字符串: 如果是已有路径就读文件，否则当作原始文本。

    指标影响：
    - 文件名会进入 report["inputs"]，用于报告可追溯。
    - 解码使用 errors="replace"，避免少量非 UTF-8 字符让整份日志读入失败。
    """
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8", errors="replace"), source.name
    if isinstance(source, bytes):
        return source.decode("utf-8", errors="replace"), "uploaded"
    if hasattr(source, "read"):
        data = source.read()
        if isinstance(data, str):
            return data, getattr(source, "name", "uploaded")
        return data.decode("utf-8", errors="replace"), getattr(source, "name", "uploaded")
    path = Path(str(source))
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace"), path.name
    return str(source), "text"


def _meaningful_lines(text: str) -> list[str]:
    """去掉空行和注释行，供无表头格式识别使用。"""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _parse_float_line(line: str) -> list[float]:
    """解析一行纯数字，支持空格、逗号和分号分隔。"""
    tokens = re.split(r"[\s,;]+", line.strip())
    values = []
    for token in tokens:
        if not token:
            continue
        values.append(float(token))
    return values


def _parse_tum_numeric_table(lines: list[str], name: str) -> Trajectory:
    """解析无表头 TUM 数字表：timestamp tx ty tz qx qy qz qw。"""
    from .utils import quaternion_to_matrix

    rows = [_parse_float_line(line) for line in lines]
    width = max(len(row) for row in rows)
    if any(len(row) != width for row in rows):
        raise ValueError(f"{name}: inconsistent number of columns")
    data = np.asarray(rows, dtype=float)
    if data.shape[1] < 8:
        raise ValueError(f"{name}: TUM format needs at least 8 columns")
    stamps = _normalize_timestamps(data[:, 0])
    positions = data[:, 1:4]
    rotations = quaternion_to_matrix(data[:, 4], data[:, 5], data[:, 6], data[:, 7])
    return Trajectory(name, stamps, positions, rotations, extras={"raw_numeric_table": data}, source_format="tum")

def _normalize_timestamps(stamps: np.ndarray, unit_hint: str | None = None) -> np.ndarray:
    """时间戳统一换算到秒。

    这直接影响 duration_s、速度分箱、时间间隔断点和 TUM 时间关联阈值。

    注意：
    - 所有内部时间统一为秒。
    - 如果输入是 EuRoC ns 时间戳，这里会乘 1e-9，避免报告耗时爆成 1e12 秒。
    """
    arr = np.asarray(stamps, dtype=float)
    unit = unit_hint or _infer_timestamp_unit(arr)
    factors = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
    return arr * factors.get(unit or "s", 1.0)


def _infer_timestamp_unit(stamps: np.ndarray) -> str:
    """无表头时按时间戳数量级和相邻步长推断单位。

    推断依据：
    - 绝对值很大通常说明是 Unix ns/us/ms 时间戳。
    - 相邻步长很大也能提示单位，例如 50,000,000 通常是 0.05 秒的 ns。
    """
    finite = np.asarray(stamps, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return "s"

    median_abs = float(np.nanmedian(np.abs(finite)))
    sorted_values = np.sort(finite)
    diffs = np.diff(sorted_values)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    median_step = float(np.nanmedian(diffs)) if len(diffs) else 0.0

    if median_abs >= 1e17 or median_step >= 1e7:
        return "ns"
    if median_abs >= 1e14 or median_step >= 1e4:
        return "us"
    if median_abs >= 1e11:
        return "ms"
    return "s"
