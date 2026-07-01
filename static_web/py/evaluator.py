"""VO/VLOC evaluation core.

这份文件负责所有“算法层”的工作，页面只是调用这里的函数。

当前公开入口：
1. sf_vloc: data_dir/imu.txt + log_dir/vloc.txt + home_point.txt + calib_raw.yaml。
2. sf_vo: data_dir/imu.txt + log_dir/vo.txt + home_point.txt + calib_raw.yaml。
3. tum: 标准 TUM 双轨迹文本，主要保留给离线/回归测试。

代码分层：
1. 固定格式解析：目录入口只按需求文档固定列读取，不再做旧版自动表头识别。
2. 坐标预处理：VLOC 统一到 body/NED；VO 从 camera 通过外参转到 body。
3. 时间同步：固定把 GT/reference 插值到 estimate 时间戳；超过 1.0 s GT 插值间隔的帧会被丢弃。
4. 有效段处理：VLOC 先过滤 vloc_mode <= 1；VO 按 reset_count 分段并过滤短段。
5. 轨迹评估：VLOC 固定不做 Sim3/SE3 对齐；VO 固定按有效连续段分别做 Sim3。
6. 指标与导出：生成页面指标、可视化明细、逐帧 ATE/RPE/尺度表和 Excel 中间结果。

指标与代码字段对应：
- 时间同步质量：prepare_evaluation_trajectories()/interpolate_reference_to_estimate() -> report["association"]。
- 轨迹对齐尺度：compute_alignment()/aggregate_alignment() -> report["alignment"]；VLOC 固定 none，VO 固定分段 Sim3。
- ATE 三维位置误差：pos_error_m -> report["ate_position_m"]。
- ATE 水平误差：horizontal_error_m -> report["ate_horizontal_m"]。
- ATE 垂直/高度误差：vertical_error_m -> report["ate_vertical_m"]。
- 姿态/yaw 误差：rotation_errors()/yaw_from_rot() -> ate_orientation_deg / ate_yaw_deg。
- RPE 帧数/距离间隔误差：rpe_frame_dataframe()/relative_error() -> report["rpe_frame_delta"] 和 rpe_per_frame。
- 局部尺度：scale_frame_dataframe() -> report["scale_frame_delta"] 和 scale_per_frame。
- 覆盖率、路程、耗时、原始尺度比等汇总量：summary dict。
- reset/gap/大跳变诊断：detect_associated_discontinuities() -> report["discontinuities"]。
- runtime/资源统计：summarize_runtime() -> report["runtime"]。

论文出处标注：
- [Sturm12] Sturm et al., "A Benchmark for the Evaluation of RGB-D SLAM Systems", IROS 2012。
  直接来源：TUM trajectory 格式、timestamp association 思路、ATE、RPE。
- [Geiger12] Geiger et al., "Are we ready for Autonomous Driving? The KITTI Vision Benchmark Suite", CVPR 2012。
  参考来源：长距离轨迹评估应关注路程尺度和累计漂移。
- [Schubert18] Schubert et al., "The TUM VI Benchmark for Evaluating Visual-Inertial Odometry", IROS 2018。
  参考来源：VIO 数据的高频 GT、传感器时间同步、长序列/起止段评估和 VI 姿态评估语境。
- [Delmerico18] Delmerico and Scaramuzza, "A Benchmark Comparison of Monocular Visual-Inertial Odometry Algorithms for Flying Robots", ICRA 2018。
  参考来源：飞行机器人场景下同时关注轨迹精度、低延迟、每帧处理时间、CPU 和内存负载。
- [Zhang18] Zhang and Scaramuzza, "A Tutorial on Quantitative Trajectory Evaluation for Visual(-Inertial) Odometry", IROS 2018。
  直接来源：按传感器可观性选择 Sim3/不对齐口径，ATE 与相对误差的统一解释。

每个输出指标对应的论文方法：
- report["association"]：Sturm12 的 TUM greedy timestamp association；interpolate_gt 是本系统为“GT 高频、estimate 低频或错位”
  增加的工程扩展，动机来自 Schubert18 的高频同步 GT 和 Zhang18 对时间关联问题的强调。
- report["alignment"]：Sturm12 ATE 需要先明确轨迹配准口径；Zhang18 明确单目无尺度通常看 Sim3。
- report["ate_position_m"]：Sturm12 的 Absolute Trajectory Error；Zhang18 也把 ATE 作为常用全局误差。
- report["ate_horizontal_m"]：ATE 的 XY 分量拆分，论文中不是独立排行榜指标；为物流无人机横向航线偏差扩展，
  应和 Sturm12/Zhang18 的 ATE 一起理解。
- report["ate_vertical_m"]：ATE 的 Z 分量拆分，论文中不是独立排行榜指标；为无人机高度安全扩展。
- report["ate_orientation_deg"]：Zhang18 的 SE(3) 姿态误差/相对误差思想；Schubert18/TUM VI 的 VIO 评估包含姿态语境。
- report["ate_yaw_deg"]：姿态误差的 yaw 分量拆分，论文中不是独立排行榜指标；为无人机航向控制扩展。
- report["rpe_frame_delta"]：Sturm12 的 Relative Pose Error；frames 模式对应固定帧 RPE，meters 模式是在同一
  relative_error 公式上按 GT 距离窗口选终点的工程扩展；Schubert18/TUM VI 使用固定时间间隔 RPE 评估 VIO；
  Zhang18 将其归入相对误差。
- report["scale_frame_delta"]：局部尺度窗口统计，用来观察 VO 局部尺度是否随时间或距离漂移。
- report["summary"]["gt_coverage_ratio"] 和 report["summary"]["est_coverage_ratio"]：工程扩展，动机来自 Schubert18/Delmerico18
  对长序列 VIO 跟踪成功率、鲁棒性和飞行可用性的关注。
- report["summary"]["raw_path_scale_ratio"]：Zhang18 的尺度可观性和 Sim3/SE3 对齐讨论；用于判断估计轨迹是否无尺度或尺度不稳。
- report["summary"]["duration_s"]、["gt_path_m"]、["est_path_m"]：工程基础量，用于把 Geiger12 的长度/速度误差、
  Delmerico18 的运行时间约束和无人机长航程需求放到同一报告。
- report["discontinuities"]：工程扩展，处理 estimate 重定位/重置/丢跟踪后的大跳变，避免跨断点污染 RPE 和分段 Sim3。
- report["runtime"]：Delmerico18 直接关注每帧处理时间、CPU 和内存负载；本系统从 estimate extras 字段中统计这些量。
"""

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


# 指标代码索引。README 的“指标与 evaluator.py 代码总表”应和这里保持一致。
# 维护规则：只要 report 新增/改名指标，就同步更新本表和 README，避免页面、文档、代码三处口径分叉。
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
        return float(path_distance(self.positions)[-1]) if len(self.positions) else 0.0


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


@dataclass
class EvaluationConfig:
    """评估配置。

    当前前端只暴露少量必要参数：
    - sf_vloc: 页面不暴露对齐/时间同步/RPE 配置，固定 GT 插值到 VLOC 时间戳、最大 GT 插值间隔 1.0s、禁止外推、不做 Sim3。
    - sf_vo: 页面只保留 RPE 统计间隔和尺度图间隔，固定 GT 插值到 VO 时间戳、最大 GT 插值间隔 1.0s、禁止外推、按 reset 连续段分别 Sim3。

    配置与指标/流程的对应关系：
    - rpe_delta_value/rpe_delta_unit: 控制 VO 页面 RPE 按帧数或按 GT 距离统计，对应 report["rpe_frame_delta"] 和 rpe_per_frame。
    - scale_delta_value/scale_delta_unit: 控制 VO 页面局部尺度图按帧数或按 GT 距离取窗口，对应 report["scale_frame_delta"] 和 scale_per_frame。
    """

    rpe_delta_frames: int = 1
    rpe_delta_value: float | None = None
    rpe_delta_unit: str = "frames"
    rpe_distance_tolerance_ratio: float = 0.05
    scale_delta_value: float | None = None
    scale_delta_unit: str = "frames"
    scale_distance_tolerance_ratio: float = 0.05


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


def evaluate_vloc_bundle(bundle: SfVlocBundle, config: EvaluationConfig | None = None) -> dict[str, Any]:
    """按需求文档固定流程评估 sf_vloc。

    这条入口不暴露对齐/姿态修正/时间同步模式选择：
    - 固定使用经纬高 -> NED；
    - 固定把 vloc 的 imu 位姿转到 body；
    - 固定按有效 vloc 时间戳插值 nav；
    - 固定最大 GT 插值间隔 1.0 s，超过直接丢弃该 vloc 帧；
    - 固定不外推、固定 time_offset=0、固定不做 Sim3/SE3 用户选择。
    """

    cfg = normalized_vloc_evaluation_config(config)
    nav_ned_body = sf_nav_to_body_ned_trajectory(bundle.nav, bundle.home_point)
    vloc_ned_body = sf_vloc_to_body_ned_trajectory(bundle.vloc, bundle.home_point, bundle.calibration)

    vloc_mode = np.asarray(vloc_ned_body.extras.get("vloc_mode", np.zeros(len(vloc_ned_body.positions))), dtype=float)
    valid_mode = np.isfinite(vloc_mode) & (vloc_mode > 1.0)
    dropped_invalid_mode = int(np.count_nonzero(~valid_mode))
    if not np.any(valid_mode):
        raise ValueError("No VLOC samples remain after filtering vloc_mode > 1")

    valid_indices = np.flatnonzero(valid_mode)
    vloc_valid = subset_trajectory(vloc_ned_body, valid_indices)
    report = evaluate_trajectories(nav_ned_body, vloc_valid, cfg)
    visual_segment_ids = (
        report["per_pose"]["visual_segment_id"].to_numpy(dtype=int)
        if "visual_segment_id" in report["per_pose"]
        else None
    )
    report["vloc_details"] = build_vloc_detail_report(nav_ned_body, vloc_valid, cfg, visual_segment_ids=visual_segment_ids)
    report["inputs"]["entry_mode"] = "vloc"
    report["inputs"]["workflow"] = "sf_vloc"
    report["inputs"]["data_dir_name"] = bundle.data_dir.name or "data_dir"
    report["inputs"]["log_dir_name"] = bundle.log_dir.name or "log_dir"
    report["inputs"]["fixed_rules"] = {
        "alignment": "none",
        "association_mode": "interpolate_gt",
        "max_interpolation_gap_s": float(VLOC_FIXED_MAX_INTERPOLATION_GAP_S),
        "allow_extrapolation": False,
        "time_offset_s": float(FIXED_TIME_OFFSET_S),
    }
    report["association"]["dropped_est_invalid_mode"] = dropped_invalid_mode
    report["association"]["valid_est_after_mode_filter"] = int(len(vloc_valid.positions))
    report["summary"]["raw_est_poses"] = int(len(bundle.vloc.positions))
    for sheet_name in ("sim3_gt_tum", "sim3_vo_tum"):
        report["trajectory_exports"].pop(sheet_name, None)
    return report


def evaluate_vo_bundle(bundle: SfVoBundle, config: EvaluationConfig | None = None) -> dict[str, Any]:
    """按需求文档固定流程评估 sf_vo。

    这条入口和 VLOC 分开：
    - 固定读取 data_dir/imu.txt 和 log_dir/vo.txt；
    - 固定把 nav body 位姿通过 calib_raw.yaml 外参转到 cam；VO 保持在 cam frame；
    - 固定按 reset_count 连续段切分，丢弃小于 10 s 或小于 200 帧的短段；
    - 固定把 GT 插值到有效 VO 时间戳，最大 GT 插值间隔 1.0 s；
    - 固定按连续段分别做 Sim3，让每个 VO 重置后的局部坐标系单独对齐。
    """

    cfg = normalized_vo_evaluation_config(config)
    # nav_body = sf_nav_to_body_trajectory(bundle.nav)
    # vo_body = sf_vo_to_body_trajectory(bundle.vo, bundle.calibration)
    nav_cam = sf_nav_to_camera_trajectory(bundle.nav, bundle.calibration)
    vo_cam = bundle.vo

    valid_indices, valid_segment_ids, segment_filter = vo_valid_segment_indices(vo_cam)
    if len(valid_indices) < 2:
        raise ValueError("No VO reset segment remains after filtering duration >= 10s and frame count >= 200")

    vo_valid = subset_trajectory(vo_cam, valid_indices)
    vo_valid.extras["evaluation_segment_id"] = np.asarray(valid_segment_ids, dtype=int)
    report = evaluate_trajectories(nav_cam, vo_valid, cfg)
    report["association"]["dropped_est_invalid_segment"] = int(segment_filter["dropped_pose_count"])
    report["association"]["valid_est_after_segment_filter"] = int(len(vo_valid.positions))
    report["association"]["vo_reset_segment_filter"] = segment_filter
    visual_segment_ids = (
        report["per_pose"]["visual_segment_id"].to_numpy(dtype=int)
        if "visual_segment_id" in report["per_pose"]
        else None
    )
    report["vo_details"] = build_vo_detail_report(nav_cam, vo_valid, cfg, report, visual_segment_ids=visual_segment_ids)
    report["inputs"]["entry_mode"] = "vo"
    report["inputs"]["workflow"] = "sf_vo"
    report["inputs"]["data_dir_name"] = bundle.data_dir.name or "data_dir"
    report["inputs"]["log_dir_name"] = bundle.log_dir.name or "log_dir"
    report["inputs"]["fixed_rules"] = {
        "alignment": "sim3",
        "association_mode": "interpolate_gt",
        "max_interpolation_gap_s": float(VO_FIXED_MAX_INTERPOLATION_GAP_S),
        "allow_extrapolation": False,
        "time_offset_s": float(FIXED_TIME_OFFSET_S),
        "continuous_segment_policy": "segments",
        "min_valid_segment_duration_s": float(VO_MIN_VALID_SEGMENT_DURATION_S),
        "min_valid_segment_frames": int(VO_MIN_VALID_SEGMENT_FRAMES),
    }
    report["summary"]["raw_est_poses"] = int(len(bundle.vo.positions))
    return report


def build_vloc_detail_report(
    nav: Trajectory,
    vloc: Trajectory,
    cfg: EvaluationConfig,
    visual_segment_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    """构造 VLOC 页面专用明细。

    这部分严格对应需求文档中的 VLOC 轨迹对比和可视化：
    - comparison: nav_data.ned - vloc_data.ned 的逐帧位置误差，以及 R_ref^-1 R_est 姿态误差；
    - nav_status: 插值到 VLOC 时间戳后的导航状态、速度和 reset 信息；
    - vloc_status: 与有效 VLOC 样本对应的 vloc_mode、num_inliers、reset_count；
    - summary: VLOC 轨迹长度、水平/垂直平均和最大误差。
    """
    nav_eval, vloc_eval, _assoc = build_associated_trajectories(
        nav,
        vloc,
        max_interpolation_gap_s=VLOC_FIXED_MAX_INTERPOLATION_GAP_S,
    )
    timestamps = vloc_eval.stamps
    target_stamps = np.asarray(vloc_eval.extras.get("target_stamp", timestamps + FIXED_TIME_OFFSET_S), dtype=float)
    if len(timestamps) == 0:
        empty = pd.DataFrame()
        return {"summary": {}, "comparison": empty, "nav_status": empty, "vloc_status": empty}

    nav_status = vloc_nav_status_frame(nav, target_stamps, timestamps)
    vloc_status = vloc_est_status_frame(vloc_eval)
    comparison = vloc_comparison_frame(nav_eval, vloc_eval, nav_status, vloc_status, visual_segment_ids=visual_segment_ids)

    horizontal = comparison["horizontal_position_error_m"].to_numpy(dtype=float)
    vertical_abs = comparison["vertical_position_error_abs_m"].to_numpy(dtype=float)
    euler_norm = comparison["attitude_error_euler_norm_deg"].to_numpy(dtype=float) if "attitude_error_euler_norm_deg" in comparison else np.asarray([], dtype=float)
    summary = {
        "trajectory_length_m": float(path_distance(nav_eval.positions)[-1]) if len(nav_eval.positions) else 0.0,
        "horizontal_error_mean_m": float(np.nanmean(horizontal)) if len(horizontal) else math.nan,
        "horizontal_error_max_m": float(np.nanmax(horizontal)) if len(horizontal) else math.nan,
        "vertical_error_mean_m": float(np.nanmean(vertical_abs)) if len(vertical_abs) else math.nan,
        "vertical_error_max_m": float(np.nanmax(vertical_abs)) if len(vertical_abs) else math.nan,
        "mean_error_pos_xy": float(np.nanmean(horizontal)) if len(horizontal) else math.nan,
        "max_error_pos_xy": float(np.nanmax(horizontal)) if len(horizontal) else math.nan,
        "mean_error_pos_z": float(np.nanmean(vertical_abs)) if len(vertical_abs) else math.nan,
        "max_error_pos_z": float(np.nanmax(vertical_abs)) if len(vertical_abs) else math.nan,
        "mean_error_euler": float(np.nanmean(euler_norm)) if len(euler_norm) else math.nan,
        "max_error_euler": float(np.nanmax(euler_norm)) if len(euler_norm) else math.nan,
    }
    return {
        "summary": summary,
        "comparison": comparison,
        "nav_status": nav_status,
        "vloc_status": vloc_status,
    }


def build_vo_detail_report(
    nav: Trajectory,
    vo: Trajectory,
    cfg: EvaluationConfig,
    report: dict[str, Any],
    visual_segment_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    """构造 VO 页面专用明细。

    comparison 使用通用 evaluator 已经算好的 Sim3 后 per_pose 数据：
    这样页面看到的 VO 轨迹、ATE/RPE 和导出结果使用同一套对齐结果。
    """
    nav_eval, vo_eval, _assoc = build_associated_trajectories(
        nav,
        vo,
        max_interpolation_gap_s=VO_FIXED_MAX_INTERPOLATION_GAP_S,
    )
    timestamps = vo_eval.stamps
    target_stamps = np.asarray(vo_eval.extras.get("target_stamp", timestamps + FIXED_TIME_OFFSET_S), dtype=float)
    if len(timestamps) == 0:
        empty = pd.DataFrame()
        return {"summary": {}, "comparison": empty, "nav_status": empty, "vo_status": empty, "segment_filter": {}}

    nav_status = vloc_nav_status_frame(nav, target_stamps, timestamps)
    vo_status = vo_est_status_frame(vo_eval)
    comparison = vo_comparison_frame(report.get("per_pose", pd.DataFrame()), vo_status, visual_segment_ids=visual_segment_ids)
    summary = {
        "trajectory_length_m": float(report.get("summary", {}).get("gt_path_length_m", math.nan)),
        "mean_error_pos_xy": float(report.get("ate_horizontal_m", {}).get("mean", math.nan)),
        "mean_error_pos_z": float(report.get("ate_vertical_m", {}).get("mean", math.nan)),
        "max_error_pos_xy": float(report.get("ate_horizontal_m", {}).get("max", math.nan)),
        "max_error_pos_z": float(report.get("ate_vertical_m", {}).get("max", math.nan)),
        "mean_error_euler": float(report.get("ate_orientation_deg", {}).get("mean", math.nan)) if report.get("ate_orientation_deg") else math.nan,
        "max_error_euler": float(report.get("ate_orientation_deg", {}).get("max", math.nan)) if report.get("ate_orientation_deg") else math.nan,
    }
    segment_filter = report.get("association", {}).get("vo_reset_segment_filter", {})
    return {
        "summary": summary,
        "comparison": comparison,
        "nav_status": nav_status,
        "vo_status": vo_status,
        "segment_filter": segment_filter,
    }


def vloc_nav_status_frame(nav: Trajectory, target_stamps: np.ndarray, timestamps: np.ndarray) -> pd.DataFrame:
    """把 nav 状态按需求文档插到有效 VLOC 时间戳。

    离散状态字段按最近邻；速度、高度等连续字段按线性插值。
    """
    frame = pd.DataFrame({"timestamp": timestamps})
    nearest_fields = {
        "flight_mode": "flight_mode",
        "navi_mode": "navi_mode",
        "rtk_yaw": "rtk_yaw",
        "rtk_alti": "rtk_altitude",
        "position_reset_count": "position_reset_count",
        "altitude_reset_count": "altitude_reset_count",
        "heading_reset_count": "heading_reset_count",
    }
    for output_name, extra_name in nearest_fields.items():
        frame[output_name] = extra_values_nearest(nav, extra_name, target_stamps)

    for extra_field in ("vx", "vy", "vz", "height"):
        frame[extra_field] = extra_values_linear(nav, extra_field, target_stamps)
    frame["velocity_norm"] = np.linalg.norm(frame[["vx", "vy", "vz"]].to_numpy(dtype=float), axis=1)
    return frame


def vloc_est_status_frame(vloc: Trajectory) -> pd.DataFrame:
    """提取有效 VLOC 样本自身的状态字段。"""
    frame = pd.DataFrame({"timestamp": vloc.stamps})
    for extra_field in ("vloc_mode", "num_inliers", "reset_count", "height"):
        frame[extra_field] = trajectory_extra_or_nan(vloc, extra_field)
    return frame


def vo_est_status_frame(vo: Trajectory) -> pd.DataFrame:
    """提取有效 VO 样本自身的状态字段。"""
    frame = pd.DataFrame({"timestamp": vo.stamps})
    for extra_field in ("num_inliers", "is_keyframe", "time_cost", "reset_count", "evaluation_segment_id"):
        frame[extra_field] = trajectory_extra_or_nan(vo, extra_field)
    return frame


def vo_comparison_frame(
    per_pose: pd.DataFrame,
    vo_status: pd.DataFrame,
    visual_segment_ids: np.ndarray | None = None,
) -> pd.DataFrame:
    """VO 逐帧对比表，位置误差按 nav - aligned VO 输出。"""
    if per_pose.empty:
        return pd.DataFrame()
    frame = pd.DataFrame(
        {
            "timestamp": per_pose["timestamp"].to_numpy(dtype=float),
            "segment_id": per_pose["segment_id"].to_numpy(dtype=int),
            "visual_segment_id": (
                np.asarray(visual_segment_ids, dtype=int)
                if visual_segment_ids is not None and len(visual_segment_ids) == len(per_pose)
                else per_pose.get("visual_segment_id", per_pose["segment_id"]).to_numpy(dtype=int)
            ),
            "distance_m": per_pose["distance_m"].to_numpy(dtype=float),
            "nav_x_m": per_pose["gt_x_m"].to_numpy(dtype=float),
            "nav_y_m": per_pose["gt_y_m"].to_numpy(dtype=float),
            "nav_z_m": per_pose["gt_z_m"].to_numpy(dtype=float),
            "vo_x_aligned_m": per_pose["est_x_aligned_m"].to_numpy(dtype=float),
            "vo_y_aligned_m": per_pose["est_y_aligned_m"].to_numpy(dtype=float),
            "vo_z_aligned_m": per_pose["est_z_aligned_m"].to_numpy(dtype=float),
            "position_error_x_m": -per_pose["x_error_m"].to_numpy(dtype=float),
            "position_error_y_m": -per_pose["y_error_m"].to_numpy(dtype=float),
            "position_error_z_m": -per_pose["z_error_m"].to_numpy(dtype=float),
            "position_error_3d_m": per_pose["error_m"].to_numpy(dtype=float),
            "horizontal_position_error_m": per_pose["horizontal_error_m"].to_numpy(dtype=float),
            "vertical_position_error_signed_m": -per_pose["z_error_m"].to_numpy(dtype=float),
            "vertical_position_error_abs_m": per_pose["vertical_error_abs_m"].to_numpy(dtype=float),
        }
    )
    if {"gt_yaw_deg", "est_yaw_aligned_deg", "yaw_error_signed_deg"}.issubset(per_pose.columns):
        frame["nav_yaw_deg"] = per_pose["gt_yaw_deg"].to_numpy(dtype=float)
        frame["nav_pitch_deg"] = per_pose["gt_pitch_deg"].to_numpy(dtype=float)
        frame["nav_roll_deg"] = per_pose["gt_roll_deg"].to_numpy(dtype=float)
        frame["vo_yaw_aligned_deg"] = per_pose["est_yaw_aligned_deg"].to_numpy(dtype=float)
        frame["vo_pitch_aligned_deg"] = per_pose["est_pitch_aligned_deg"].to_numpy(dtype=float)
        frame["vo_roll_aligned_deg"] = per_pose["est_roll_aligned_deg"].to_numpy(dtype=float)
        frame["attitude_error_yaw_deg"] = -per_pose["yaw_error_signed_deg"].to_numpy(dtype=float)
        frame["attitude_error_pitch_deg"] = -per_pose["pitch_error_signed_deg"].to_numpy(dtype=float)
        frame["attitude_error_roll_deg"] = -per_pose["roll_error_signed_deg"].to_numpy(dtype=float)
        frame["attitude_error_euler_norm_deg"] = np.linalg.norm(
            frame[["attitude_error_yaw_deg", "attitude_error_pitch_deg", "attitude_error_roll_deg"]].to_numpy(dtype=float),
            axis=1,
        )
    if len(vo_status) == len(frame):
        for extra_field in ("num_inliers", "is_keyframe", "time_cost", "reset_count", "evaluation_segment_id"):
            if extra_field in vo_status:
                frame[extra_field] = vo_status[extra_field].to_numpy(dtype=float)
    return frame


def vloc_comparison_frame(
    nav_eval: Trajectory,
    vloc_eval: Trajectory,
    nav_status: pd.DataFrame,
    vloc_status: pd.DataFrame,
    visual_segment_ids: np.ndarray | None = None,
) -> pd.DataFrame:
    """VLOC 逐帧对比表，位置误差按需求文档使用 nav - vloc。"""
    nav_pos = np.asarray(nav_eval.positions, dtype=float)
    vloc_pos = np.asarray(vloc_eval.positions, dtype=float)
    pos_error = nav_pos - vloc_pos
    segment_ids = np.zeros(len(vloc_eval.stamps), dtype=int)
    if visual_segment_ids is not None and len(visual_segment_ids) == len(vloc_eval.stamps):
        segment_ids = np.asarray(visual_segment_ids, dtype=int)
    frame = pd.DataFrame(
        {
            "timestamp": vloc_eval.stamps,
            "segment_id": segment_ids,
            "visual_segment_id": segment_ids,
            "distance_m": path_distance(nav_pos),
            "nav_n_m": nav_pos[:, 0],
            "nav_e_m": nav_pos[:, 1],
            "nav_d_m": nav_pos[:, 2],
            "vloc_n_m": vloc_pos[:, 0],
            "vloc_e_m": vloc_pos[:, 1],
            "vloc_d_m": vloc_pos[:, 2],
            "position_error_n_m": pos_error[:, 0],
            "position_error_e_m": pos_error[:, 1],
            "position_error_d_m": pos_error[:, 2],
            "position_error_3d_m": np.linalg.norm(pos_error, axis=1),
            "horizontal_position_error_m": np.linalg.norm(pos_error[:, :2], axis=1),
            "vertical_position_error_signed_m": pos_error[:, 2],
            "vertical_position_error_abs_m": np.abs(pos_error[:, 2]),
        }
    )
    frame["nav_height_m"] = nav_status["height"].to_numpy(dtype=float) if "height" in nav_status else np.nan
    frame["vloc_height_m"] = vloc_status["height"].to_numpy(dtype=float) if "height" in vloc_status else np.nan
    if nav_eval.rotations is not None and vloc_eval.rotations is not None:
        nav_ypr = np.degrees(euler_yaw_pitch_roll_from_matrix(nav_eval.rotations))
        vloc_ypr = np.degrees(euler_yaw_pitch_roll_from_matrix(vloc_eval.rotations))
        err_rot = np.einsum("nji,njk->nik", nav_eval.rotations, vloc_eval.rotations)
        err_ypr = np.degrees(wrap_pi(euler_yaw_pitch_roll_from_matrix(err_rot)))
        frame["nav_yaw_deg"] = nav_ypr[:, 0]
        frame["nav_pitch_deg"] = nav_ypr[:, 1]
        frame["nav_roll_deg"] = nav_ypr[:, 2]
        frame["vloc_yaw_deg"] = vloc_ypr[:, 0]
        frame["vloc_pitch_deg"] = vloc_ypr[:, 1]
        frame["vloc_roll_deg"] = vloc_ypr[:, 2]
        frame["attitude_error_yaw_deg"] = err_ypr[:, 0]
        frame["attitude_error_pitch_deg"] = err_ypr[:, 1]
        frame["attitude_error_roll_deg"] = err_ypr[:, 2]
        frame["attitude_error_euler_norm_deg"] = np.linalg.norm(err_ypr, axis=1)
    return frame


def trajectory_extra_or_nan(traj: Trajectory, key: str) -> np.ndarray:
    """读取等长 extras；不存在时返回 NaN，方便前端图表跳过。"""
    values = traj.extras.get(key)
    if values is None or len(values) != len(traj.positions):
        return np.full(len(traj.positions), math.nan, dtype=float)
    return np.asarray(values, dtype=float)


def extra_values_linear(traj: Trajectory, key: str, target_stamps: np.ndarray) -> np.ndarray:
    """连续字段线性插值到 target_stamps。"""
    unique = _unique_timestamp_trajectory(traj)
    values = trajectory_extra_or_nan(unique, key)
    if len(values) == 0:
        return np.asarray([], dtype=float)
    if np.all(~np.isfinite(values)):
        return np.full(len(target_stamps), math.nan, dtype=float)
    return np.interp(target_stamps, unique.stamps, values)


def extra_values_nearest(traj: Trajectory, key: str, target_stamps: np.ndarray) -> np.ndarray:
    """离散状态字段最近邻插值到 target_stamps。"""
    unique = _unique_timestamp_trajectory(traj)
    values = trajectory_extra_or_nan(unique, key)
    if len(values) == 0:
        return np.asarray([], dtype=float)
    indices = nearest_indices_for_stamps(unique.stamps, target_stamps)
    return values[indices]


def nearest_indices_for_stamps(stamps: np.ndarray, target_stamps: np.ndarray) -> np.ndarray:
    """向量化最近时间戳索引，用于状态字段最近邻插值。"""
    src = np.asarray(stamps, dtype=float)
    target = np.asarray(target_stamps, dtype=float)
    if len(src) == 0:
        raise ValueError("Cannot find nearest index in an empty timestamp array")
    insert = np.searchsorted(src, target, side="left")
    left = np.clip(insert - 1, 0, len(src) - 1)
    right = np.clip(insert, 0, len(src) - 1)
    choose_right = np.abs(src[right] - target) < np.abs(target - src[left])
    return np.where(choose_right, right, left)


def parse_imu_fixed(text: str, name: str = "imu.txt") -> Trajectory:
    """按需求文档固定 21 列解析 IMU/nav GT。

    不根据表头猜列名；表头只会被当作非数字说明行跳过。
    yaw/pitch/roll 固定为弧度。
    """

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


def normalized_vloc_evaluation_config(config: EvaluationConfig | None = None) -> EvaluationConfig:
    """把用户配置收敛成 sf_vloc 固定评估参数。"""
    return _copy_user_delta_config(config)


def normalized_vo_evaluation_config(config: EvaluationConfig | None = None) -> EvaluationConfig:
    """把用户配置收敛成 sf_vo 固定评估参数。

    VO 和 VLOC 的关键区别是：VO 是可能无尺度且会 reset 的轨迹，因此固定走 Sim3，
    并把 reset_count 形成的连续段交给 evaluate_trajectories() 逐段对齐。
    """
    return _copy_user_delta_config(config)


def _copy_user_delta_config(config: EvaluationConfig | None = None) -> EvaluationConfig:
    """只复制仍允许用户控制的 RPE/尺度窗口参数。"""
    base = config if config is not None else EvaluationConfig()
    return EvaluationConfig(
        rpe_delta_frames=base.rpe_delta_frames,
        rpe_delta_value=base.rpe_delta_value,
        rpe_delta_unit=base.rpe_delta_unit,
        rpe_distance_tolerance_ratio=base.rpe_distance_tolerance_ratio,
        scale_delta_value=base.scale_delta_value,
        scale_delta_unit=base.scale_delta_unit,
        scale_distance_tolerance_ratio=base.scale_distance_tolerance_ratio,
    )


def sf_nav_to_body_trajectory(nav: Trajectory) -> Trajectory:
    """VO 流程中的 nav GT 已经是 body 坐标系，这里只补齐语义字段。"""
    extras = dict(nav.extras)
    extras["body_x_m"] = nav.positions[:, 0]
    extras["body_y_m"] = nav.positions[:, 1]
    extras["body_z_m"] = nav.positions[:, 2]
    return Trajectory(
        nav.name,
        nav.stamps,
        nav.positions,
        nav.rotations,
        extras=extras,
        source_format="sf_imu_body",
    )


def sf_nav_to_body_ned_trajectory(nav: Trajectory, home_point: HomePoint) -> Trajectory:
    """把 nav GT 转成以 home_point 为原点的 body/NED 轨迹。

    水平 N/E 使用经纬度转 NED；垂直分量按原 MATLAB VLOC 口径处理：
    nav 使用 altitude_msl，VLOC 使用 raw z，因此后续误差等价于
    abs(nav_altitude_msl + vloc_body_z)。
    """
    latitude = _required_extra(nav, "latitude")
    longitude = _required_extra(nav, "longitude")
    altitude_msl = _required_extra(nav, "altitude_msl")
    ned = geodetic_to_ned(latitude, longitude, altitude_msl, home_point)
    # ned[:, 2] = -np.asarray(altitude_msl, dtype=float)
    extras = dict(nav.extras)
    extras["body_x_m"] = nav.positions[:, 0]
    extras["body_y_m"] = nav.positions[:, 1]
    extras["body_z_m"] = nav.positions[:, 2]
    extras["ned_n_m"] = ned[:, 0]
    extras["ned_e_m"] = ned[:, 1]
    extras["ned_d_m"] = ned[:, 2]
    return Trajectory(
        nav.name,
        nav.stamps,
        ned,
        nav.rotations,
        extras=extras,
        source_format="sf_imu_body_ned",
    )


def sf_vloc_to_body_ned_trajectory(vloc: Trajectory, home_point: HomePoint, calibration: Calibration) -> Trajectory:
    """把 vloc 的 imu 位姿转成 body/NED 轨迹。"""
    latitude = _required_extra(vloc, "latitude")
    longitude = _required_extra(vloc, "longitude")
    altitude_msl = np.asarray(vloc.extras.get("altitude_msl", vloc.positions[:, 2]), dtype=float)
    imu_ned = geodetic_to_ned(latitude, longitude, altitude_msl, home_point)
    # imu_ned[:, 2] = np.asarray(vloc.positions[:, 2], dtype=float)

    rotations = vloc.rotations
    body_ned = imu_ned
    body_rot = rotations
    if rotations is not None:
        rot_imu_body = np.asarray(calibration.t_imu_body[:3, :3], dtype=float)
        trans_imu_body = np.asarray(calibration.t_imu_body[:3, 3], dtype=float)
        rot_body_imu = rot_imu_body.T
        trans_body_in_imu = -rot_body_imu @ trans_imu_body
        body_ned = imu_ned + np.einsum("nij,j->ni", rotations, trans_body_in_imu)
        body_rot = np.einsum("nij,jk->nik", rotations, rot_body_imu)

    extras = dict(vloc.extras)
    extras["imu_x_m"] = vloc.positions[:, 0]
    extras["imu_y_m"] = vloc.positions[:, 1]
    extras["imu_z_m"] = vloc.positions[:, 2]
    extras["ned_n_m"] = body_ned[:, 0]
    extras["ned_e_m"] = body_ned[:, 1]
    extras["ned_d_m"] = body_ned[:, 2]
    return Trajectory(
        vloc.name,
        vloc.stamps,
        body_ned,
        body_rot,
        extras=extras,
        source_format="sf_vloc_body_ned",
    )


def sf_nav_to_camera_trajectory(nav: Trajectory, calibration: Calibration) -> Trajectory:
    """把 nav 从 body/IMU 系转到 camera 系，使 nav 与 VO 在同一坐标系下评估。

    数学（参考 convert_nav_to_tum.py）：
      R_b_c = R_b_i @ R_c_i^T
      P_b_c = P_b_i - R_b_c @ P_c_i
    对每一帧 nav：
      R_w_c = R_w_b @ R_b_c
      P_w_c = P_w_b + R_w_b @ P_b_c

    来源对应：需求明确 VO 在 cam frame 输出，因此把 GT 转到 cam frame 比较，
    而不是把 VO 转到 body frame。单位外参时输出应与原始 nav 完全一致。
    """
    t_imu_body = np.asarray(calibration.t_imu_body, dtype=float)
    t_cam_imu = np.asarray(calibration.t_cam_imu, dtype=float)

    rot_b_i = t_imu_body[:3, :3]
    trans_b_i = t_imu_body[:3, 3]
    rot_c_i = t_cam_imu[:3, :3]
    trans_c_i = t_cam_imu[:3, 3]

    rot_b_c = rot_b_i @ rot_c_i.T
    trans_b_c = trans_b_i - rot_b_c @ trans_c_i

    rotations = nav.rotations
    cam_positions = np.asarray(nav.positions, dtype=float)
    cam_rotations = rotations
    if rotations is not None:
        cam_positions = cam_positions + np.einsum("nij,j->ni", rotations, trans_b_c)
        cam_rotations = np.einsum("nij,jk->nik", rotations, rot_b_c)

    extras = dict(nav.extras)
    extras["body_x_m"] = nav.positions[:, 0]
    extras["body_y_m"] = nav.positions[:, 1]
    extras["body_z_m"] = nav.positions[:, 2]
    extras["cam_x_m"] = cam_positions[:, 0]
    extras["cam_y_m"] = cam_positions[:, 1]
    extras["cam_z_m"] = cam_positions[:, 2]
    return Trajectory(
        nav.name,
        nav.stamps,
        cam_positions,
        cam_rotations,
        extras=extras,
        source_format="sf_imu_camera",
    )


def sf_vo_to_body_trajectory(vo: Trajectory, calibration: Calibration) -> Trajectory:
    """把 VO camera 位姿转成 body 位姿。

    需求文档定义 VO 输出在 cam frame，评估时要和 nav body frame 对比。
    这里按 T_world_body = T_world_cam * T_cam_imu * T_imu_body 组合外参；
    单位外参时输出应与原始 VO 完全一致。
    """
    t_cam_body = np.asarray(calibration.t_cam_imu, dtype=float) @ np.asarray(calibration.t_imu_body, dtype=float)
    rot_cam_body = t_cam_body[:3, :3]
    trans_cam_body = t_cam_body[:3, 3]

    rotations = vo.rotations
    body_positions = np.asarray(vo.positions, dtype=float)
    body_rotations = rotations
    if rotations is not None:
        body_positions = body_positions + np.einsum("nij,j->ni", rotations, trans_cam_body)
        body_rotations = np.einsum("nij,jk->nik", rotations, rot_cam_body)

    extras = dict(vo.extras)
    extras["cam_x_m"] = vo.positions[:, 0]
    extras["cam_y_m"] = vo.positions[:, 1]
    extras["cam_z_m"] = vo.positions[:, 2]
    extras["body_x_m"] = body_positions[:, 0]
    extras["body_y_m"] = body_positions[:, 1]
    extras["body_z_m"] = body_positions[:, 2]
    return Trajectory(
        vo.name,
        vo.stamps,
        body_positions,
        body_rotations,
        extras=extras,
        source_format="sf_vo_body",
    )


def vo_valid_segment_indices(vo: Trajectory) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """按 reset_count 连续段筛选 VO 有效段。

    规则来自需求文档：
    - reset_count 变化代表 VO 重新初始化，新段不能和旧段混成一条连续轨迹；
    - 每段 duration < 10 s 或 frame count < 200 都视为无效，先过滤；
    - 剩余有效段会重新编号为 evaluation_segment_id，供 Sim3 分段对齐和 3D 起终点显示使用。
    """
    reset_count = trajectory_extra_or_nan(vo, "reset_count")
    n = len(vo.positions)
    if n == 0:
        return np.asarray([], dtype=int), np.asarray([], dtype=int), {
            "segments": [],
            "valid_segment_count": 0,
            "invalid_segment_count": 0,
            "dropped_pose_count": 0,
        }

    starts = [0]
    for idx in range(n - 1):
        current = reset_count[idx]
        nxt = reset_count[idx + 1]
        changed = current != nxt
        if not np.isfinite(current) or not np.isfinite(nxt):
            changed = True
        if changed:
            starts.append(idx + 1)
    starts.append(n)

    valid_indices: list[int] = []
    valid_segment_ids: list[int] = []
    segment_infos: list[dict[str, Any]] = []
    next_valid_segment_id = 0
    for raw_segment_id, (start, end) in enumerate(zip(starts[:-1], starts[1:])):
        count = int(end - start)
        duration_s = float(vo.stamps[end - 1] - vo.stamps[start]) if count > 1 else 0.0
        valid = count >= VO_MIN_VALID_SEGMENT_FRAMES and duration_s >= VO_MIN_VALID_SEGMENT_DURATION_S
        info = {
            "raw_segment_id": int(raw_segment_id),
            "start_index": int(start),
            "end_index": int(end),
            "count": count,
            "duration_s": duration_s,
            "reset_count": float(reset_count[start]) if np.isfinite(reset_count[start]) else math.nan,
            "valid": bool(valid),
        }
        if valid:
            segment_indices = list(range(start, end))
            valid_indices.extend(segment_indices)
            valid_segment_ids.extend([next_valid_segment_id] * count)
            info["evaluation_segment_id"] = int(next_valid_segment_id)
            next_valid_segment_id += 1
        segment_infos.append(info)

    valid_idx_arr = np.asarray(valid_indices, dtype=int)
    valid_seg_arr = np.asarray(valid_segment_ids, dtype=int)
    return valid_idx_arr, valid_seg_arr, {
        "min_duration_s": float(VO_MIN_VALID_SEGMENT_DURATION_S),
        "min_frames": int(VO_MIN_VALID_SEGMENT_FRAMES),
        "segments": segment_infos,
        "valid_segment_count": int(next_valid_segment_id),
        "invalid_segment_count": int(sum(1 for item in segment_infos if not item["valid"])),
        "dropped_pose_count": int(n - len(valid_idx_arr)),
    }


def _required_extra(traj: Trajectory, key: str) -> np.ndarray:
    values = traj.extras.get(key)
    if values is None:
        raise ValueError(f"{traj.name}: missing required trajectory extra '{key}'")
    arr = np.asarray(values, dtype=float)
    if len(arr) != len(traj.positions):
        raise ValueError(f"{traj.name}: extra '{key}' length mismatch")
    return arr


def geodetic_to_ned(
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
    altitude_m: np.ndarray,
    home_point: HomePoint,
) -> np.ndarray:
    """WGS84 经纬高转以 home_point 为原点的 NED。"""
    lat = np.asarray(latitude_deg, dtype=float).reshape(-1)
    lon = np.asarray(longitude_deg, dtype=float).reshape(-1)
    alt = np.asarray(altitude_m, dtype=float).reshape(-1)
    if not (len(lat) == len(lon) == len(alt)):
        raise ValueError("latitude/longitude/altitude arrays must have the same length")

    ecef = geodetic_to_ecef(lat, lon, alt)
    home_ecef = geodetic_to_ecef(
        np.asarray([home_point.latitude], dtype=float),
        np.asarray([home_point.longitude], dtype=float),
        np.asarray([home_point.altitude_msl], dtype=float),
    )[0]
    lat0 = math.radians(float(home_point.latitude))
    lon0 = math.radians(float(home_point.longitude))
    sin_lat0, cos_lat0 = math.sin(lat0), math.cos(lat0)
    sin_lon0, cos_lon0 = math.sin(lon0), math.cos(lon0)
    ecef_to_ned = np.asarray(
        [
            [-sin_lat0 * cos_lon0, -sin_lat0 * sin_lon0, cos_lat0],
            [-sin_lon0, cos_lon0, 0.0],
            [-cos_lat0 * cos_lon0, -cos_lat0 * sin_lon0, -sin_lat0],
        ],
        dtype=float,
    )
    delta = ecef - home_ecef
    return delta @ ecef_to_ned.T


def geodetic_to_ecef(latitude_deg: np.ndarray, longitude_deg: np.ndarray, altitude_m: np.ndarray) -> np.ndarray:
    """WGS84 经纬高转 ECEF。"""
    lat = np.deg2rad(np.asarray(latitude_deg, dtype=float).reshape(-1))
    lon = np.deg2rad(np.asarray(longitude_deg, dtype=float).reshape(-1))
    alt = np.asarray(altitude_m, dtype=float).reshape(-1)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)
    radius = WGS84_A_M / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (radius + alt) * cos_lat * cos_lon
    y = (radius + alt) * cos_lat * sin_lon
    z = (radius * (1.0 - WGS84_E2) + alt) * sin_lat
    return np.column_stack([x, y, z])


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


def evaluate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    """通用轨迹评估入口：输入 GT/reference 和 estimate，输出完整 report。

    这里是 VLOC 和 VO 都会复用的核心计算层：
    - VLOC 入口会先把 nav/vloc 都转成 body/NED，再固定不对齐地调用这里。
    - VO 入口会先把 camera pose 转成 body pose、按 reset_count 筛掉短段，再用分段 Sim3 调用这里。
    - TUM/测试入口也可以直接传两条 Trajectory 进来。

    流程对应页面上的“运行结果、可视化、明细与导出”：
    1. 时间同步 -> association / coverage。
    2. 大跳变诊断 -> discontinuities。
    3. 对每个选中连续段做对齐和误差计算。
    4. 汇总 ATE/RPE/局部尺度/runtime 等指标。
    5. 返回 report dict，app.py 只负责展示这个 report。

    来源对应：
    - ATE/RPE 主干来自 Sturm12 和 Zhang18。
    - 长序列覆盖率和断点是 Schubert18/Delmerico18 场景下的工程扩展。
    - runtime 统计来自 Delmerico18 对飞行机器人实时性的关注。
    """
    cfg = config or EvaluationConfig()
    is_vo_workflow = "evaluation_segment_id" in est.extras
    alignment_mode = VO_ALIGNMENT_MODE if is_vo_workflow else VLOC_ALIGNMENT_MODE
    segment_policy = VO_SEGMENT_POLICY if is_vo_workflow else VLOC_SEGMENT_POLICY
    max_interpolation_gap_s = VO_FIXED_MAX_INTERPOLATION_GAP_S if is_vo_workflow else VLOC_FIXED_MAX_INTERPOLATION_GAP_S

    # 1. 时间同步：默认以 estimate 时间戳为评估基准，把 GT/reference 插值到 estimate 时刻。
    #    这样 GT=0.1/0.3/0.5、estimate=0.2/0.4/0.6 的相位错开数据不会被错误丢弃。
    original_gt = gt
    original_est = est
    gt, est, gt_idx, est_idx, assoc = prepare_evaluation_trajectories(
        original_gt,
        original_est,
        max_interpolation_gap_s=max_interpolation_gap_s,
    )
    if len(gt_idx) < 2:
        raise ValueError("Need at least two associated poses to evaluate a trajectory")

    # 2. 先在同步后的原始匹配序列上诊断断点/跳变。
    #    sf_vo 会把 reset_count 分段结果写入 evaluation_segment_id，因此 reset 边界也会被标为断点；
    #    sf_vloc 没有 VO reset 分段时，则主要看 GT/estimate 步长和时间 gap。
    original_match_count = int(len(gt_idx))
    original_gt_pos = gt.positions[gt_idx]
    original_est_pos = est.positions[est_idx]
    original_stamps = gt.stamps[gt_idx]
    forced_segment_ids = None
    if "evaluation_segment_id" in est.extras:
        candidate_segment_ids = np.asarray(est.extras["evaluation_segment_id"])
        if len(candidate_segment_ids) == len(est.positions):
            forced_segment_ids = candidate_segment_ids[est_idx]
    discontinuities_all = detect_associated_discontinuities(
        original_stamps,
        original_gt_pos,
        original_est_pos,
        step_threshold_m=FIXED_DISCONTINUITY_STEP_M,
        time_gap_threshold_s=FIXED_DISCONTINUITY_TIME_GAP_S,
        forced_segment_ids=forced_segment_ids,
    )
    eval_ranges = select_evaluation_segments(discontinuities_all["segments"], segment_policy, original_match_count)
    if not eval_ranges:
        raise ValueError("No continuous segment contains at least two matched poses")
    # 这些列表会收集每个连续段的结果，最后统一 concat/describe。
    per_pose_frames: list[pd.DataFrame] = []
    pos_error_parts: list[np.ndarray] = []
    horizontal_error_parts: list[np.ndarray] = []
    vertical_error_signed_parts: list[np.ndarray] = []
    vertical_error_abs_parts: list[np.ndarray] = []
    orientation_error_parts: list[np.ndarray] = []
    yaw_error_signed_parts: list[np.ndarray] = []
    yaw_error_abs_parts: list[np.ndarray] = []
    rpe_trans_parts: list[np.ndarray] = []
    rpe_rot_parts: list[np.ndarray] = []
    used_gt_indices: list[np.ndarray] = []
    used_est_indices: list[np.ndarray] = []
    used_match_indices: list[np.ndarray] = []
    alignments: list[dict[str, Any]] = []
    sim3_gt_export_frames: list[pd.DataFrame] = []
    sim3_vo_export_frames: list[pd.DataFrame] = []
    rpe_frame_export_frames: list[pd.DataFrame] = []
    scale_frame_export_frames: list[pd.DataFrame] = []
    total_gt_path_m = 0.0
    total_raw_est_path_m = 0.0
    total_aligned_est_path_m = 0.0
    total_duration_s = 0.0
    distance_offset = 0.0

    for seg_id, seg in enumerate(eval_ranges):
        # 4. 根据连续段策略切片。
        #    sf_vloc 固定基本是一整段有效 vloc 时间戳；sf_vo 固定按 reset_count 连续段分别评估。
        start = int(seg["start"])
        end = int(seg["end"])
        cur_gt_idx = gt_idx[start:end]
        cur_est_idx = est_idx[start:end]
        if len(cur_gt_idx) < 2:
            continue

        gt_pos = gt.positions[cur_gt_idx]
        est_pos = est.positions[cur_est_idx]
        gt_rot = gt.rotations[cur_gt_idx] if gt.rotations is not None else None
        est_rot_raw = est.rotations[cur_est_idx] if est.rotations is not None else None
        est_rot = est_rot_raw
        stamps = gt.stamps[cur_gt_idx]

        # 5. 对齐 estimate 到 GT 坐标系。
        #    sf_vloc 固定 alignment=none，位置误差就是 nav-vloc 原始坐标差；
        #    sf_vo 固定 alignment=sim3，位置误差基于每段 Sim3 后的 aligned VO。
        alignment = compute_alignment(gt_pos, est_pos, gt_rot, est_rot, mode=alignment_mode)
        alignment["segment_id"] = int(seg_id)
        alignment["start_match_index"] = start
        alignment["end_match_index"] = end
        alignments.append(alignment)

        est_pos_aligned = apply_alignment(est_pos, alignment)
        est_rot_aligned = apply_rotation_alignment(est_rot, alignment) if est_rot is not None else None

        # Excel 导出固定保留一份 Sim3 中间轨迹。
        # 对 VO，这就是需求文档中的分段 Sim3 输出；对 VLOC，虽然主评估不使用 Sim3，
        # 这个 sheet 仍可作为诊断中间结果，且不会影响 VLOC 页面指标。
        sim3_alignment = compute_alignment(gt_pos, est_pos, gt_rot, est_rot, mode="sim3")
        sim3_est_pos = apply_alignment(est_pos, sim3_alignment)
        sim3_est_rot = apply_rotation_alignment(est_rot, sim3_alignment) if est_rot is not None else None
        sim3_extra = {
            "segment_id": np.full(len(stamps), int(seg_id), dtype=int),
            "match_index": np.arange(start, end, dtype=int),
        }
        sim3_extra.update(alignment_export_columns(sim3_alignment, len(stamps), "sim3"))
        sim3_gt_export_frames.append(tum_dataframe_from_arrays(stamps, gt_pos, gt_rot, extra=sim3_extra))
        sim3_vo_export_frames.append(tum_dataframe_from_arrays(stamps, sim3_est_pos, sim3_est_rot, extra=sim3_extra))

        # 6. ATE 逐帧误差：
        #    error_m -> ate_position_m，horizontal_error_m -> ate_horizontal_m，
        #    vertical_error_m -> ate_vertical_m。
        #    来源：error_m 直接对应 Sturm12/Zhang18 的 ATE；
        #    horizontal/vertical 是本系统面向无人机航线偏差和高度安全做的 ATE 分量扩展。
        errors = est_pos_aligned - gt_pos
        x_error_m = errors[:, 0]
        y_error_m = errors[:, 1]
        z_error_m = errors[:, 2]
        pos_error_m = np.linalg.norm(errors, axis=1)
        horizontal_error_m = np.linalg.norm(errors[:, :2], axis=1)
        vertical_error_signed_m = z_error_m
        vertical_error_abs_m = np.abs(vertical_error_signed_m)
        local_distance_m = path_distance(gt_pos)
        plot_distance_m = local_distance_m + distance_offset

        orientation_error_deg = None
        yaw_error_signed_deg = None
        yaw_error_abs_deg = None
        gt_ypr_deg = None
        est_ypr_deg = None
        ypr_error_signed_deg = None
        ypr_error_abs_deg = None
        if gt_rot is not None and est_rot_aligned is not None:
            # 7. 如果输入含姿态，额外统计 orientation/yaw ATE。
            #    来源：orientation_error_deg 来自 Zhang18/Schubert18 的 SE(3) 姿态误差语境；
            #    yaw_error_deg 是无人机航向分析扩展，不是 5 篇论文的独立排行榜指标。
            orientation_error_deg = np.degrees(rotation_errors(gt_rot, est_rot_aligned))
            gt_ypr = euler_yaw_pitch_roll_from_matrix(gt_rot)
            est_ypr = euler_yaw_pitch_roll_from_matrix(est_rot_aligned)
            ypr_error_signed = wrap_pi(est_ypr - gt_ypr)
            gt_ypr_deg = np.degrees(gt_ypr)
            est_ypr_deg = np.degrees(est_ypr)
            ypr_error_signed_deg = np.degrees(ypr_error_signed)
            ypr_error_abs_deg = np.abs(ypr_error_signed_deg)
            yaw_error_signed_deg = ypr_error_signed_deg[:, 0]
            yaw_error_abs_deg = np.abs(yaw_error_signed_deg)
            orientation_error_parts.append(orientation_error_deg)
            yaw_error_signed_parts.append(yaw_error_signed_deg)
            yaw_error_abs_parts.append(yaw_error_abs_deg)

        # 8. RPE 相对位姿误差，对应页面“RPE RMSE”和 Excel 的 rpe_per_frame。
        #    unit=frames 时每个 i 取 j=i+N；unit=meters 时按 GT 累计路程找目标距离 ± tolerance 内的候选终点，
        #    并选择 RPE 平移误差最小的候选。来源：Sturm12 RPE；距离窗口是长航程无人机评估扩展。
        rpe_frame = rpe_frame_dataframe(
            gt_pos,
            est_pos_aligned,
            gt_rot,
            est_rot_aligned,
            stamps,
            segment_id=int(seg_id),
            match_indices=np.arange(start, end, dtype=int),
            delta=max(1, int(cfg.rpe_delta_frames)),
            delta_value=cfg.rpe_delta_value,
            delta_unit=cfg.rpe_delta_unit,
            distance_tolerance_ratio=cfg.rpe_distance_tolerance_ratio,
        )
        rpe_frame_export_frames.append(rpe_frame)
        rpe_valid = rpe_frame["rpe_available"].to_numpy(dtype=bool) if "rpe_available" in rpe_frame else np.asarray([], dtype=bool)
        rpe_trans = rpe_frame.loc[rpe_valid, "rpe_translation_m"].to_numpy(dtype=float) if len(rpe_frame) else np.asarray([], dtype=float)
        rpe_rot_deg = rpe_frame.loc[rpe_valid, "rpe_rotation_deg"].dropna().to_numpy(dtype=float) if len(rpe_frame) else np.asarray([], dtype=float)
        rpe_trans_parts.append(rpe_trans)
        if len(rpe_rot_deg):
            rpe_rot_parts.append(rpe_rot_deg)
        scale_frame = scale_frame_dataframe(
            gt_pos,
            est_pos,
            stamps,
            segment_id=int(seg_id),
            match_indices=np.arange(start, end, dtype=int),
            delta=max(1, int(cfg.rpe_delta_frames)),
            delta_value=cfg.scale_delta_value,
            delta_unit=cfg.scale_delta_unit,
            distance_tolerance_ratio=cfg.scale_distance_tolerance_ratio,
        )
        scale_frame_export_frames.append(scale_frame)

        # 10. per_pose 是每帧明细表，既用于误差曲线，也可导出 CSV。
        frame = pd.DataFrame(
            {
                "timestamp": stamps,
                "segment_id": int(seg_id),
                "distance_m": plot_distance_m,
                "segment_distance_m": local_distance_m,
                "gt_x_m": gt_pos[:, 0],
                "gt_y_m": gt_pos[:, 1],
                "gt_z_m": gt_pos[:, 2],
                "est_x_aligned_m": est_pos_aligned[:, 0],
                "est_y_aligned_m": est_pos_aligned[:, 1],
                "est_z_aligned_m": est_pos_aligned[:, 2],
                "x_error_m": x_error_m,
                "y_error_m": y_error_m,
                "z_error_m": z_error_m,
                "error_m": pos_error_m,
                "horizontal_error_m": horizontal_error_m,
                "vertical_error_signed_m": vertical_error_signed_m,
                "vertical_error_abs_m": vertical_error_abs_m,
                "vertical_error_m": vertical_error_abs_m,
            }
        )
        if orientation_error_deg is not None:
            frame["orientation_error_deg"] = orientation_error_deg
            frame["gt_yaw_deg"] = gt_ypr_deg[:, 0]
            frame["gt_pitch_deg"] = gt_ypr_deg[:, 1]
            frame["gt_roll_deg"] = gt_ypr_deg[:, 2]
            frame["est_yaw_aligned_deg"] = est_ypr_deg[:, 0]
            frame["est_pitch_aligned_deg"] = est_ypr_deg[:, 1]
            frame["est_roll_aligned_deg"] = est_ypr_deg[:, 2]
            frame["yaw_error_signed_deg"] = yaw_error_signed_deg
            frame["yaw_error_abs_deg"] = yaw_error_abs_deg
            frame["yaw_error_deg"] = yaw_error_abs_deg
            frame["pitch_error_signed_deg"] = ypr_error_signed_deg[:, 1]
            frame["pitch_error_abs_deg"] = ypr_error_abs_deg[:, 1]
            frame["roll_error_signed_deg"] = ypr_error_signed_deg[:, 2]
            frame["roll_error_abs_deg"] = ypr_error_abs_deg[:, 2]

        per_pose_frames.append(frame)
        pos_error_parts.append(pos_error_m)
        horizontal_error_parts.append(horizontal_error_m)
        vertical_error_signed_parts.append(vertical_error_signed_m)
        vertical_error_abs_parts.append(vertical_error_abs_m)
        used_gt_indices.append(cur_gt_idx)
        used_est_indices.append(cur_est_idx)
        used_match_indices.append(np.arange(start, end, dtype=int))

        # 11. summary 所需的总路程、raw estimate 路程、对齐后 estimate 路程、耗时等。
        #     来源：路程/速度支撑 Geiger12 风格统计；duration/runtime 支撑 Delmerico18 实时性分析；
        #     raw_path_scale_ratio 支撑 Zhang18 的尺度可观性判断。
        seg_gt_path = float(local_distance_m[-1])
        total_gt_path_m += seg_gt_path
        total_raw_est_path_m += float(path_distance(est_pos)[-1])
        total_aligned_est_path_m += float(path_distance(est_pos_aligned)[-1])
        total_duration_s += float(stamps[-1] - stamps[0]) if len(stamps) > 1 else 0.0
        distance_offset += seg_gt_path

    if not per_pose_frames:
        raise ValueError("No continuous segment contains at least two matched poses")

    per_pose = pd.concat(per_pose_frames, ignore_index=True)
    rpe_per_frame = pd.concat(rpe_frame_export_frames, ignore_index=True) if rpe_frame_export_frames else pd.DataFrame()
    scale_per_frame = pd.concat(scale_frame_export_frames, ignore_index=True) if scale_frame_export_frames else pd.DataFrame()
    # 12. 统计汇总：describe() 会统一给出 count/rmse/mean/median/std/min/max/p95/p99。
    pos_error_m = np.concatenate(pos_error_parts)
    horizontal_error_m = np.concatenate(horizontal_error_parts)
    vertical_error_signed_m = np.concatenate(vertical_error_signed_parts)
    vertical_error_abs_m = np.concatenate(vertical_error_abs_parts)
    orientation_error_deg = np.concatenate(orientation_error_parts) if orientation_error_parts else None
    yaw_error_signed_deg = np.concatenate(yaw_error_signed_parts) if yaw_error_signed_parts else None
    yaw_error_abs_deg = np.concatenate(yaw_error_abs_parts) if yaw_error_abs_parts else None
    rpe_trans = np.concatenate(rpe_trans_parts) if rpe_trans_parts else np.asarray([], dtype=float)
    rpe_rot_deg = np.concatenate(rpe_rot_parts) if rpe_rot_parts else np.asarray([], dtype=float)
    used_gt_idx = np.concatenate(used_gt_indices)
    used_est_idx = np.concatenate(used_est_indices)
    used_match_idx = np.concatenate(used_match_indices)
    visual_segment_ids = np.asarray(discontinuities_all.get("segment_ids", []), dtype=int)
    if len(visual_segment_ids) and len(used_match_idx) == len(per_pose):
        per_pose["visual_segment_id"] = visual_segment_ids[used_match_idx]
    else:
        per_pose["visual_segment_id"] = per_pose["segment_id"].to_numpy(dtype=int)
    alignment = aggregate_alignment(alignments, alignment_mode)
    ate_report = {
        "primary_label": f"{alignment_mode.upper()} ATE",
        "primary_position_m": describe(pos_error_m),
    }
    rpe_delta_info = normalize_rpe_delta_config(cfg)
    rpe = {
        **rpe_delta_info,
        "count": int(len(rpe_trans)),
        "translation_m": describe(rpe_trans),
        "rotation_deg": describe(rpe_rot_deg) if len(rpe_rot_deg) else None,
    }
    scale_valid = scale_per_frame["scale_available"].to_numpy(dtype=bool) if "scale_available" in scale_per_frame else np.asarray([], dtype=bool)
    local_sim3_scale = scale_per_frame.loc[scale_valid, "local_sim3_scale"].to_numpy(dtype=float) if len(scale_per_frame) else np.asarray([], dtype=float)
    local_scale_ratio = scale_per_frame.loc[scale_valid, "local_scale_ratio_est_over_gt"].to_numpy(dtype=float) if len(scale_per_frame) else np.asarray([], dtype=float)
    local_scale_drift = scale_per_frame.loc[scale_valid, "local_scale_drift_percent"].to_numpy(dtype=float) if len(scale_per_frame) else np.asarray([], dtype=float)
    scale_delta_info = normalize_scale_delta_config(cfg)
    scale_frame_delta = {
        **scale_delta_info,
        "count": int(len(local_sim3_scale)),
        "local_sim3_scale": describe(local_sim3_scale),
        "local_scale_ratio_est_over_gt": describe(local_scale_ratio),
        "local_scale_drift_percent": describe(local_scale_drift),
    }
    selected_segment = {
        "policy": segment_policy,
        "segments": [{"start_index": int(seg["start"]), "end_index": int(seg["end"]), "count": int(seg["count"])} for seg in eval_ranges],
        "selected_matches": int(len(used_gt_idx)),
        "dropped_matches": int(original_match_count - len(used_gt_idx)),
    }

    # 14. summary 是页面第一屏指标卡的主要来源。
    #     coverage/path/runtime 是物流无人机长航程可用性扩展；
    #     这些扩展的动机来自 Schubert18 长序列 VIO 和 Delmerico18 飞行机器人 benchmark。
    summary = {
        "gt_path_length_m": float(total_gt_path_m),
        "est_path_length_raw_m": float(total_raw_est_path_m),
        "est_path_length_aligned_m": float(total_aligned_est_path_m),
        "duration_s": float(total_duration_s),
        "matched_poses": int(len(used_gt_idx)),
        "original_matched_poses": original_match_count,
        "gt_poses": int(len(original_gt.positions)),
        "est_poses": int(len(original_est.positions)),
        "coverage_ratio": _gt_coverage_ratio(total_duration_s, original_gt),
        "gt_pose_coverage_ratio": _gt_coverage_ratio(total_duration_s, original_gt),
        "gt_time_coverage_ratio": float(total_duration_s / original_gt.duration_s) if original_gt.duration_s > 0 else 1.0,
        "est_pose_coverage_ratio": float(len(used_est_idx) / max(1, len(original_est.positions))),
        "raw_path_scale_ratio_est_over_gt": float(total_raw_est_path_m / total_gt_path_m) if total_gt_path_m > 0 else math.nan,
    }

    # 15. report 是唯一对外返回值。app.py 的所有图表/表格/下载都从这里取数据。
    #     新增 report 指标时，同步更新 METRIC_CODE_MAP 和 README 的指标-代码总表。
    trajectory_exports = build_trajectory_export_sheets(
        original_gt,
        original_est,
        gt,
        est,
        pd.concat(sim3_gt_export_frames, ignore_index=True) if sim3_gt_export_frames else pd.DataFrame(),
        pd.concat(sim3_vo_export_frames, ignore_index=True) if sim3_vo_export_frames else pd.DataFrame(),
        ate_frame_dataframe(per_pose),
        rpe_per_frame,
        scale_per_frame,
    )
    report = {
        "inputs": {
            "ground_truth": {"name": original_gt.name, "format": original_gt.source_format},
            "estimate": {"name": original_est.name, "format": original_est.source_format},
        },
        "config": _dataclass_to_jsonable(cfg),
        "association": assoc,
        "discontinuities": {
            "all_matches": discontinuities_all,
            "selected_segment": selected_segment,
        },
        "alignment": alignment,
        "summary": summary,
        "ate": ate_report,
        "ate_position_m": describe(pos_error_m),
        "ate_horizontal_m": describe(horizontal_error_m),
        "ate_vertical_m": describe(vertical_error_abs_m),
        "vertical_error_signed_m": describe(vertical_error_signed_m),
        "vertical_error_abs_m": describe(vertical_error_abs_m),
        "ate_orientation_deg": describe(orientation_error_deg) if orientation_error_deg is not None else None,
        "ate_yaw_deg": describe(yaw_error_abs_deg) if yaw_error_abs_deg is not None else None,
        "yaw_error_signed_deg": describe(yaw_error_signed_deg) if yaw_error_signed_deg is not None else None,
        "yaw_error_abs_deg": describe(yaw_error_abs_deg) if yaw_error_abs_deg is not None else None,
        "rpe_frame_delta": rpe,
        "scale_frame_delta": scale_frame_delta,
        "per_pose": per_pose,
        "trajectory_exports": trajectory_exports,
    }
    return report


def prepare_evaluation_trajectories(
    gt: Trajectory,
    est: Trajectory,
    *,
    max_interpolation_gap_s: float,
) -> tuple[Trajectory, Trajectory, np.ndarray, np.ndarray, dict[str, Any]]:
    """把 GT/reference 和 estimate 准备成同一时间轴上的评估序列。

    代码意义：
    - 固定以 estimate 时间戳为基准，把 GT/reference 插值到 estimate 时刻。
      这适合物流无人机/IMU GT 长时间记录场景，算法输出只有运行段也不会引入无关 GT。

    指标对应：
    - 返回的 assoc 会进入 report["association"]。
    - build_associated_trajectories() 会先构造同一时间轴上的 gt_eval/est_eval；
      这里返回的 gt_idx/est_idx 只是兼容旧评估主流程的等长索引，不再表示插值模式下的原始离散 GT 索引。

    来源对应：
    - interpolate_gt 是工程扩展：Schubert18/TUM VI 提供高频同步 GT 的评估语境；
      对物流无人机这种“GT 全程跑、estimate 只在算法段输出”的数据，按 estimate 时间戳插 GT 更合理。
    """
    gt_eval, est_eval, assoc = build_associated_trajectories(
        gt,
        est,
        max_interpolation_gap_s=max_interpolation_gap_s,
    )
    idx = np.arange(len(gt_eval.positions), dtype=int)
    return gt_eval, est_eval, idx, idx, assoc


def build_associated_trajectories(
    gt: Trajectory,
    est: Trajectory,
    max_interpolation_gap_s: float = VLOC_FIXED_MAX_INTERPOLATION_GAP_S,
) -> tuple[Trajectory, Trajectory, dict[str, Any]]:
    """构造同一时间轴上的 GT/reference 和 estimate 评估轨迹。

    代码意义：
    - 固定以 estimate 时间戳为基准，把 GT position 线性插值、GT rotation 用 SLERP 插值到 estimate 时刻。

    指标对应：
    - 返回的 assoc 直接进入 report["association"]，报告可以看到插值覆盖率、丢帧数量和 GT 插值间隔。
    - 后续 ATE/RPE/RE/断点检测都只看返回的 gt_eval/est_eval，不再关心原始采样频率是否相同。
    """
    return interpolate_gt_to_est_timestamps(gt, est, max_interpolation_gap_s=max_interpolation_gap_s)


def interpolate_gt_to_est_timestamps(
    gt: Trajectory,
    est: Trajectory,
    *,
    max_interpolation_gap_s: float,
) -> tuple[Trajectory, Trajectory, dict[str, Any]]:
    """将 GT/reference 插值到 estimate 时间戳。

    代码意义：
    - estimate 时间戳作为评估时间戳，时间偏移固定为 0。
    - 只保留落在 GT 时间范围内的 estimate 点，避免拿没有 GT 的算法输出段做统计。
    - max_interpolation_gap_s 用来阻止跨很长 GT 缺口插值，避免虚假的平滑 GT。
    - 位置用线性插值；姿态如果存在，后续 interpolate_rotations_from_brackets() 使用 SLERP。

    指标对应：
    - report["association"]["matches"]: 最终参与评估的 estimate 时间戳数量。
    - report["association"]["dropped_est_outside_gt_range"]: 因超出 GT 时间范围丢弃的 estimate 点。
    - report["association"]["dropped_est_large_gt_gap"]: 因 GT 插值间隔过大丢弃的 estimate 点。
    - report["association"]["max_interpolation_gap_s"]: 实际使用样本中的最大 GT 插值间隔。

    来源对应：
    - 不是 5 篇论文里的固定公式，是本系统的时间同步工程扩展。
    - 目的仍然服务 Sturm12/Zhang18 的 ATE/RPE：必须先把两条轨迹放到可比时间轴上。
    """
    return interpolate_reference_to_estimate(
        gt,
        est,
        max_interpolation_gap_s=max_interpolation_gap_s,
    )


def interpolate_reference_to_estimate(
    reference: Trajectory,
    estimate: Trajectory,
    *,
    max_interpolation_gap_s: float = VLOC_FIXED_MAX_INTERPOLATION_GAP_S,
) -> tuple[Trajectory, Trajectory, dict[str, Any]]:
    """把 reference 轨迹插值到 estimate 时间戳。

    这是当前 sf_vloc/sf_vo 的固定时间同步方法：
    - estimate 自己的时间戳作为评估行；
    - reference 的查询时刻是 estimate.stamps；
    - 超出 reference 时间范围、时间戳非法或左右 reference 样本间隔超过 max_interpolation_gap_s 的 estimate 帧会被丢弃，不允许外推；
    - 返回的 ref_interp 和 est_matched 等长，且都使用原始 estimate 时间戳，target_stamp 会保存在 extras 中方便排查固定时间偏移。
    """
    ref_unique = _unique_timestamp_trajectory(reference)
    duplicate_timestamp_count = int(len(reference.stamps) - len(ref_unique.stamps))
    shifted_est_stamps = estimate.stamps + FIXED_TIME_OFFSET_S
    finite_est = np.isfinite(shifted_est_stamps)
    before_range = finite_est & (shifted_est_stamps < ref_unique.stamps[0])
    after_range = finite_est & (shifted_est_stamps > ref_unique.stamps[-1])
    in_range = finite_est & ~before_range & ~after_range

    candidate_est_indices = np.flatnonzero(in_range)
    target_candidates = shifted_est_stamps[candidate_est_indices]
    bracket_info = interpolation_brackets(ref_unique.stamps, target_candidates)
    candidate_gaps = bracket_info["gap_s"]
    candidate_valid_timestamp = bracket_info["valid_timestamp"]
    valid_gap = candidate_gaps <= float(max_interpolation_gap_s)
    valid = candidate_valid_timestamp & valid_gap

    est_indices = candidate_est_indices[valid]
    target_stamps = target_candidates[valid]
    common_stamps = estimate.stamps[est_indices]
    bracket_gaps = candidate_gaps[valid]
    left_indices = bracket_info["left_index"][valid]
    right_indices = bracket_info["right_index"][valid]
    alphas = bracket_info["alpha"][valid]
    left_offsets = bracket_info["left_offset_s"][valid]
    right_offsets = bracket_info["right_offset_s"][valid]
    nearest_side_offsets = bracket_info["nearest_side_offset_s"][valid]

    dropped_invalid_timestamp = int(np.count_nonzero(~finite_est) + np.count_nonzero(in_range) - np.count_nonzero(candidate_valid_timestamp))
    dropped_before = int(np.count_nonzero(before_range))
    dropped_after = int(np.count_nonzero(after_range))
    dropped_gap = int(np.count_nonzero(candidate_valid_timestamp & ~valid_gap))

    ref_positions = interpolate_positions_from_brackets(ref_unique.positions, left_indices, right_indices, alphas)
    if ref_unique.rotations is not None:
        ref_rotations = interpolate_rotations_from_brackets(ref_unique.rotations, left_indices, right_indices, alphas)
        rotation_method_report = "slerp"
    else:
        ref_rotations = None
        rotation_method_report = "skipped_no_reference_rotation"

    est_matched = subset_trajectory(estimate, est_indices, stamps_override=common_stamps)
    est_matched.extras["source_index"] = est_indices
    est_matched.extras["original_est_stamp"] = estimate.stamps[est_indices]
    est_matched.extras["target_stamp"] = target_stamps
    ref_interp = Trajectory(
        f"{reference.name}_interpolated_to_{estimate.name}",
        common_stamps,
        ref_positions,
        ref_rotations,
        extras={
            "source_index": est_indices,
            "original_est_stamp": estimate.stamps[est_indices],
            "target_stamp": target_stamps,
            "gt_left_index": left_indices,
            "gt_right_index": right_indices,
            "interp_alpha": alphas,
            "gt_bracket_gap_s": bracket_gaps,
        },
        source_format=f"{reference.source_format}+interpolated",
    )
    matched_duration = float(common_stamps[-1] - common_stamps[0]) if len(common_stamps) > 1 else 0.0
    info = {
        "method": "interpolate_gt",
        "mode": "interpolate_gt",
        "target": "estimate_timestamps",
        "interpolated": True,
        "position_method": "linear",
        "rotation_method": rotation_method_report,
        "time_offset_s": float(FIXED_TIME_OFFSET_S),
        "max_interpolation_gap_s": max_interpolation_gap_s,
        "max_interpolation_gap_s_allowed": max_interpolation_gap_s,
        "max_interpolation_gap_config_s": max_interpolation_gap_s,
        "allow_extrapolation": False,
        "estimate_count_input": int(len(estimate.stamps)),
        "reference_count_input": int(len(reference.stamps)),
        "estimate_pose_count": int(len(estimate.positions)),
        "reference_pose_count": int(len(reference.positions)),
        "reference_duplicate_timestamp_count": duplicate_timestamp_count,
        "matched_count": int(len(est_indices)),
        "matches": int(len(est_indices)),
        "dropped_count": int(len(estimate.stamps) - len(est_indices)),
        "dropped": int(len(estimate.stamps) - len(est_indices)),
        "coverage_estimate_ratio": float(len(est_indices) / max(1, len(estimate.stamps))),
        "est_pose_coverage_ratio": float(len(est_indices) / max(1, len(estimate.positions))),
        "candidate_pose_count_inside_gt_range": int(len(candidate_est_indices)),
        "dropped_before_reference_range": dropped_before,
        "dropped_after_reference_range": dropped_after,
        "dropped_gt_gap_too_large": dropped_gap,
        "dropped_invalid_timestamp": dropped_invalid_timestamp,
        "outside_gt_range_count": int(dropped_before + dropped_after),
        "large_interpolation_gap_count": dropped_gap,
        "dropped_est_outside_gt_range": int(dropped_before + dropped_after),
        "dropped_est_large_gt_gap": dropped_gap,
        "max_used_gt_gap_s": float(np.max(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "mean_used_gt_gap_s": float(np.mean(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "median_used_gt_gap_s": float(np.median(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "p95_used_gt_gap_s": float(np.percentile(bracket_gaps, 95)) if len(bracket_gaps) else 0.0,
        "max_interpolation_gap_used_s": float(np.max(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "mean_interpolation_gap_s": float(np.mean(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "median_interpolation_gap_s": float(np.median(bracket_gaps)) if len(bracket_gaps) else 0.0,
        "p95_interpolation_gap_s": float(np.percentile(bracket_gaps, 95)) if len(bracket_gaps) else 0.0,
        "max_abs_time_offset_to_left_sample_s": float(np.max(left_offsets)) if len(left_offsets) else 0.0,
        "max_abs_time_offset_to_right_sample_s": float(np.max(right_offsets)) if len(right_offsets) else 0.0,
        "mean_abs_time_offset_to_left_or_right_s": float(np.mean(nearest_side_offsets)) if len(nearest_side_offsets) else 0.0,
        "gt_time_coverage_ratio": float(matched_duration / reference.duration_s) if reference.duration_s > 0 else 1.0,
    }
    if ref_unique.rotations is None:
        info["rotation_interpolation_note"] = "rotation interpolation skipped: no reference rotation"
    if info["coverage_estimate_ratio"] < 0.8:
        info["warning"] = "low interpolate_gt coverage; check timestamp units, GT/estimate time ranges, time_offset_s, and max_interpolation_gap_s"
    if not len(est_indices):
        info["warning"] = "no estimate timestamp remains after interpolation filtering"
    elif len(est_indices) < 2:
        info["warning"] = "fewer than two estimate timestamps remain after interpolation filtering"
    return ref_interp, est_matched, info


def _unique_timestamp_trajectory(traj: Trajectory) -> Trajectory:
    """Keep the first sample for duplicate timestamps before interpolation."""
    unique_stamps, unique_indices = np.unique(traj.stamps, return_index=True)
    if len(unique_stamps) == len(traj.stamps):
        return traj
    return subset_trajectory(traj, np.sort(unique_indices), stamps_override=traj.stamps[np.sort(unique_indices)])


def subset_trajectory(traj: Trajectory, indices: np.ndarray, stamps_override: np.ndarray | None = None) -> Trajectory:
    """按索引截取轨迹，并可把时间戳替换成统一后的评估时间戳。"""
    rotations = traj.rotations[indices] if traj.rotations is not None else None
    extras = {key: np.asarray(value)[indices] for key, value in traj.extras.items() if len(value) == len(traj.positions)}
    stamps = np.asarray(stamps_override, dtype=float) if stamps_override is not None else traj.stamps[indices]
    return Trajectory(traj.name, stamps, traj.positions[indices], rotations, extras=extras, source_format=traj.source_format)


def interpolate_positions_from_brackets(
    src_positions: np.ndarray,
    left_indices: np.ndarray,
    right_indices: np.ndarray,
    alphas: np.ndarray,
) -> np.ndarray:
    """使用预先计算好的左右样本和 alpha 做位置线性插值。"""
    if len(left_indices) == 0:
        return np.empty((0, 3), dtype=float)
    p0 = src_positions[left_indices]
    p1 = src_positions[right_indices]
    alpha = np.asarray(alphas, dtype=float).reshape(-1, 1)
    return (1.0 - alpha) * p0 + alpha * p1


def interpolation_brackets(
    src_stamps: np.ndarray,
    target_stamps: np.ndarray,
) -> dict[str, np.ndarray]:
    """找到每个目标时间戳两侧的 GT 样本，并计算插值诊断量。

    输出字段对应 report["association"] 和 gt_eval.extras：
    - left_index/right_index: GT 插值使用的左右样本。若目标时间戳正好命中 GT，左右索引相同。
    - alpha: 线性插值/SLERP 的比例，0 表示左端，1 表示右端。
    - gap_s: 左右 GT 样本间隔，用于 max_interpolation_gap_s 过滤。
    - nearest_side_offset_s: 目标时间戳离左右样本较近一侧的时间差，用于诊断采样偏差。
    """
    src = np.asarray(src_stamps, dtype=float)
    target = np.asarray(target_stamps, dtype=float)
    if len(src) == 0:
        raise ValueError("Cannot interpolate against an empty reference trajectory")
    insert = np.searchsorted(src, target, side="left")
    clipped_insert = np.clip(insert, 0, max(0, len(src) - 1))
    exact = (insert < len(src)) & np.isclose(src[clipped_insert], target)

    left = np.empty(len(target), dtype=int)
    right = np.empty(len(target), dtype=int)
    left[exact] = clipped_insert[exact]
    right[exact] = clipped_insert[exact]

    middle = (~exact) & (insert > 0) & (insert < len(src))
    left[middle] = insert[middle] - 1
    right[middle] = insert[middle]

    before = (~exact) & (insert <= 0)
    after = (~exact) & (insert >= len(src))
    outside = before | after
    left[outside] = np.clip(insert[outside] - 1, 0, max(0, len(src) - 1))
    right[outside] = np.clip(insert[outside], 0, max(0, len(src) - 1))

    gaps = np.zeros(len(target), dtype=float)
    gaps[middle] = src[right[middle]] - src[left[middle]]
    gaps[outside] = math.inf

    alpha = np.zeros(len(target), dtype=float)
    valid_denominator = gaps > 0
    alpha[valid_denominator] = (target[valid_denominator] - src[left[valid_denominator]]) / gaps[valid_denominator]
    alpha = np.clip(alpha, 0.0, 1.0)

    left_offset = np.abs(target - src[left])
    right_offset = np.abs(src[right] - target)
    nearest_side_offset = np.minimum(left_offset, right_offset)
    invalid = outside
    nearest_side_offset[invalid] = math.inf
    left_offset[invalid] = math.inf
    right_offset[invalid] = math.inf
    return {
        "left_index": left,
        "right_index": right,
        "alpha": alpha,
        "gap_s": gaps,
        "left_offset_s": left_offset,
        "right_offset_s": right_offset,
        "nearest_side_offset_s": nearest_side_offset,
        "valid_timestamp": np.isfinite(gaps),
    }


def interpolate_rotations_from_brackets(
    src_rotations: np.ndarray | None,
    left_indices: np.ndarray,
    right_indices: np.ndarray,
    alphas: np.ndarray,
) -> np.ndarray | None:
    """使用预先计算好的左右样本和 alpha 对旋转做 SLERP。"""
    if src_rotations is None:
        return None
    if len(left_indices) == 0:
        return np.empty((0, 3, 3), dtype=float)
    quats = matrix_to_quaternion(src_rotations)
    out = np.empty((len(left_indices), 4), dtype=float)
    for i, (left, right, alpha) in enumerate(zip(left_indices, right_indices, alphas)):
        if left == right or abs(float(alpha)) < 1e-15:
            out[i] = quats[left]
        elif abs(float(alpha) - 1.0) < 1e-15:
            out[i] = quats[right]
        else:
            out[i] = slerp_quaternion(quats[left], quats[right], float(alpha))
    return quaternion_to_matrix(out[:, 0], out[:, 1], out[:, 2], out[:, 3])


def slerp_quaternion(q0: np.ndarray, q1: np.ndarray, alpha: float) -> np.ndarray:
    """四元数球面线性插值，避免直接线性插姿态造成旋转误差。"""
    q0 = np.asarray(q0, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    q0_norm = np.linalg.norm(q0)
    q1_norm = np.linalg.norm(q1)
    if q0_norm == 0 or q1_norm == 0:
        raise ValueError("Cannot SLERP a zero-norm quaternion")
    q0 = q0 / q0_norm
    q1 = q1 / q1_norm
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    if dot > 0.9995:
        q = q0 + alpha * (q1 - q0)
        return q / np.linalg.norm(q)
    theta_0 = math.acos(float(np.clip(dot, -1.0, 1.0)))
    theta = theta_0 * alpha
    sin_theta = math.sin(theta)
    sin_theta_0 = math.sin(theta_0)
    s0 = math.cos(theta) - dot * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0
    return s0 * q0 + s1 * q1


def _gt_coverage_ratio(total_duration_s: float, original_gt: Trajectory) -> float:
    """GT 覆盖率口径：按有效评估时间窗口占原始 GT 总时长计算。"""
    return float(total_duration_s / original_gt.duration_s) if original_gt.duration_s > 0 else 1.0


def compute_alignment(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None = None,
    est_rot: np.ndarray | None = None,
    mode: str = VLOC_ALIGNMENT_MODE,
) -> dict[str, Any]:
    """计算 estimate 到 GT 的轨迹对齐变换。

    指标对应：
    - none: VLOC 固定不做轨迹对齐，直接统计 nav-vloc 坐标差。
    - sim3: VO 固定同时估计尺度/旋转/平移，适合单目 VO 或其他尺度未知 estimate。
    - alignment["scale"] 最终显示为页面“对齐尺度”。

    实现细节：
    - 位置对齐用 Umeyama SVD。输入 src=estimate，dst=GT，输出 scale/rotation/translation。
    - 所有 ATE、RPE 都基于对齐后的 est_pos_aligned 计算。

    来源对应：
    - Sturm12 的 ATE 需要先把估计轨迹配准到 GT 后再算绝对误差。
    - Zhang18 明确说明单目无尺度通常看 Sim3；VLOC 当前按需求固定为已有尺度，不做对齐。
    """
    mode = mode.lower()
    if mode == "none":
        # 不对齐模式用于调试原始坐标系；如果 GT/estimate 不在同一坐标系，误差会很大。
        return _alignment_dict(mode, 1.0, np.eye(3), np.zeros(3))
    if mode == "sim3":
        # Sim3 允许估计全局尺度。单目无尺度 VO 或其他无尺度 estimate 用它可以评估“轨迹形状”，
        # 但不能证明原始输出已经具备真实米制尺度。
        scale, rot, trans = umeyama_alignment(est_pos, gt_pos, with_scale=True)
        return _alignment_dict("sim3", scale, rot, trans)
    raise ValueError(f"Unknown alignment mode: {mode}")


def umeyama_alignment(src: np.ndarray, dst: np.ndarray, with_scale: bool) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama SVD 对齐。

    src 是 estimate，dst 是 GT。with_scale=False 得到 SE3；with_scale=True 得到 Sim3。

    代码意义：
    - 通过最小二乘求 R/t/s，使 s * R * estimate + t 尽量贴近 GT。
    - 这是 evo、rpg_trajectory_evaluation、KITTI 类评估中常见的轨迹对齐口径。
    - det 修正用于避免 SVD 给出反射矩阵；轨迹对齐必须是合法旋转。

    指标影响：
    - scale 会进入 report["alignment"]，也会影响所有对齐后的 ATE/RPE/segment 误差。
    - with_scale=True 会降低无尺度 VO 的位置误差，但 raw_path_scale_ratio 和 scale_drift 仍能暴露尺度问题。

    来源对应：
    - 对齐这个评估步骤来自 Sturm12/Zhang18；Umeyama 是这里采用的 SVD 数值实现。
    - 如果启用 Sim3，报告里的尺度结论应按 Zhang18 的“尺度可观性”来解释。
    """
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError("src and dst must have shape (N, 3)")
    if len(src) < 2:
        return 1.0, np.eye(3), dst[0] - src[0]

    # 1. 先去中心化，避免平移影响旋转和尺度估计。
    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_centered = src - mu_src
    dst_centered = dst - mu_dst

    # 2. 交叉协方差描述 estimate 与 GT 的主方向关系，SVD 从中恢复最优旋转。
    cov = (dst_centered.T @ src_centered) / len(src)
    u, singular_values, vt = np.linalg.svd(cov)
    sign = np.ones(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[-1] = -1
    s_mat = np.diag(sign)
    rot = u @ s_mat @ vt

    # 3. Sim3 模式估计尺度；SE3 模式强制 scale=1，用来检验算法本身是否有真实尺度。
    if with_scale:
        var_src = float(np.mean(np.sum(src_centered * src_centered, axis=1)))
        scale = float(np.sum(singular_values * sign) / var_src) if var_src > 0 else 1.0
    else:
        scale = 1.0

    # 4. 在旋转/尺度确定后，用两条轨迹的中心点求平移。
    trans = mu_dst - scale * (rot @ mu_src)
    return scale, rot, trans


def apply_alignment(positions: np.ndarray, alignment: dict[str, Any]) -> np.ndarray:
    """把 estimate 位置应用到 GT 坐标系。

    公式：p_aligned = scale * R * p_est + t。
    之后所有位置误差字段都基于这个结果：
    - per_pose.error_m / horizontal_error_m / vertical_error_m
    - ate_position_m / ate_horizontal_m / ate_vertical_m
    - rpe_frame_delta.translation_m
    - scale_frame_delta / scale_per_frame 中的局部尺度统计
    """
    scale = float(alignment["scale"])
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    return scale * (positions @ rot.T) + trans


def apply_rotation_alignment(rotations: np.ndarray | None, alignment: dict[str, Any]) -> np.ndarray | None:
    """把 estimate 姿态应用同一个对齐旋转。

    只应用 rotation，不应用 scale/translation，因为姿态没有尺度和平移。
    结果用于姿态 ATE、yaw 误差、RPE 旋转误差和子轨迹旋转误差。
    """
    if rotations is None:
        return None
    rot = np.asarray(alignment["rotation"], dtype=float)
    return np.einsum("ij,njk->nik", rot, rotations)


def alignment_export_columns(alignment: dict[str, Any], count: int, prefix: str) -> dict[str, Any]:
    """把 Sim3/SE3 对齐参数展开成可写入 Excel sheet 的列。

    Sim3 不是只有尺度，还包含完整变换：
    p_gt = scale * R * p_vo + t。
    因此导出中间轨迹时同时保留：
    - scale: 尺度因子；
    - rotation_r00...r22: 3x3 旋转矩阵；
    - translation_x/y/z: 平移向量。
    """
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    out: dict[str, Any] = {
        f"{prefix}_mode": np.asarray([alignment.get("mode", prefix)] * count, dtype=object),
        f"{prefix}_scale": np.full(count, float(alignment["scale"]), dtype=float),
        f"{prefix}_translation_x": np.full(count, float(trans[0]), dtype=float),
        f"{prefix}_translation_y": np.full(count, float(trans[1]), dtype=float),
        f"{prefix}_translation_z": np.full(count, float(trans[2]), dtype=float),
    }
    for row in range(3):
        for col in range(3):
            out[f"{prefix}_rotation_r{row}{col}"] = np.full(count, float(rot[row, col]), dtype=float)
    return out


def aggregate_alignment(alignments: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """聚合每个连续段的对齐信息。

    代码意义：
    - 默认系统可以按 estimate 时间戳统一评估，也可以按连续段分别对齐/评估。
    - 多段时每段都有自己的 scale/rotation/translation，这里把 scale 做 min/max/mean 汇总。

    指标对应：
    - alignment.scale: 平均对齐尺度。
    - alignment.scale_min / scale_max: 不同连续段的尺度范围。
    - alignment.segment_count: 参与对齐的连续段数量。
    - 报告里的“分段尺度变化明显”就是根据 scale_min/scale_max/scale 触发的。

    来源对应：
    - 单段 SE3/Sim3 对齐来自 Sturm12/Zhang18。
    - 分段尺度范围是工程扩展，用来暴露长航程单目 VO 在不同连续段的尺度不稳定。
    """
    if not alignments:
        return _alignment_dict(mode, 1.0, np.eye(3), np.zeros(3))
    scales = np.asarray([float(item["scale"]) for item in alignments], dtype=float)
    return {
        "mode": "per_segment",
        "base_mode": mode,
        "scale": float(np.mean(scales)),
        "scale_min": float(np.min(scales)),
        "scale_max": float(np.max(scales)),
        "segment_count": int(len(alignments)),
        "segments": alignments,
    }


def detect_associated_discontinuities(
    stamps: np.ndarray,
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    step_threshold_m: float,
    time_gap_threshold_s: float,
    forced_segment_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    """断点/重置诊断。

    根据 GT 步长、estimate 步长、时间间隔判断是否存在大跳变。
    如果传入 forced_segment_ids，则相邻样本的分段 id 变化也会被当作断点，
    这用于 sf_vo reset_count 切段后的强制分段评估。
    默认评估策略不会丢弃这些点，只把信息放入 report["discontinuities"] 供诊断。

    断点来源：
    - gt_step: GT 自己相邻点跳得很远，可能是 GT 数据中断或坐标跳变。
    - est_step: estimate 相邻点跳得很远，可能是 VO/VLOC 重置、丢跟踪后重新初始化或坐标系切换。
    - evaluation_segment_id: sf_vo 的 reset_count 过滤后，不同 reset 段边界会被强制标成断点。
    - time_gap: 相邻评估时间差很大，可能是日志中断或算法停顿。

    指标/页面影响：
    - break_count > 0 会触发“检测到 reset/gap/大跳变”提示。
    - segment_ids 会写入 per_pose，让可视化在断点处断开，不错误连线。

    来源对应：
    - 这是工程扩展，5 篇论文没有把“reset 断点”定义成标准数值指标。
    - 目的在于保护 Geiger12/KITTI 风格的子轨迹统计，避免跨重定位/重置段计算相对误差。
    """
    n = len(stamps)
    if n == 0:
        return {"segment_count": 0, "break_count": 0, "breaks": [], "segments": [], "segment_ids": np.asarray([], dtype=int)}
    if n == 1:
        return {"segment_count": 1, "break_count": 0, "breaks": [], "segments": [{"start": 0, "end": 1, "count": 1}], "segment_ids": np.zeros(1, dtype=int)}

    gt_steps = np.linalg.norm(np.diff(gt_pos, axis=0), axis=1)
    est_steps = np.linalg.norm(np.diff(est_pos, axis=0), axis=1)
    time_gaps = np.diff(stamps)
    forced_ids = np.asarray(forced_segment_ids).reshape(-1) if forced_segment_ids is not None else None
    if forced_ids is not None and len(forced_ids) != n:
        forced_ids = None
    break_after = np.zeros(n - 1, dtype=bool)
    breaks: list[dict[str, Any]] = []
    for idx, (gt_step, est_step, time_gap) in enumerate(zip(gt_steps, est_steps, time_gaps)):
        reasons: list[str] = []
        if forced_ids is not None and forced_ids[idx] != forced_ids[idx + 1]:
            reasons.append("evaluation_segment_id")
        if step_threshold_m > 0 and gt_step > step_threshold_m:
            reasons.append("gt_step")
        if step_threshold_m > 0 and est_step > step_threshold_m:
            reasons.append("est_step")
        if time_gap_threshold_s > 0 and time_gap > time_gap_threshold_s:
            reasons.append("time_gap")
        if reasons:
            # break_after[idx] 表示 idx 和 idx+1 之间存在断点。
            break_after[idx] = True
            breaks.append(
                {
                    "after_index": int(idx),
                    "before_time_s": float(stamps[idx]),
                    "after_time_s": float(stamps[idx + 1]),
                    "time_gap_s": float(time_gap),
                    "gt_step_m": float(gt_step),
                    "est_step_m": float(est_step),
                    "reasons": reasons,
                }
            )

    segments = segments_from_breaks(n, break_after)
    segment_ids = np.zeros(n, dtype=int)
    for seg_id, seg in enumerate(segments):
        segment_ids[seg["start"] : seg["end"]] = seg_id

    return {
        "step_threshold_m": float(step_threshold_m),
        "time_gap_threshold_s": float(time_gap_threshold_s),
        "break_count": int(len(breaks)),
        "segment_count": int(len(segments)),
        "breaks": breaks,
        "segments": segments,
        "segment_ids": segment_ids,
    }


def select_evaluation_segments(segments: list[dict[str, int]], policy: str, total_count: int) -> list[dict[str, int]]:
    """根据断点策略选择实际参与误差计算的连续段。

    固定策略：
    - vo_timestamps: VLOC 使用，保留所有 estimate 时间戳统一评估，断点只作为诊断提示。
    - segments: 按检测出的连续段逐段评估，每段单独对齐，适合 sf_vo reset 后局部坐标系变化的情况。

    指标影响：
    - 这里决定 used_gt_idx/used_est_idx，进而影响 ATE、RPE、尺度图和 summary coverage。
    - dropped_matches 会告诉用户断点策略丢掉了多少匹配点。

    来源对应：
    - vo_timestamps/segments 是工程策略，不是论文标准公式。
    - 这些策略用于在 Schubert18/Delmerico18 关注的长序列、可能丢跟踪场景里解释指标。
    """
    valid_segments = [seg for seg in segments if int(seg.get("count", 0)) >= 2]
    if policy == VLOC_SEGMENT_POLICY:
        return [{"start": 0, "end": int(total_count), "count": int(total_count)}] if total_count >= 2 else []
    if policy == VO_SEGMENT_POLICY:
        return valid_segments
    raise ValueError(f"Unknown fixed segment policy: {policy}")


def segments_from_breaks(n: int, break_after: np.ndarray) -> list[dict[str, int]]:
    """把断点布尔数组转换成连续段列表。"""
    starts = [0]
    ends: list[int] = []
    for idx, is_break in enumerate(break_after):
        if is_break:
            ends.append(idx + 1)
            starts.append(idx + 1)
    ends.append(n)
    return [{"start": int(start), "end": int(end), "count": int(end - start)} for start, end in zip(starts, ends) if end > start]


def relative_error(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    i: int,
    j: int,
) -> tuple[float, float | None]:
    """相对运动误差，RPE 和子轨迹误差共用这一段逻辑。

    有姿态时在各自起点坐标系下比较相对位移/相对旋转；
    无姿态时只比较世界系位移差。

    指标对应：
    - RPE: i 和 j 通常是固定帧间隔。
    - 子轨迹误差: i 和 j 通常相隔固定路程 L。

    为什么有姿态时要转到起点坐标系：
    - RPE/子轨迹关心的是“这段相对运动估得准不准”，不希望被世界系整体旋转影响。
    - 这也和 TUM/RPG/KITTI 常见相对误差定义一致。

    来源对应：
    - 固定帧 i->j 的相对误差来自 Sturm12 RPE。
    - 固定距离 i->j 的相对误差来自 Geiger12/KITTI odometry。
    - Zhang18 给出了统一的相对轨迹误差解释。
    """
    if gt_rot is not None and est_rot is not None:
        gt_r, gt_t = relative_pose(gt_rot[i], gt_pos[i], gt_rot[j], gt_pos[j])
        est_r, est_t = relative_pose(est_rot[i], est_pos[i], est_rot[j], est_pos[j])
        err_r = gt_r.T @ est_r
        err_t = gt_r.T @ (est_t - gt_t)
        return float(np.linalg.norm(err_t)), float(rotation_angle(err_r))
    gt_delta = gt_pos[j] - gt_pos[i]
    est_delta = est_pos[j] - est_pos[i]
    return float(np.linalg.norm(est_delta - gt_delta)), None
    # gt_dist = float(np.linalg.norm(gt_pos[j] - gt_pos[i]))
    # est_dist = float(np.linalg.norm(est_pos[j] - est_pos[i]))
    # return abs(est_dist - gt_dist), None


def relative_pose(r_i: np.ndarray, p_i: np.ndarray, r_j: np.ndarray, p_j: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """计算从第 i 帧到第 j 帧的相对位姿。

    r_rel = R_i^T R_j，p_rel = R_i^T (p_j - p_i)。
    这个局部坐标系表达会被 relative_error() 用来比较 GT 和 estimate 的相对运动。
    """
    r_rel = r_i.T @ r_j
    p_rel = r_i.T @ (p_j - p_i)
    return r_rel, p_rel


def path_distance(positions: np.ndarray) -> np.ndarray:
    """累计路程 D_i。

    用于 summary.gt_path_length_m、误差随路程图、子轨迹长度搜索和发散阈值。

    来源对应：
    - Geiger12/KITTI 子轨迹评估依赖沿 GT 轨迹的累计路程来确定固定长度片段。
    - 本系统也把这个累计路程用于无人机长航程误差曲线和发散阈值。
    """
    positions = np.asarray(positions, dtype=float)
    if len(positions) == 0:
        return np.asarray([], dtype=float)
    if len(positions) == 1:
        return np.asarray([0.0], dtype=float)
    steps = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(steps)])


def describe(values: Any) -> dict[str, float | int] | None:
    """统一统计描述函数。

    所有 RMSE/mean/median/std/min/max/p95/p99 都从这里产生，
    因此 ATE、RPE、子轨迹、速度分箱、runtime 的统计口径一致。

    来源对应：
    - RMSE 是 Sturm12/TUM 和 Zhang18 轨迹误差报告中最常用的汇总方式。
    - mean/median/std/min/max/p95/p99 是报告可读性扩展，用于定位尾部风险和最坏情况。
    """
    if values is None:
        return None
    arr = np.asarray(values, dtype=float).reshape(-1)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return None
    return {
        "count": int(len(arr)),
        "rmse": float(np.sqrt(np.mean(arr * arr))),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
    }


def rotation_errors(gt_rot: np.ndarray, est_rot: np.ndarray) -> np.ndarray:
    """逐帧姿态角误差，单位为弧度。

    输出会在 evaluate_trajectories() 中转成角度，进入 ate_orientation_deg。
    """
    err = np.einsum("nij,nkj->nik", gt_rot, est_rot)
    return np.asarray([rotation_angle(r) for r in err], dtype=float)


def rotation_angle(rot: np.ndarray) -> float:
    """旋转矩阵对应的最小旋转角。

    trace 公式：theta = acos((trace(R)-1)/2)。clip 用于抵抗浮点误差。
    """
    value = (float(np.trace(rot)) - 1.0) / 2.0
    return math.acos(float(np.clip(value, -1.0, 1.0)))


def yaw_from_rot(rotations: np.ndarray) -> np.ndarray:
    """从旋转矩阵提取 ZYX 约定下的 yaw，用于 ate_yaw_deg。"""
    return np.arctan2(rotations[:, 1, 0], rotations[:, 0, 0])


def euler_yaw_pitch_roll_from_matrix(rotations: np.ndarray) -> np.ndarray:
    """从旋转矩阵提取 ZYX yaw/pitch/roll，输出弧度。

    这和 euler_yaw_pitch_roll_to_matrix() 使用同一约定：
    R = Rz(yaw) * Ry(pitch) * Rx(roll)。
    输出列顺序固定为 yaw, pitch, roll，用于 per_pose 里的 6 张姿态时间序列图和 3 张姿态误差图。
    """
    rot = np.asarray(rotations, dtype=float)
    yaw = np.arctan2(rot[:, 1, 0], rot[:, 0, 0])
    pitch = np.arcsin(np.clip(-rot[:, 2, 0], -1.0, 1.0))
    roll = np.arctan2(rot[:, 2, 1], rot[:, 2, 2])
    return np.column_stack([yaw, pitch, roll])


def wrap_pi(values: np.ndarray) -> np.ndarray:
    """把角度差包到 [-pi, pi)，避免 359 度和 1 度被看成差 358 度。"""
    return (values + np.pi) % (2.0 * np.pi) - np.pi


def quaternion_to_matrix(qx: np.ndarray, qy: np.ndarray, qz: np.ndarray, qw: np.ndarray) -> np.ndarray:
    """四元数转旋转矩阵。

    TUM/EuRoC 等数据常用 qx qy qz qw。这里先归一化，避免数值误差导致旋转矩阵不正交。
    """
    q = np.column_stack([qx, qy, qz, qw]).astype(float)
    norms = np.linalg.norm(q, axis=1)
    valid = norms > 0
    q[valid] /= norms[valid, None]
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    n = len(q)
    rot = np.empty((n, 3, 3), dtype=float)
    rot[:, 0, 0] = 1 - 2 * (y * y + z * z)
    rot[:, 0, 1] = 2 * (x * y - z * w)
    rot[:, 0, 2] = 2 * (x * z + y * w)
    rot[:, 1, 0] = 2 * (x * y + z * w)
    rot[:, 1, 1] = 1 - 2 * (x * x + z * z)
    rot[:, 1, 2] = 2 * (y * z - x * w)
    rot[:, 2, 0] = 2 * (x * z - y * w)
    rot[:, 2, 1] = 2 * (y * z + x * w)
    rot[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return rot


def euler_yaw_pitch_roll_to_matrix(yaw: np.ndarray, pitch: np.ndarray, roll: np.ndarray) -> np.ndarray:
    """yaw-pitch-roll 欧拉角转旋转矩阵，使用 ZYX 顺序。

    代码意义：
    - 当前 SF 固定格式的 imu.txt、vloc.txt、vo.txt 都给 yaw/pitch/roll，而不是四元数。
    - 调用方必须先把输入角度统一成弧度；固定格式 parser 会在进入这里之前完成这一步。

    注意：
    - 这里默认列语义是 yaw, pitch, roll。
    - 如果外部数据实际是 roll/pitch/yaw 或坐标系相反，需要用姿态修正选项或调整输入约定。
    """
    yaw = np.asarray(yaw, dtype=float)
    pitch = np.asarray(pitch, dtype=float)
    roll = np.asarray(roll, dtype=float)

    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)

    rot = np.empty((len(yaw), 3, 3), dtype=float)
    rot[:, 0, 0] = cy * cp
    rot[:, 0, 1] = cy * sp * sr - sy * cr
    rot[:, 0, 2] = cy * sp * cr + sy * sr
    rot[:, 1, 0] = sy * cp
    rot[:, 1, 1] = sy * sp * sr + cy * cr
    rot[:, 1, 2] = sy * sp * cr - cy * sr
    rot[:, 2, 0] = -sp
    rot[:, 2, 1] = cp * sr
    rot[:, 2, 2] = cp * cr
    return rot


def matrix_to_quaternion(rot: np.ndarray) -> np.ndarray:
    """旋转矩阵转四元数。

    主要用于姿态插值：先把矩阵转四元数，再在插值流程里做 SLERP。
    """
    out = []
    for r in rot:
        tr = float(np.trace(r))
        if tr > 0:
            s = math.sqrt(tr + 1.0) * 2
            qw = 0.25 * s
            qx = (r[2, 1] - r[1, 2]) / s
            qy = (r[0, 2] - r[2, 0]) / s
            qz = (r[1, 0] - r[0, 1]) / s
        else:
            idx = int(np.argmax(np.diag(r)))
            if idx == 0:
                s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
                qw = (r[2, 1] - r[1, 2]) / s
                qx = 0.25 * s
                qy = (r[0, 1] + r[1, 0]) / s
                qz = (r[0, 2] + r[2, 0]) / s
            elif idx == 1:
                s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
                qw = (r[0, 2] - r[2, 0]) / s
                qx = (r[0, 1] + r[1, 0]) / s
                qy = 0.25 * s
                qz = (r[1, 2] + r[2, 1]) / s
            else:
                s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
                qw = (r[1, 0] - r[0, 1]) / s
                qx = (r[0, 2] + r[2, 0]) / s
                qy = (r[1, 2] + r[2, 1]) / s
                qz = 0.25 * s
        out.append([qx, qy, qz, qw])
    return np.asarray(out, dtype=float)


def tum_dataframe_from_arrays(
    stamps: np.ndarray,
    positions: np.ndarray,
    rotations: np.ndarray | None,
    extra: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """把轨迹数组转成 TUM 表格，前 8 列固定为 timestamp tx ty tz qx qy qz qw。

    这个函数只负责导出格式，不参与 ATE/RPE 计算：
    - 有姿态时把旋转矩阵转成 TUM 四元数 qx qy qz qw。
    - 没有姿态时写单位四元数，并额外标记 has_rotation=False，保证 sheet 仍是 TUM 结构。
    - extra 列统一追加在 TUM 8 列之后，用于保存 segment_id、source_index、jump 文件名等诊断信息。
    """
    stamps = np.asarray(stamps, dtype=float)
    positions = np.asarray(positions, dtype=float)
    count = len(positions)
    if count == 0:
        quats = np.empty((0, 4), dtype=float)
        has_rotation = np.asarray([], dtype=bool)
    elif rotations is not None:
        quats = matrix_to_quaternion(np.asarray(rotations, dtype=float))
        has_rotation = np.ones(count, dtype=bool)
    else:
        quats = np.zeros((count, 4), dtype=float)
        quats[:, 3] = 1.0
        has_rotation = np.zeros(count, dtype=bool)

    frame = pd.DataFrame(
        {
            "timestamp": stamps,
            "tx": positions[:, 0] if count else np.asarray([], dtype=float),
            "ty": positions[:, 1] if count else np.asarray([], dtype=float),
            "tz": positions[:, 2] if count else np.asarray([], dtype=float),
            "qx": quats[:, 0] if count else np.asarray([], dtype=float),
            "qy": quats[:, 1] if count else np.asarray([], dtype=float),
            "qz": quats[:, 2] if count else np.asarray([], dtype=float),
            "qw": quats[:, 3] if count else np.asarray([], dtype=float),
            "has_rotation": has_rotation,
        }
    )
    if extra:
        for key, value in extra.items():
            arr = np.asarray(value)
            if arr.ndim == 0:
                frame[key] = arr.item()
            elif len(arr) == count:
                frame[key] = arr
    return frame


def trajectory_to_tum_dataframe(traj: Trajectory, extra: dict[str, Any] | None = None) -> pd.DataFrame:
    """把 Trajectory 转成 TUM 表格。

    原始输入、插值后 GT、筛选后 estimate 和 Sim3 输出都通过这个函数统一导出，
    避免不同 sheet 的列顺序或四元数顺序不一致。
    """
    return tum_dataframe_from_arrays(traj.stamps, traj.positions, traj.rotations, extra=extra)


def raw_numeric_table(traj: Trajectory) -> np.ndarray | None:
    """取解析阶段保留的原始数字表，用于导出时复查原始 estimate 列。"""
    table = traj.extras.get("raw_numeric_table")
    if table is None:
        return None
    arr = np.asarray(table, dtype=float)
    if arr.ndim != 2 or len(arr) != len(traj.positions):
        return None
    return arr


def jump_export_columns_from_source(
    source: Trajectory,
    source_indices: np.ndarray | None,
    prefix: str,
) -> dict[str, Any]:
    """根据原始 estimate 倒数第四列的 +1 变化生成导出分段列。

    历史需求：如果 estimate 输出文件倒数第四列出现 0->1、1->2 这类 +1 跳变，
    就把跳变后的数据视为新的 TUM 文件，例如 vo_tum_01、vo_tum_02。
    当前固定 sf_vo 中倒数第四列正好是 reset_count；sf_vloc 也会保留该诊断列，
    但主评估的 VLOC/VO 分段逻辑仍以各自固定流程为准，不依赖这里额外切 sheet。

    Excel 当前是 9 个固定 sheet，因此这里不额外创建无限多个 sheet，而是在相关 sheet 中写入：
    - tum_file: 逻辑文件名，如 vo_tum_01；这里的 vo_tum 是历史命名，实际代表 estimate_tum。
    - jump_segment_id: 从 0 开始的分段编号。
    - jump_source_value: 原始倒数第四列的值，方便复查跳变点。
    """
    n = len(source.positions)
    if source_indices is None:
        indices = np.arange(n, dtype=int)
    else:
        indices = np.asarray(source_indices, dtype=int)

    table = raw_numeric_table(source)
    all_segment_ids = np.zeros(n, dtype=int)
    all_values = np.full(n, math.nan, dtype=float)
    source_column_index = -4
    if table is not None and table.shape[1] >= 4:
        source_column_index = int(table.shape[1] - 4)
        all_values = table[:, source_column_index]
        diffs = np.diff(all_values)
        jumps = np.isfinite(diffs) & np.isclose(diffs, 1.0, rtol=0.0, atol=1e-9)
        all_segment_ids = np.concatenate([[0], np.cumsum(jumps)]).astype(int)

    safe_indices = np.clip(indices, 0, max(0, n - 1)) if n else indices
    segment_ids = all_segment_ids[safe_indices] if n else np.asarray([], dtype=int)
    values = all_values[safe_indices] if n else np.asarray([], dtype=float)
    return {
        "source_index": indices,
        "jump_segment_id": segment_ids,
        "jump_source_column_from_end": np.full(len(indices), -4, dtype=int),
        "jump_source_column_index": np.full(len(indices), source_column_index, dtype=int),
        "jump_source_value": values,
        "tum_file": np.asarray([f"{prefix}_{seg_id + 1:02d}" for seg_id in segment_ids], dtype=object),
    }


def interpolated_gt_extra_columns(gt_eval: Trajectory) -> dict[str, Any]:
    """整理 GT 插值 sheet 的诊断列，保留左右 GT 样本和 alpha。"""
    n = len(gt_eval.positions)
    extra: dict[str, Any] = {"row_index": np.arange(n, dtype=int)}
    for key in ["original_est_stamp", "target_stamp", "gt_left_index", "gt_right_index", "interp_alpha", "gt_bracket_gap_s"]:
        value = gt_eval.extras.get(key)
        if value is not None and len(value) == n:
            extra[key] = value
    return extra


def ate_frame_dataframe(per_pose: pd.DataFrame) -> pd.DataFrame:
    """生成每个时间戳一行的 ATE 明细 sheet。

    ATE 不是只在最后算一个总 RMSE。evaluate_trajectories() 已经在 per_pose 里保存了
    每一帧的对齐后位置误差，这里只把这些逐帧误差换成更适合导出阅读的列名：
    - ate_position_m: 三维位置绝对轨迹误差，等于 per_pose.error_m。
    - ate_horizontal_m: XY 平面绝对误差，等于 per_pose.horizontal_error_m。
    - ate_vertical_signed_m: Z 方向带符号误差，正负能看出高度偏高还是偏低。
    - ate_vertical_abs_m: Z 方向绝对误差，适合做 RMSE/阈值判断。

    如果输入包含姿态，还会追加姿态/yaw 的逐帧绝对误差。
    """
    if per_pose.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "segment_id",
                "distance_m",
                "segment_distance_m",
                "ate_position_m",
                "ate_horizontal_m",
                "ate_vertical_signed_m",
                "ate_vertical_abs_m",
            ]
        )

    data: dict[str, Any] = {
        "timestamp": per_pose["timestamp"].to_numpy(),
        "segment_id": per_pose["segment_id"].to_numpy(),
        "distance_m": per_pose["distance_m"].to_numpy() if "distance_m" in per_pose else np.full(len(per_pose), math.nan),
        "segment_distance_m": per_pose["segment_distance_m"].to_numpy() if "segment_distance_m" in per_pose else np.full(len(per_pose), math.nan),
        "ate_position_m": per_pose["error_m"].to_numpy(),
        "ate_horizontal_m": per_pose["horizontal_error_m"].to_numpy(),
        "ate_vertical_signed_m": per_pose["vertical_error_signed_m"].to_numpy(),
        "ate_vertical_abs_m": per_pose["vertical_error_abs_m"].to_numpy(),
    }
    if "orientation_error_deg" in per_pose:
        data["ate_orientation_deg"] = per_pose["orientation_error_deg"].to_numpy()
    if "yaw_error_signed_deg" in per_pose:
        data["ate_yaw_signed_deg"] = per_pose["yaw_error_signed_deg"].to_numpy()
    if "yaw_error_abs_deg" in per_pose:
        data["ate_yaw_abs_deg"] = per_pose["yaw_error_abs_deg"].to_numpy()
    return pd.DataFrame(data)


def normalize_rpe_delta_config(cfg: EvaluationConfig) -> dict[str, Any]:
    """把 RPE 的 UI/API 配置统一成 report 可读字段。

    rpe_delta_unit 只支持 frames 和 meters 两类：
    - frames: 终点固定为 j=i+N。
    - meters: 终点从 GT 累计路程的 target*(1±tolerance) 范围内选择。

    rpe_delta_value 是新参数；如果为空则退回旧的 rpe_delta_frames，保证旧配置还能复现。
    """
    unit_raw = str(cfg.rpe_delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        value = cfg.rpe_delta_value if cfg.rpe_delta_value is not None else cfg.rpe_delta_frames
        frames = max(1, int(round(float(value))))
        return {
            "delta_unit": "frames",
            "delta_value": float(frames),
            "delta_frames": int(frames),
            "delta_distance_m": None,
            "distance_tolerance_ratio": None,
            "distance_tolerance_percent": None,
        }
    if unit_raw == "meters":
        value = cfg.rpe_delta_value if cfg.rpe_delta_value is not None else cfg.rpe_delta_frames
        distance_m = float(value)
        if distance_m <= 0:
            raise ValueError("RPE distance delta must be positive")
        tolerance_ratio = max(0.0, float(cfg.rpe_distance_tolerance_ratio))
        return {
            "delta_unit": "meters",
            "delta_value": distance_m,
            "delta_frames": None,
            "delta_distance_m": distance_m,
            "distance_tolerance_ratio": tolerance_ratio,
            "distance_tolerance_percent": 100.0 * tolerance_ratio,
        }
    raise ValueError(f"Unknown rpe_delta_unit: {cfg.rpe_delta_unit}")


def normalize_scale_delta_config(cfg: EvaluationConfig) -> dict[str, Any]:
    """把尺度图的窗口配置统一成 report 可读字段。

    这个配置独立于 RPE，但单位和语义保持一致：
    - frames: 从每个起点 i 往后取固定帧数 j=i+N。
    - meters: 从每个起点 i 往后找 GT 路程 target*(1±tolerance) 内的候选终点。

    meters 模式和 RPE 的差别在于：尺度图选 GT 距离最接近目标距离的候选，
    不按误差最小选择，避免把尺度问题人为挑好。
    """
    unit_raw = str(cfg.scale_delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        value = cfg.scale_delta_value if cfg.scale_delta_value is not None else cfg.rpe_delta_frames
        frames = max(1, int(round(float(value))))
        return {
            "delta_unit": "frames",
            "delta_value": float(frames),
            "delta_frames": int(frames),
            "delta_distance_m": None,
            "distance_tolerance_ratio": None,
            "distance_tolerance_percent": None,
        }
    if unit_raw == "meters":
        value = cfg.scale_delta_value if cfg.scale_delta_value is not None else cfg.rpe_delta_frames
        distance_m = float(value)
        if distance_m <= 0:
            raise ValueError("Scale distance delta must be positive")
        tolerance_ratio = max(0.0, float(cfg.scale_distance_tolerance_ratio))
        return {
            "delta_unit": "meters",
            "delta_value": distance_m,
            "delta_frames": None,
            "delta_distance_m": distance_m,
            "distance_tolerance_ratio": tolerance_ratio,
            "distance_tolerance_percent": 100.0 * tolerance_ratio,
        }
    raise ValueError(f"Unknown scale_delta_unit: {cfg.scale_delta_unit}")


def rpe_frame_dataframe(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    stamps: np.ndarray,
    *,
    segment_id: int,
    match_indices: np.ndarray,
    delta: int,
    delta_value: float | None = None,
    delta_unit: str = "frames",
    distance_tolerance_ratio: float = 0.05,
) -> pd.DataFrame:
    """生成每个时间戳一行的 RPE 明细 sheet。

    RPE 比较的是从当前帧 i 到未来终点帧 j 的相对运动：
    - frames 模式：j=i+delta。
    - meters 模式：用 GT 累计路程找 target*(1±tolerance) 范围内的候选 j，
      逐个计算 RPE 并选 rpe_translation_m 最小的候选。
    - rpe_translation_m: 这段相对位移的误差。
    - rpe_rotation_deg: 这段相对旋转的误差；没有姿态输入时为 NaN。
    - rpe_available: 当前时间戳是否有足够的未来帧可计算 RPE。

    不能找到合法终点时，保留时间戳但 rpe_available=False。
    这样 Excel 里仍然能做到“每个时间戳都有一行”，不会因为 RPE 少几行而和 ATE 对不上。
    """
    stamps = np.asarray(stamps, dtype=float)
    match_indices = np.asarray(match_indices, dtype=int)
    n = len(stamps)
    unit_raw = str(delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        unit = "frames"
    elif unit_raw == "meters":
        unit = "meters"
    else:
        raise ValueError(f"Unknown rpe_delta_unit: {delta_unit}")
    delta_frames = max(1, int(round(float(delta_value)))) if unit == "frames" and delta_value is not None else max(1, int(delta))
    target_distance_m = float(delta_value) if unit == "meters" and delta_value is not None else float(delta)
    if unit == "meters" and target_distance_m <= 0:
        raise ValueError("RPE distance delta must be positive")
    tolerance_ratio = max(0.0, float(distance_tolerance_ratio))
    min_distance_m = target_distance_m * (1.0 - tolerance_ratio) if unit == "meters" else math.nan
    max_distance_m = target_distance_m * (1.0 + tolerance_ratio) if unit == "meters" else math.nan
    gt_distance = path_distance(gt_pos)

    rpe_translation = np.full(n, math.nan, dtype=float)
    rpe_rotation = np.full(n, math.nan, dtype=float)
    end_timestamp = np.full(n, math.nan, dtype=float)
    end_match_index = np.full(n, -1, dtype=int)
    time_delta = np.full(n, math.nan, dtype=float)
    actual_distance = np.full(n, math.nan, dtype=float)
    distance_error = np.full(n, math.nan, dtype=float)
    candidate_count = np.zeros(n, dtype=int)
    available = np.zeros(n, dtype=bool)

    # evo 的 filter_pairs_by_path(all_pairs=False) 口径：
    # 按累计路程每走过 delta 就记录一个起点 ids[k]，pair 是 (ids[k], ids[k+1])，
    # 这样每段路程至少为 delta，且不重叠。仅在 meters 模式下启用。
    # evo 使用 reference 轨迹（Sim3 对齐后的 est）计算累计路程，这里对齐 evo。
    evo_ids: list[int] = []
    if unit == "meters":
        evo_path = 0.0
        for k in range(1, n):
            evo_path += float(np.linalg.norm(est_pos[k] - est_pos[k - 1]))
            if evo_path >= target_distance_m:
                evo_ids.append(k)
                evo_path = 0.0

    for i in range(n):
        if unit == "frames":
            # candidates = [i + delta_frames] if i + delta_frames < n else []
            # evo 的 filter_pairs_by_index(all_pairs=False) 口径：
            # 起点为 delta 的整数倍，终点 = 起点 + delta，非重叠覆盖。
            if i % delta_frames == 0 and i + delta_frames < n:
                candidates = [i + delta_frames]
            else:
                candidates = []
            
        else:
            # evo 的 filter_pairs_by_path(all_pairs=False) 口径：
            # 只有 i 出现在 evo_ids 里时才计算 RPE，候选终点固定为 evo_ids 的下一个。
            if i in evo_ids:
                idx_in_evo = evo_ids.index(i)
                if idx_in_evo + 1 < len(evo_ids):
                    candidates = [evo_ids[idx_in_evo + 1]]
                else:
                    candidates = []
            else:
                candidates = []
            # 旧口径（tolerance 窗口内选最小误差候选），保留参考：
            # start_distance = gt_distance[i]
            # left = int(np.searchsorted(gt_distance, start_distance + min_distance_m, side="left"))
            # right = int(np.searchsorted(gt_distance, start_distance + max_distance_m, side="right"))
            # candidates = [idx for idx in range(max(i + 1, left), min(right, n))]
        candidate_count[i] = len(candidates)
        if not candidates:
            continue
        best: tuple[float, float, int, float | None] | None = None
        for j in candidates:
            trans_error, rot_error = relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j)
            cur_distance = float(gt_distance[j] - gt_distance[i])
            cur_distance_error = abs(cur_distance - target_distance_m) if unit == "meters" else math.nan
            key = (float(trans_error), cur_distance_error if math.isfinite(cur_distance_error) else 0.0, int(j))
            if best is None or key < (best[0], best[1], best[2]):
                best = (float(trans_error), cur_distance_error, int(j), rot_error)
        if best is None:
            continue
        trans_error, cur_distance_error, j, rot_error = best
        rpe_translation[i] = trans_error
        if rot_error is not None:
            rpe_rotation[i] = math.degrees(rot_error)
        end_timestamp[i] = stamps[j]
        end_match_index[i] = int(match_indices[j]) if j < len(match_indices) else -1
        time_delta[i] = stamps[j] - stamps[i]
        actual_distance[i] = float(gt_distance[j] - gt_distance[i])
        distance_error[i] = cur_distance_error
        available[i] = True

    return pd.DataFrame(
        {
            "timestamp": stamps,
            "segment_id": np.full(n, int(segment_id), dtype=int),
            "match_index": match_indices if len(match_indices) == n else np.arange(n, dtype=int),
            "rpe_delta_unit": np.asarray([unit] * n, dtype=object),
            "rpe_delta_value": np.full(n, float(delta_frames if unit == "frames" else target_distance_m), dtype=float),
            "rpe_delta_frames": np.full(n, delta_frames if unit == "frames" else math.nan, dtype=float),
            "rpe_target_distance_m": np.full(n, target_distance_m if unit == "meters" else math.nan, dtype=float),
            "rpe_distance_tolerance_min_m": np.full(n, min_distance_m, dtype=float),
            "rpe_distance_tolerance_max_m": np.full(n, max_distance_m, dtype=float),
            "rpe_end_match_index": end_match_index,
            "rpe_end_timestamp": end_timestamp,
            "rpe_time_delta_s": time_delta,
            "rpe_actual_distance_m": actual_distance,
            "rpe_distance_error_m": distance_error,
            "rpe_candidate_count": candidate_count,
            "rpe_translation_m": rpe_translation,
            "rpe_rotation_deg": rpe_rotation,
            "rpe_available": available,
        }
    )


def scale_frame_dataframe(
    gt_pos: np.ndarray,
    est_pos_raw: np.ndarray,
    stamps: np.ndarray,
    *,
    segment_id: int,
    match_indices: np.ndarray,
    delta: int,
    delta_value: float | None = None,
    delta_unit: str = "frames",
    distance_tolerance_ratio: float = 0.05,
) -> pd.DataFrame:
    """生成每个起点时间戳对应的局部尺度明细。

    对每个起点 i 选择未来终点 j，计算该窗口内的路程比例：
    - local_scale_ratio_est_over_gt = VO_raw_window_length / GT_window_length。
    - local_sim3_scale = GT_window_length / VO_raw_window_length。
    - local_scale_drift_percent = (local_scale_ratio_est_over_gt - 1) * 100。

    注意这里使用未对齐的 estimate 位置 est_pos_raw。否则 Sim3 对齐后的轨迹已经被整体缩放，
    会掩盖原始 estimate 的局部尺度变化。
    """
    stamps = np.asarray(stamps, dtype=float)
    match_indices = np.asarray(match_indices, dtype=int)
    n = len(stamps)
    unit_raw = str(delta_unit or "frames").strip().lower()
    if unit_raw == "frames":
        unit = "frames"
    elif unit_raw == "meters":
        unit = "meters"
    else:
        raise ValueError(f"Unknown scale_delta_unit: {delta_unit}")
    delta_frames = max(1, int(round(float(delta_value)))) if unit == "frames" and delta_value is not None else max(1, int(delta))
    target_distance_m = float(delta_value) if unit == "meters" and delta_value is not None else float(delta)
    if unit == "meters" and target_distance_m <= 0:
        raise ValueError("Scale distance delta must be positive")
    tolerance_ratio = max(0.0, float(distance_tolerance_ratio))
    min_distance_m = target_distance_m * (1.0 - tolerance_ratio) if unit == "meters" else math.nan
    max_distance_m = target_distance_m * (1.0 + tolerance_ratio) if unit == "meters" else math.nan
    gt_distance = path_distance(gt_pos)
    est_distance = path_distance(est_pos_raw)

    local_scale_ratio = np.full(n, math.nan, dtype=float)
    local_sim3_scale = np.full(n, math.nan, dtype=float)
    local_scale_drift = np.full(n, math.nan, dtype=float)
    end_timestamp = np.full(n, math.nan, dtype=float)
    end_match_index = np.full(n, -1, dtype=int)
    time_delta = np.full(n, math.nan, dtype=float)
    actual_distance = np.full(n, math.nan, dtype=float)
    est_actual_distance = np.full(n, math.nan, dtype=float)
    distance_error = np.full(n, math.nan, dtype=float)
    candidate_count = np.zeros(n, dtype=int)
    available = np.zeros(n, dtype=bool)

    for i in range(n):
        if unit == "frames":
            candidates = [i + delta_frames] if i + delta_frames < n else []
        else:
            start_distance = gt_distance[i]
            left = int(np.searchsorted(gt_distance, start_distance + min_distance_m, side="left"))
            right = int(np.searchsorted(gt_distance, start_distance + max_distance_m, side="right"))
            candidates = [idx for idx in range(max(i + 1, left), min(right, n))]
        candidate_count[i] = len(candidates)
        if not candidates:
            continue
        if unit == "meters":
            j = min(candidates, key=lambda idx: (abs(float(gt_distance[idx] - gt_distance[i]) - target_distance_m), idx))
        else:
            j = candidates[0]
        gt_len = float(gt_distance[j] - gt_distance[i])
        est_len = float(est_distance[j] - est_distance[i])
        if gt_len <= 0 or est_len <= 0:
            continue
        ratio = est_len / gt_len
        local_scale_ratio[i] = ratio
        local_sim3_scale[i] = gt_len / est_len
        local_scale_drift[i] = (ratio - 1.0) * 100.0
        end_timestamp[i] = stamps[j]
        end_match_index[i] = int(match_indices[j]) if j < len(match_indices) else -1
        time_delta[i] = stamps[j] - stamps[i]
        actual_distance[i] = gt_len
        est_actual_distance[i] = est_len
        distance_error[i] = abs(gt_len - target_distance_m) if unit == "meters" else math.nan
        available[i] = True

    return pd.DataFrame(
        {
            "timestamp": stamps,
            "local_sim3_scale": local_sim3_scale,
            "local_scale_ratio_est_over_gt": local_scale_ratio,
            "local_scale_drift_percent": local_scale_drift,
            "scale_available": available,
            "segment_id": np.full(n, int(segment_id), dtype=int),
            "match_index": match_indices if len(match_indices) == n else np.arange(n, dtype=int),
            "scale_delta_unit": np.asarray([unit] * n, dtype=object),
            "scale_delta_value": np.full(n, float(delta_frames if unit == "frames" else target_distance_m), dtype=float),
            "scale_delta_frames": np.full(n, delta_frames if unit == "frames" else math.nan, dtype=float),
            "scale_target_distance_m": np.full(n, target_distance_m if unit == "meters" else math.nan, dtype=float),
            "scale_distance_tolerance_min_m": np.full(n, min_distance_m, dtype=float),
            "scale_distance_tolerance_max_m": np.full(n, max_distance_m, dtype=float),
            "scale_end_match_index": end_match_index,
            "scale_end_timestamp": end_timestamp,
            "scale_time_delta_s": time_delta,
            "scale_actual_distance_m": actual_distance,
            "scale_est_actual_distance_m": est_actual_distance,
            "scale_distance_error_m": distance_error,
            "scale_candidate_count": candidate_count,
        }
    )


def build_trajectory_export_sheets(
    original_gt: Trajectory,
    original_est: Trajectory,
    gt_eval: Trajectory,
    est_eval: Trajectory,
    sim3_gt_tum: pd.DataFrame,
    sim3_vo_tum: pd.DataFrame,
    ate_per_frame: pd.DataFrame,
    rpe_per_frame: pd.DataFrame,
    scale_per_frame: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """构造 Excel 导出的中间结果 sheet。

    Sheet 设计：
    1. input_gt_tum: 原始 GT 转 TUM。
    2. input_vo_tum: 原始 estimate 转 TUM，并按倒数第四列 +1 跳变标记 vo_tum_XX。
       这里保留 vo_tum 作为历史 sheet 名称；在 VLOC 模式下它代表 vloc estimate。
    3. filtered_vo_tum: 时间同步后保留下来的 estimate。
    4. interpolated_gt_tum: 插值到 estimate 时间戳后的 GT。
    5. sim3_gt_tum: Sim3 评估时使用的 GT，VLOC 入口会移除这张表。
    6. sim3_vo_tum: Sim3 对齐后的 estimate，VLOC 入口会移除这张表。
    7. ate_per_frame: 每个评估时间戳的 ATE 明细。
    8. rpe_per_frame: 每个评估时间戳起算的固定帧/距离 RPE 明细。
    9. scale_per_frame: 每个评估时间戳起算的局部尺度比例/尺度漂移明细。
    """
    raw_gt_extra = {
        "source_index": np.arange(len(original_gt.positions), dtype=int),
        "tum_file": np.asarray(["gt_tum_01"] * len(original_gt.positions), dtype=object),
    }
    raw_vo_extra = jump_export_columns_from_source(original_est, None, "vo_tum")

    est_source_index = est_eval.extras.get("source_index")
    filtered_vo_extra = jump_export_columns_from_source(original_est, est_source_index, "vo_tum")
    filtered_vo_extra["matched_index"] = np.arange(len(est_eval.positions), dtype=int)

    return {
        "input_gt_tum": trajectory_to_tum_dataframe(original_gt, raw_gt_extra),
        "input_vo_tum": trajectory_to_tum_dataframe(original_est, raw_vo_extra),
        "filtered_vo_tum": trajectory_to_tum_dataframe(est_eval, filtered_vo_extra),
        "interpolated_gt_tum": trajectory_to_tum_dataframe(gt_eval, interpolated_gt_extra_columns(gt_eval)),
        "sim3_gt_tum": sim3_gt_tum,
        "sim3_vo_tum": sim3_vo_tum,
        "ate_per_frame": ate_per_frame,
        "rpe_per_frame": rpe_per_frame,
        "scale_per_frame": scale_per_frame,
    }


def report_to_excel(report: dict[str, Any]) -> bytes:
    """把 report 中的轨迹和逐帧误差导出 sheet 写成一个 xlsx 工作簿。"""
    sheets = report.get("trajectory_exports") or {}
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            safe_name = re.sub(r"[\[\]:*?/\\]", "_", str(name))[:31] or "sheet"
            if isinstance(frame, pd.DataFrame):
                frame.to_excel(writer, sheet_name=safe_name, index=False)
            else:
                pd.DataFrame(frame).to_excel(writer, sheet_name=safe_name, index=False)
    return output.getvalue()


def report_to_json(report: dict[str, Any]) -> str:
    """导出严格 JSON 报告，供网页下载和 Pyodide 传回 JavaScript。"""
    return json.dumps(_jsonable_report(report), ensure_ascii=False, indent=2, allow_nan=False)


def _jsonable_report(report: dict[str, Any]) -> dict[str, Any]:
    """report_to_json() 的入口包装，保持调用语义清晰。"""
    return _jsonable_value(report)


def _jsonable_value(value: Any) -> Any:
    """把 report 递归转成标准 JSON 值。

    代码意义：
    - DataFrame -> records list，供 per_pose/rpe_per_frame/scale_per_frame 导出。
    - numpy scalar/array -> Python 原生类型，避免 json.dumps 不认识。
    - NaN/Infinity -> None，浏览器 JSON.parse 会把它读成 null。

    指标对应：
    - 所有 report 字段最终都经过这里，确保 ATE/RPE/segment/runtime 等结果可以稳定导出。
    """
    if isinstance(value, pd.DataFrame):
        return [_jsonable_value(row) for row in value.to_dict(orient="records")]
    if isinstance(value, np.ndarray):
        return _jsonable_value(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable_value(value.item())
    if isinstance(value, dict):
        return {key: _jsonable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _dataclass_to_jsonable(cfg: EvaluationConfig) -> dict[str, Any]:
    """把 EvaluationConfig 展开成普通 dict，写入 report["config"]。

    代码意义：
    - 报告里保留本次评估的所有参数，便于复现实验。
    - 这些配置不是算法结果，但会改变所有指标的解释方式。
    """
    return {
        "rpe_delta_frames": cfg.rpe_delta_frames,
        "rpe_delta_value": cfg.rpe_delta_value,
        "rpe_delta_unit": cfg.rpe_delta_unit,
        "rpe_distance_tolerance_ratio": cfg.rpe_distance_tolerance_ratio,
        "scale_delta_value": cfg.scale_delta_value,
        "scale_delta_unit": cfg.scale_delta_unit,
        "scale_distance_tolerance_ratio": cfg.scale_distance_tolerance_ratio,
    }


def _alignment_dict(mode: str, scale: float, rotation: np.ndarray, translation: np.ndarray) -> dict[str, Any]:
    """统一构造 alignment 字段。

    rotation/translation 保留 ndarray，后续 _jsonable_value() 会在导出时转成 list。
    """
    return {
        "mode": mode,
        "scale": float(scale),
        "rotation": np.asarray(rotation, dtype=float),
        "translation": np.asarray(translation, dtype=float),
    }


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
