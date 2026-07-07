"""Public evaluation formats and fixed SF file contracts."""

from __future__ import annotations

from dataclasses import dataclass

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
            "log_dir/calib_raw.yaml",
        ),
        description="SF VO 评估：读取 IMU/nav GT、VO 输出和相机/IMU/body 外参。",
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

VLOC_FIXED_MAX_INTERPOLATION_GAP_S = 1.0
VO_FIXED_MAX_INTERPOLATION_GAP_S = 1.0
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
    "altitude",
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
)
