"""VO evaluation core.

这份文件负责所有“算法层”的工作，页面只是调用这里的函数。

代码分层：
1. 输入解析：把 TUM/KITTI/CSV/EuRoC/注释表头等轨迹文件读成 Trajectory。
2. 时间同步：默认把 GT 插值到 VO 时间戳；也保留 TUM greedy timestamp association。
3. 轨迹对齐：SE3、Sim3、首帧对齐或不对齐，把 VO 坐标系映射到 GT 坐标系。
4. 指标计算：ATE、RPE、长距离子轨迹误差、尺度漂移、覆盖率、发散、速度分箱、runtime。
5. 报告输出：把指标、每帧误差表、子轨迹表组织成 report dict，供 app.py 展示和导出。

指标与代码字段对应：
- 时间同步质量：prepare_evaluation_trajectories()/associate_trajectories() -> report["association"]。
- 轨迹对齐尺度：compute_alignment()/aggregate_alignment() -> report["alignment"]。
- ATE 三维位置误差：pos_error_m -> report["ate_position_m"]。
- ATE 水平误差：horizontal_error_m -> report["ate_horizontal_m"]。
- ATE 垂直/高度误差：vertical_error_m -> report["ate_vertical_m"]。
- VO 姿态修正：select_orientation_correction()/apply_orientation_correction() -> report["orientation_correction"]。
- 姿态/yaw 误差：rotation_errors()/yaw_from_rot() -> ate_orientation_deg / ate_yaw_deg。
- RPE 帧数/距离间隔误差：rpe_frame_dataframe()/relative_error() -> report["rpe_frame_delta"] 和 rpe_per_frame。
- KITTI/rpg 风格子轨迹误差：segment_errors() -> report["segment_errors"] 和 segment_records。
- 速度分箱误差：summarize_by_speed_bins() -> report["speed_bins"]。
- 终点漂移、覆盖率、路程、耗时、原始尺度比：summary dict。
- 发散检测：detect_divergence() -> report["divergence"]。
- VO 重置/大跳变诊断：detect_associated_discontinuities() -> report["discontinuities"]。
- runtime/资源统计：summarize_runtime() -> report["runtime"]。

论文出处标注：
- [Sturm12] Sturm et al., "A Benchmark for the Evaluation of RGB-D SLAM Systems", IROS 2012。
  直接来源：TUM trajectory 格式、timestamp association 思路、ATE、RPE。
- [Geiger12] Geiger et al., "Are we ready for Autonomous Driving? The KITTI Vision Benchmark Suite", CVPR 2012。
  直接来源：按子轨迹长度统计平移误差百分比、旋转误差 deg/m，以及按速度/长度看误差。
- [Schubert18] Schubert et al., "The TUM VI Benchmark for Evaluating Visual-Inertial Odometry", IROS 2018。
  参考来源：VIO 数据的高频 GT、传感器时间同步、长序列/起止段评估和 VI 姿态评估语境。
- [Delmerico18] Delmerico and Scaramuzza, "A Benchmark Comparison of Monocular Visual-Inertial Odometry Algorithms for Flying Robots", ICRA 2018。
  参考来源：飞行机器人场景下同时关注轨迹精度、低延迟、每帧处理时间、CPU 和内存负载。
- [Zhang18] Zhang and Scaramuzza, "A Tutorial on Quantitative Trajectory Evaluation for Visual(-Inertial) Odometry", IROS 2018。
  直接来源：按传感器可观性选择 SE3/Sim3/首帧等对齐方式，ATE 与相对误差的统一解释。

每个输出指标对应的论文方法：
- report["association"]：Sturm12 的 TUM greedy timestamp association；interpolate_gt 是本系统为“GT 高频、VO 低频或错位”
  增加的工程扩展，动机来自 Schubert18 的高频同步 GT 和 Zhang18 对时间关联问题的强调。
- report["alignment"]：Sturm12 ATE 需要先对齐轨迹；Zhang18 明确按单目/双目/VIO 选择 Sim3、SE3 或其他变换。
- report["ate_position_m"]：Sturm12 的 Absolute Trajectory Error；Zhang18 也把 ATE 作为常用全局误差。
- report["ate_horizontal_m"]：ATE 的 XY 分量拆分，论文中不是独立排行榜指标；为物流无人机横向航线偏差扩展，
  应和 Sturm12/Zhang18 的 ATE 一起理解。
- report["ate_vertical_m"]：ATE 的 Z 分量拆分，论文中不是独立排行榜指标；为无人机高度安全扩展。
- report["ate_orientation_deg"]：Zhang18 的 SE(3) 姿态误差/相对误差思想；Schubert18/TUM VI 的 VIO 评估包含姿态语境。
- report["ate_yaw_deg"]：姿态误差的 yaw 分量拆分，论文中不是独立排行榜指标；为无人机航向控制扩展。
- report["rpe_frame_delta"]：Sturm12 的 Relative Pose Error；frames 模式对应固定帧 RPE，meters 模式是在同一
  relative_error 公式上按 GT 距离窗口选终点的工程扩展；Schubert18/TUM VI 使用固定时间间隔 RPE 评估 VIO；
  Zhang18 将其归入相对误差。
- report["segment_errors"]：Geiger12/KITTI odometry 的固定长度子轨迹平移百分比和旋转 deg/m；
  Zhang18/rpg 轨迹评估也使用相对误差和尺度漂移思想。
- report["speed_bins"]：Geiger12/KITTI 的 error-vs-speed 图表思想；本系统把它泛化到无人机速度分箱。
- report["summary"]["endpoint_error_m"]：工程扩展，论文中不是标准排行榜指标；用于物流无人机终点/降落点偏差分析。
- report["summary"]["gt_coverage_ratio"] 和 report["summary"]["est_coverage_ratio"]：工程扩展，动机来自 Schubert18/Delmerico18
  对长序列 VIO 跟踪成功率、鲁棒性和飞行可用性的关注。
- report["summary"]["raw_path_scale_ratio"]：Zhang18 的尺度可观性和 Sim3/SE3 对齐讨论；用于判断单目 VO 是否无尺度或尺度不稳。
- report["summary"]["duration_s"]、["gt_path_m"]、["est_path_m"]：工程基础量，用于把 Geiger12 的长度/速度误差、
  Delmerico18 的运行时间约束和无人机长航程需求放到同一报告。
- report["divergence"]：工程扩展，论文中没有统一阈值公式；用于把 Schubert18/Delmerico18 的长序列鲁棒性需求落到可报警字段。
- report["discontinuities"]：工程扩展，处理 VO 重定位/重置/丢跟踪后的大跳变，避免跨断点污染 Geiger12 式子轨迹统计。
- report["runtime"]：Delmerico18 直接关注每帧处理时间、CPU 和内存负载；本系统从 VO 输出 extras 字段中统计这些量。
"""

from __future__ import annotations

import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


# 指标代码索引。README 的“指标与 evaluator.py 代码总表”应和这里保持一致。
# 维护规则：只要 report 新增/改名指标，就同步更新本表和 README，避免页面、文档、代码三处口径分叉。
METRIC_CODE_MAP: tuple[dict[str, str], ...] = (
    {
        "metric": "时间同步 / GT 插值到 VO",
        "report_field": 'report["association"]',
        "code": "prepare_evaluation_trajectories(); build_associated_trajectories(); interpolate_reference_to_estimate(); associate_trajectories()",
    },
    {
        "metric": "轨迹对齐 / 对齐尺度",
        "report_field": 'report["alignment"]',
        "code": "compute_alignment(); umeyama_alignment(); aggregate_alignment(); apply_alignment()",
    },
    {
        "metric": "VO 姿态修正",
        "report_field": 'report["orientation_correction"]',
        "code": "select_orientation_correction(); score_orientation_correction_candidate(); apply_orientation_correction()",
    },
    {
        "metric": "ATE 三维位置误差",
        "report_field": 'report["ate_position_m"]; report["ate"]["primary_position_m"]',
        "code": "evaluate_trajectories(): errors/pos_error_m; describe(); build_ate_report()",
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
        "metric": "RPE 固定时间间隔误差",
        "report_field": 'report["rpe_time_delta"]',
        "code": "rpe_error_arrays_by_time(); nearest_time_index(); summarize_time_rpe()",
    },
    {
        "metric": "按距离子轨迹平移 / 旋转 / 尺度误差",
        "report_field": 'report["segment_errors"]',
        "code": "segment_errors(); find_segment_end(); relative_error(); summarize_segment_records()",
    },
    {
        "metric": "每个子轨迹明细",
        "report_field": 'report["segment_records"]',
        "code": "segment_errors(): records; summarize_segment_records()",
    },
    {
        "metric": "速度分箱误差",
        "report_field": 'report["speed_bins"]',
        "code": "summarize_by_speed_bins(); describe_clean()",
    },
    {
        "metric": "最差片段 Top-K",
        "report_field": 'report["worst_segments"]',
        "code": "build_worst_segments()",
    },
    {
        "metric": "断点 / VO 重置 / 大跳变",
        "report_field": 'report["discontinuities"]',
        "code": "detect_associated_discontinuities(); select_evaluation_segments(); summarize_continuity()",
    },
    {
        "metric": "发散检测",
        "report_field": 'report["divergence"]',
        "code": "detect_divergence(); classify_tracking_failure(); classify_scale_divergence()",
    },
    {
        "metric": "航程 / 耗时 / 匹配数量 / 覆盖率 / 终点漂移 / 原始尺度比",
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
    extras: runtime 或资源字段，例如 process_time_ms、fps、memory_mb。
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
        - 时间排序很重要：后续 path_distance()、插值、RPE、子轨迹搜索都默认轨迹按时间递增。
        - extras 会跟随相同排序同步重排，确保 runtime 字段仍然和 VO 位姿一一对应。

        指标影响：
        - 如果这里不排序，summary.duration_s、speed_bins、RPE 和断点检测都会被乱序时间污染。
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


@dataclass
class EvaluationConfig:
    """评估配置，基本都由 app.py/静态网页侧边栏控件传入。

    配置与指标/流程的对应关系：
    - alignment: 决定 compute_alignment() 的 SE3/Sim3/首帧/不对齐方式，影响所有 ATE/RPE/子轨迹误差。
    - orientation_correction: 对 VO 姿态做坐标系/外参修正，或自动选择最优修正，
      对应 report["orientation_correction"]，会影响姿态 ATE、RPE 和带姿态的子轨迹误差。
    - association_mode/max_time_diff_s/max_interpolation_gap_s/time_offset_s/allow_extrapolation:
      决定 prepare_evaluation_trajectories() 如何把 GT 和 VO 放到同一时间轴，影响匹配位姿、覆盖率和所有后续误差。
    - rpe_delta_value/rpe_delta_unit: 控制 RPE 按帧数或按 GT 距离统计，对应 report["rpe_frame_delta"] 和 rpe_per_frame。
      rpe_delta_frames 保留为旧配置兼容字段；rpe_delta_seconds 仍输出固定时间 RPE 参考值。
    - segment_lengths_m/segment_step_frames/max_segments_per_length/max_segment_length_diff_ratio:
      控制 segment_errors() 的长航程子轨迹抽样，对应 report["segment_errors"] 和 report["segment_records"]。
    - continuous_segment_policy/discontinuity_*: 控制断点诊断和跨重置轨迹如何纳入评估，对应 report["discontinuities"]。
    - divergence_*: 控制 detect_divergence() 的发散阈值，对应 report["divergence"]。
    - speed_bins_mps: 控制 summarize_by_speed_bins() 的速度分箱，对应 report["speed_bins"]。
    """

    profile: str = "monocular_long_range_uav"
    alignment: str = "sim3"
    orientation_correction: str = "none"
    association_mode: str = "interpolate_gt"
    max_time_diff_s: float | None = 0.02
    max_interpolation_gap_s: float | None = 0.15
    allow_extrapolation: bool = False
    interpolate_rotation: bool = True
    interpolation_position_method: str = "linear"
    interpolation_rotation_method: str = "slerp"
    time_offset_s: float = 0.0
    rpe_delta_frames: int = 1
    rpe_delta_value: float | None = None
    rpe_delta_unit: str = "frames"
    rpe_distance_tolerance_ratio: float = 0.05
    scale_delta_value: float | None = None
    scale_delta_unit: str = "frames"
    scale_distance_tolerance_ratio: float = 0.05
    rpe_delta_seconds: tuple[float, ...] = (1.0, 5.0, 10.0)
    segment_lengths_m: tuple[float, ...] = (50, 100, 200, 500, 1000, 2000, 5000)
    max_segments_per_length: int = 10000
    segment_step_frames: int = 10
    max_segment_length_diff_ratio: float = 0.05
    continuous_segment_policy: str = "segments"
    discontinuity_step_m: float = 100.0
    discontinuity_time_gap_s: float = 5.0
    divergence_abs_m: float = 30.0
    divergence_rel_percent: float = 3.0
    divergence_min_distance_m: float = 100.0
    divergence_min_time_s: float = 5.0
    speed_bins_mps: tuple[float, ...] = (0, 8, 12, 16, 20, math.inf)
    top_k_worst_segments: int = 10


# 下面这些候选列名用于 CSV/TSV/注释表头自动识别。
# 目的：不要求用户改原始数据列名，只要能识别到所需字段即可。
TIME_COLUMN_CANDIDATES = ["timestamp", "time", "t", "stamp", "sec", "seconds", "ts", "ts1", "frame", "index"]
X_COLUMN_CANDIDATES = [
    "x",
    "tx",
    "px",
    "p_x",
    "p_RS_R_x",
    "p_W_B_x",
    "p_W_C_x",
    "posx",
    "positionx",
    "translationx",
    "utmex",
    "east",
    "easting",
]
Y_COLUMN_CANDIDATES = [
    "y",
    "ty",
    "py",
    "p_y",
    "p_RS_R_y",
    "p_W_B_y",
    "p_W_C_y",
    "posy",
    "positiony",
    "translationy",
    "utmnorth",
    "north",
    "northing",
]
Z_COLUMN_CANDIDATES = [
    "z",
    "tz",
    "pz",
    "p_z",
    "p_RS_R_z",
    "p_W_B_z",
    "p_W_C_z",
    "posz",
    "positionz",
    "translationz",
    "alt",
    "altitude",
    "height",
    "up",
]
QX_COLUMN_CANDIDATES = ["qx", "q_x", "q_RS_x", "q_W_B_x", "q_B_W_x", "quatx", "quaternionx", "orientationx"]
QY_COLUMN_CANDIDATES = ["qy", "q_y", "q_RS_y", "q_W_B_y", "q_B_W_y", "quaty", "quaterniony", "orientationy"]
QZ_COLUMN_CANDIDATES = ["qz", "q_z", "q_RS_z", "q_W_B_z", "q_B_W_z", "quatz", "quaternionz", "orientationz"]
QW_COLUMN_CANDIDATES = ["qw", "q_w", "q_RS_w", "q_W_B_w", "q_B_W_w", "quatw", "quaternionw", "orientationw"]

AUTO_ORIENTATION_CORRECTION_CANDIDATES = (
    "none",
    "inverse",
    "rx180_left",
    "rx180_right",
    "rx180_left_inverse",
    "rx180_right_inverse",
    "ry180_left",
    "ry180_right",
    "ry180_left_inverse",
    "ry180_right_inverse",
    "rz180_left",
    "rz180_right",
    "rz180_left_inverse",
    "rz180_right_inverse",
    "enu_ned_left",
    "enu_ned_right",
    "enu_ned_both",
    "enu_ned_left_inverse",
    "enu_ned_right_inverse",
    "enu_ned_both_inverse",
)


def load_trajectory(source: str | bytes | Path | io.BytesIO, fmt: str = "auto", name: str | None = None) -> Trajectory:
    """从文件、上传对象或纯文本中读取轨迹。

    支持的常见格式：
    - TUM: timestamp tx ty tz qx qy qz qw
    - KITTI odometry: 12 values per row, row-major 3x4 pose matrix
    - CSV/TSV/空格表：time/x/y/z，可选 quaternion、rotation matrix 或 yaw/pitch/roll。

    代码意义：
    - 这里只负责把输入对象变成文本，真正的格式识别在 load_trajectory_from_text()。
    - 保留 name 是为了 report["inputs"] 能告诉用户本次评估到底用了哪个文件。

    指标影响：
    - 读取错误会影响所有指标；因此解析失败时宁愿报错，也不默默生成错误轨迹。
    """
    text, inferred_name = _read_text(source)
    return load_trajectory_from_text(text, fmt=fmt, name=name or inferred_name)


def load_trajectory_from_text(text: str, fmt: str = "auto", name: str = "trajectory") -> Trajectory:
    """把文本轨迹读成 Trajectory。

    这里是输入格式分发层：auto 会先看是否有注释表头，再按列数识别
    SF/VLOC/KITTI/TUM/XYZ/CSV。真正的列解析在 _parse_sf()、_parse_vloc()、_parse_csv() 和 _parse_numeric_table()。

    指标影响：
    - 识别成 KITTI/TUM/CSV 会决定时间戳、姿态和单位如何解析。
    - 如果误把带表头文件当无表头数字表，后续 ATE/RPE 可能完全失真，所以 auto 优先检查注释表头。
    """

    lines = _meaningful_lines(text)
    if not lines:
        raise ValueError(f"{name}: empty trajectory file")

    normalized_fmt = fmt.lower()
    if normalized_fmt == "auto":
        if _comment_header(text):
            normalized_fmt = _detect_commented_format(text)
        else:
            normalized_fmt = _detect_plain_header_format(lines) or _detect_format(lines)

    if normalized_fmt == "sf":
        return _parse_sf(text, name)
    if normalized_fmt == "vloc":
        return _parse_vloc(text, name)
    if normalized_fmt == "csv":
        return _parse_csv(text, name)
    if normalized_fmt == "tum":
        return _parse_numeric_table(lines, name, "tum")
    if normalized_fmt == "kitti":
        return _parse_numeric_table(lines, name, "kitti")
    if normalized_fmt == "xyz":
        return _parse_numeric_table(lines, name, "xyz")
    raise ValueError(f"Unsupported trajectory format: {fmt}")


def evaluate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    """评估入口：输入 GT 和 VO 轨迹，输出完整 report。

    流程对应页面上的“运行结果、可视化、明细与导出”：
    1. 时间同步 -> association / coverage。
    2. 大跳变诊断 -> discontinuities。
    3. 对每个选中连续段做对齐和误差计算。
    4. 汇总 ATE/RPE/子轨迹/速度分箱/runtime/发散等指标。
    5. 返回 report dict，app.py 只负责展示这个 report。

    来源对应：
    - ATE/RPE 主干来自 Sturm12 和 Zhang18。
    - 长度/速度子轨迹误差来自 Geiger12/KITTI。
    - 长序列覆盖率、断点和发散是 Schubert18/Delmerico18 场景下的工程扩展。
    - runtime 统计来自 Delmerico18 对飞行机器人实时性的关注。
    """
    cfg = config or EvaluationConfig()

    # 1. 时间同步：默认以 VO 时间戳为评估基准，把 GT/IMU 插值到 VO 时刻。
    #    这样 GT=0.1/0.3/0.5、VO=0.2/0.4/0.6 的相位错开数据不会被错误丢弃。
    #    如果选择 nearest，则退回 TUM RGB-D benchmark 的 greedy timestamp association。
    original_gt = gt
    original_est = est
    gt, est, gt_idx, est_idx, assoc = prepare_evaluation_trajectories(original_gt, original_est, cfg)
    if len(gt_idx) < 2:
        raise ValueError("Need at least two associated poses to evaluate a trajectory")

    # 2. 先在原始匹配序列上诊断断点/跳变。默认策略 vo_timestamps 不丢点，
    #    断点只用于提示 VO 可能发生了重置或局部坐标系切换。
    original_match_count = int(len(gt_idx))
    original_gt_pos = gt.positions[gt_idx]
    original_est_pos = est.positions[est_idx]
    original_stamps = gt.stamps[gt_idx]
    discontinuities_all = detect_associated_discontinuities(
        original_stamps,
        original_gt_pos,
        original_est_pos,
        step_threshold_m=cfg.discontinuity_step_m,
        time_gap_threshold_s=cfg.discontinuity_time_gap_s,
    )
    eval_ranges = select_evaluation_segments(discontinuities_all["segments"], cfg.continuous_segment_policy, original_match_count)
    if not eval_ranges:
        raise ValueError("No continuous segment contains at least two matched poses")

    # 3. 根据 GT/VO 姿态和评估段选择 VO 姿态修正。auto 会试多个坐标系/外参候选，
    #    手动模式则直接应用用户选定的修正；ignore 会退化成 position-only RPE/子轨迹误差。
    orientation_selection = select_orientation_correction(gt, est, gt_idx, est_idx, eval_ranges, cfg)

    # 这些列表会收集每个连续段的结果，最后统一 concat/describe。
    per_pose_frames: list[pd.DataFrame] = []
    segment_record_frames: list[pd.DataFrame] = []
    pos_error_parts: list[np.ndarray] = []
    horizontal_error_parts: list[np.ndarray] = []
    vertical_error_signed_parts: list[np.ndarray] = []
    vertical_error_abs_parts: list[np.ndarray] = []
    orientation_error_parts: list[np.ndarray] = []
    yaw_error_signed_parts: list[np.ndarray] = []
    yaw_error_abs_parts: list[np.ndarray] = []
    rpe_trans_parts: list[np.ndarray] = []
    rpe_rot_parts: list[np.ndarray] = []
    rpe_time_trans_parts: dict[float, list[np.ndarray]] = {float(delta): [] for delta in cfg.rpe_delta_seconds if float(delta) > 0}
    rpe_time_rot_parts: dict[float, list[np.ndarray]] = {float(delta): [] for delta in cfg.rpe_delta_seconds if float(delta) > 0}
    used_gt_indices: list[np.ndarray] = []
    used_est_indices: list[np.ndarray] = []
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
        # 4. 根据连续段策略切片；默认是一整段 VO 时间戳，segments 模式会分段评估。
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
        est_rot = apply_orientation_correction(est_rot_raw, orientation_selection["selected"]) if est_rot_raw is not None else None
        if orientation_selection["selected"] == "ignore":
            gt_rot = None
            est_rot = None
        stamps = gt.stamps[cur_gt_idx]

        # 5. 对齐 VO 到 GT 坐标系。alignment.scale 是页面“对齐尺度”。
        alignment = compute_alignment(gt_pos, est_pos, gt_rot, est_rot, mode=cfg.alignment)
        alignment["segment_id"] = int(seg_id)
        alignment["start_match_index"] = start
        alignment["end_match_index"] = end
        alignments.append(alignment)

        est_pos_aligned = apply_alignment(est_pos, alignment)
        est_rot_aligned = apply_rotation_alignment(est_rot, alignment) if est_rot is not None else None

        # Excel 导出需要固定给出 Sim3 结果。这里独立计算 Sim3，不受页面当前 alignment 选项影响；
        # 这样即使用户临时选择 SE3/首帧对齐，导出的 sim3_vo_tum 仍然是标准 Sim3 对齐输出。
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
        for delta_s in rpe_time_trans_parts:
            time_trans, time_rot = rpe_error_arrays_by_time(
                gt_pos,
                est_pos_aligned,
                gt_rot,
                est_rot_aligned,
                stamps,
                delta_s=delta_s,
            )
            rpe_time_trans_parts[delta_s].append(time_trans)
            if len(time_rot):
                rpe_time_rot_parts[delta_s].append(np.degrees(time_rot))

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

        # 9. 长航程核心指标：按固定距离 L 抽子轨迹，统计漂移百分比、旋转误差和尺度漂移。
        #    来源：Geiger12/KITTI 的长度子轨迹平移/旋转漂移；尺度漂移解释参考 Zhang18。
        cur_segments = segment_errors(
            gt_pos,
            est_pos_aligned,
            est_pos,
            gt_rot,
            est_rot_aligned,
            stamps,
            lengths_m=cfg.segment_lengths_m,
            max_segments_per_length=cfg.max_segments_per_length,
            step_frames=cfg.segment_step_frames,
            max_length_diff_ratio=cfg.max_segment_length_diff_ratio,
            )
        if not cur_segments["records"].empty:
            rec = cur_segments["records"].copy()
            rec["segment_id"] = int(seg_id)
            rec["global_start_match_index"] = (rec["start_index"] + start).astype(float)
            rec["global_end_match_index"] = (rec["end_index"] + start).astype(float)
            segment_record_frames.append(rec)

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

        # 11. summary 所需的总路程、raw VO 路程、对齐后 VO 路程、耗时等。
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
    segment_records = pd.concat(segment_record_frames, ignore_index=True) if segment_record_frames else pd.DataFrame()
    rpe_per_frame = pd.concat(rpe_frame_export_frames, ignore_index=True) if rpe_frame_export_frames else pd.DataFrame()
    scale_per_frame = pd.concat(scale_frame_export_frames, ignore_index=True) if scale_frame_export_frames else pd.DataFrame()
    # 12. 统计汇总：describe() 会统一给出 count/rmse/mean/median/std/min/max/p95/p99。
    segment_summary = summarize_segment_records(segment_records)
    speed_bins = summarize_by_speed_bins(segment_records, cfg.speed_bins_mps)
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
    # 13. runtime 只统计 VO 输出里存在的资源字段；没有字段则返回 None。
    runtime = summarize_runtime(est, used_est_idx)
    alignment = aggregate_alignment(alignments, cfg.alignment)
    global_sim3_ate = compute_global_ate(gt, est, used_gt_idx, used_est_idx, orientation_selection["selected"], mode="sim3")
    ate_report = build_ate_report(
        pos_error_m,
        global_sim3_ate,
        cfg,
        alignment,
    )
    rpe_delta_info = normalize_rpe_delta_config(cfg)
    rpe = {
        **rpe_delta_info,
        "count": int(len(rpe_trans)),
        "translation_m": describe(rpe_trans),
        "rotation_deg": describe(rpe_rot_deg) if len(rpe_rot_deg) else None,
    }
    rpe_time_delta = summarize_time_rpe(rpe_time_trans_parts, rpe_time_rot_parts)
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
        "policy": cfg.continuous_segment_policy,
        "segments": [{"start_index": int(seg["start"]), "end_index": int(seg["end"]), "count": int(seg["count"])} for seg in eval_ranges],
        "selected_matches": int(len(used_gt_idx)),
        "dropped_matches": int(original_match_count - len(used_gt_idx)),
    }
    endpoint_error_m = float(pos_error_m[-1])

    # 14. summary 是页面第一屏指标卡的主要来源。
    #     endpoint/coverage/divergence 不是论文标准排行榜字段，是物流无人机长航程可用性扩展；
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
        "coverage_ratio": _gt_coverage_ratio(assoc, total_duration_s, original_gt, len(used_gt_idx)),
        "gt_pose_coverage_ratio": _gt_coverage_ratio(assoc, total_duration_s, original_gt, len(used_gt_idx)),
        "gt_time_coverage_ratio": float(total_duration_s / original_gt.duration_s) if original_gt.duration_s > 0 else 1.0,
        "est_pose_coverage_ratio": float(len(used_est_idx) / max(1, len(original_est.positions))),
        "endpoint_error_m": endpoint_error_m,
        "endpoint_error_percent_of_path": float(100.0 * endpoint_error_m / total_gt_path_m) if total_gt_path_m > 0 else math.nan,
        "raw_path_scale_ratio_est_over_gt": float(total_raw_est_path_m / total_gt_path_m) if total_gt_path_m > 0 else math.nan,
    }
    discontinuities_used = detect_associated_discontinuities(
        per_pose["timestamp"].to_numpy(),
        per_pose[["gt_x_m", "gt_y_m", "gt_z_m"]].to_numpy(),
        per_pose[["est_x_aligned_m", "est_y_aligned_m", "est_z_aligned_m"]].to_numpy(),
        step_threshold_m=cfg.discontinuity_step_m,
        time_gap_threshold_s=cfg.discontinuity_time_gap_s,
    )
    continuity = summarize_continuity(discontinuities_all, original_stamps, original_gt_pos, total_gt_path_m)
    discontinuities_all["continuity"] = continuity
    worst_segments = build_worst_segments(segment_records, discontinuities_all, cfg.top_k_worst_segments)
    divergence = detect_divergence(
        pos_error_m,
        per_pose["distance_m"].to_numpy(),
        cfg.divergence_abs_m,
        cfg.divergence_rel_percent,
        per_pose["timestamp"].to_numpy(),
        min_distance_m=cfg.divergence_min_distance_m,
        min_time_s=cfg.divergence_min_time_s,
        discontinuities=discontinuities_all,
        segment_summary=segment_summary,
        alignment=alignment,
        summary=summary,
    )

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
            "used_matches": discontinuities_used,
            "selected_segment": selected_segment,
            "continuity": continuity,
        },
        "alignment": alignment,
        "orientation_correction": orientation_selection,
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
        "rpe_time_delta": rpe_time_delta,
        "segment_errors": segment_summary,
        "worst_segments": worst_segments,
        "speed_bins": speed_bins,
        "runtime": runtime,
        "divergence": divergence,
        "per_pose": per_pose,
        "segment_records": segment_records,
        "trajectory_exports": trajectory_exports,
    }
    return report


def prepare_evaluation_trajectories(
    gt: Trajectory,
    est: Trajectory,
    cfg: EvaluationConfig,
) -> tuple[Trajectory, Trajectory, np.ndarray, np.ndarray, dict[str, Any]]:
    """把 GT 和 VO 准备成同一时间轴上的评估序列。

    代码意义：
    - 默认 interpolate_gt: 以 VO 时间戳为基准，把 GT 插值到 VO 时刻。
      这适合物流无人机/IMU GT 长时间记录场景，VO 只有算法运行段也不会引入无关 GT。
    - nearest: 保留 TUM RGB-D benchmark 的最近邻贪心匹配口径，用于复现论文/开源工具。
    - index: 忽略时间戳，按行号配对，用于已经离线同步好的文件。

    指标对应：
    - 返回的 assoc 会进入 report["association"]。
    - build_associated_trajectories() 会先构造同一时间轴上的 gt_eval/est_eval；
      这里返回的 gt_idx/est_idx 只是兼容旧评估主流程的等长索引，不再表示插值模式下的原始离散 GT 索引。

    来源对应：
    - nearest 模式直接对应 Sturm12/TUM 工具的时间戳匹配。
    - interpolate_gt 是工程扩展：Schubert18/TUM VI 提供高频同步 GT 的评估语境；
      对物流无人机这种“GT 全程跑、VO 只在算法段输出”的数据，按 VO 时间戳插 GT 更合理。
    """
    gt_eval, est_eval, assoc = build_associated_trajectories(gt, est, cfg)
    idx = np.arange(len(gt_eval.positions), dtype=int)
    return gt_eval, est_eval, idx, idx, assoc


def build_associated_trajectories(
    gt: Trajectory,
    est: Trajectory,
    cfg: EvaluationConfig,
) -> tuple[Trajectory, Trajectory, dict[str, Any]]:
    """按配置构造同一时间轴上的 GT/VO 评估轨迹。

    代码意义：
    - interpolate_gt: 默认模式，以 VO 时间戳为基准，把 GT position 线性插值、GT rotation 用 SLERP 插值到 VO 时刻。
    - nearest/tum_greedy_timestamp: 保留 TUM-style greedy timestamp association，不做插值。
    - index: 不看时间戳，显式按行号对齐，主要用于已经离线同步好的调试数据。

    指标对应：
    - 返回的 assoc 直接进入 report["association"]，报告可以据此区分“真实插值”和“最近邻匹配”。
    - 后续 ATE/RPE/RE/断点检测都只看返回的 gt_eval/est_eval，不再关心原始采样频率是否相同。
    """
    mode = cfg.association_mode.lower()
    if mode in {"interpolate_gt", "gt_interpolate", "interpolate", "vo_timestamps"}:
        return interpolate_gt_to_est_timestamps(gt, est, cfg)
    if mode in {"nearest", "tum", "tum_greedy", "tum_greedy_timestamp", "associate"}:
        gt_idx, est_idx, assoc = associate_trajectories(gt, est, cfg.max_time_diff_s, cfg.time_offset_s)
        assoc["mode"] = "nearest"
        assoc["target"] = "nearest_timestamp_pairs"
        assoc["interpolated"] = False
        gt_eval = subset_trajectory(gt, gt_idx)
        est_eval = subset_trajectory(est, est_idx)
        gt_eval.extras["source_index"] = gt_idx
        est_eval.extras["source_index"] = est_idx
        return gt_eval, est_eval, assoc
    if mode in {"index", "index_truncated"}:
        gt_idx, est_idx, assoc = associate_trajectories(gt, est, None, cfg.time_offset_s)
        assoc["mode"] = "index"
        assoc["target"] = "row_index"
        assoc["interpolated"] = False
        gt_eval = subset_trajectory(gt, gt_idx)
        est_eval = subset_trajectory(est, est_idx)
        gt_eval.extras["source_index"] = gt_idx
        est_eval.extras["source_index"] = est_idx
        return gt_eval, est_eval, assoc
    raise ValueError(f"Unknown association mode: {cfg.association_mode}")


def interpolate_gt_to_est_timestamps(
    gt: Trajectory,
    est: Trajectory,
    cfg: EvaluationConfig,
) -> tuple[Trajectory, Trajectory, dict[str, Any]]:
    """将 GT 插值到 VO 时间戳。

    代码意义：
    - 先把 VO 时间戳加上 time_offset_s，解决 GT/VO 两套时钟固定偏移。
    - 只保留落在 GT 时间范围内的 VO 点，避免拿没有 GT 的 VO 段做统计。
    - max_interpolation_gap_s 用来阻止跨很长 GT 缺口插值，避免虚假的平滑 GT。
    - 位置用线性插值；姿态如果存在，后续 interpolate_rotations() 使用 SLERP。

    指标对应：
    - report["association"]["matches"]: 最终参与评估的 VO 时间戳数量。
    - report["association"]["dropped_est_outside_gt_range"]: 因超出 GT 时间范围丢弃的 VO 点。
    - report["association"]["dropped_est_large_gt_gap"]: 因 GT 插值间隔过大丢弃的 VO 点。
    - report["association"]["max_interpolation_gap_s"]: 实际使用样本中的最大 GT 插值间隔。

    来源对应：
    - 不是 5 篇论文里的固定公式，是本系统的时间同步工程扩展。
    - 目的仍然服务 Sturm12/Zhang18 的 ATE/RPE：必须先把两条轨迹放到可比时间轴上。
    """
    return interpolate_reference_to_estimate(
        gt,
        est,
        time_offset_s=cfg.time_offset_s,
        max_interpolation_gap_s=cfg.max_interpolation_gap_s,
        allow_extrapolation=cfg.allow_extrapolation,
        interpolate_rotation=cfg.interpolate_rotation,
        interpolation_position_method=cfg.interpolation_position_method,
        interpolation_rotation_method=cfg.interpolation_rotation_method,
    )


def interpolate_reference_to_estimate(
    reference: Trajectory,
    estimate: Trajectory,
    *,
    time_offset_s: float = 0.0,
    max_interpolation_gap_s: float | None = 0.15,
    allow_extrapolation: bool = False,
    interpolate_rotation: bool = True,
    interpolation_position_method: str = "linear",
    interpolation_rotation_method: str = "slerp",
) -> tuple[Trajectory, Trajectory, dict[str, Any]]:
    """Interpolate reference trajectory to estimate timestamps.

    返回的 ref_interp 和 est_matched 等长，且都使用原始 estimate 时间戳。
    reference 的查询时刻是 estimate.stamps + time_offset_s；这个 target_stamp
    会保存在 extras 中，方便排查固定时间偏移。
    """
    position_method = interpolation_position_method.lower()
    rotation_method = interpolation_rotation_method.lower()
    if position_method != "linear":
        raise ValueError(f"Unsupported interpolation_position_method: {interpolation_position_method}")
    if rotation_method != "slerp":
        raise ValueError(f"Unsupported interpolation_rotation_method: {interpolation_rotation_method}")

    ref_unique = _unique_timestamp_trajectory(reference)
    duplicate_timestamp_count = int(len(reference.stamps) - len(ref_unique.stamps))
    shifted_est_stamps = estimate.stamps + float(time_offset_s)
    finite_est = np.isfinite(shifted_est_stamps)
    before_range = finite_est & (shifted_est_stamps < ref_unique.stamps[0])
    after_range = finite_est & (shifted_est_stamps > ref_unique.stamps[-1])
    if allow_extrapolation:
        in_range = finite_est
    else:
        in_range = finite_est & ~before_range & ~after_range

    candidate_est_indices = np.flatnonzero(in_range)
    target_candidates = shifted_est_stamps[candidate_est_indices]
    bracket_info = interpolation_brackets(ref_unique.stamps, target_candidates, allow_extrapolation=allow_extrapolation)
    candidate_gaps = bracket_info["gap_s"]
    candidate_valid_timestamp = bracket_info["valid_timestamp"]
    if max_interpolation_gap_s is None:
        valid_gap = np.ones(len(candidate_est_indices), dtype=bool)
    else:
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
    dropped_before = int(np.count_nonzero(before_range)) if not allow_extrapolation else 0
    dropped_after = int(np.count_nonzero(after_range)) if not allow_extrapolation else 0
    dropped_gap = int(np.count_nonzero(candidate_valid_timestamp & ~valid_gap))

    ref_positions = interpolate_positions_from_brackets(ref_unique.positions, left_indices, right_indices, alphas)
    if interpolate_rotation and ref_unique.rotations is not None:
        ref_rotations = interpolate_rotations_from_brackets(ref_unique.rotations, left_indices, right_indices, alphas)
        rotation_method_report = "slerp"
    elif ref_unique.rotations is None:
        ref_rotations = None
        rotation_method_report = "skipped_no_reference_rotation"
    else:
        ref_rotations = None
        rotation_method_report = "disabled"

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
        "time_offset_s": float(time_offset_s),
        "max_interpolation_gap_s": max_interpolation_gap_s,
        "max_interpolation_gap_s_allowed": max_interpolation_gap_s,
        "max_interpolation_gap_config_s": max_interpolation_gap_s,
        "allow_extrapolation": bool(allow_extrapolation),
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
        "max_time_diff_s": 0.0,
        "mean_time_diff_s": 0.0,
        "gt_time_coverage_ratio": float(matched_duration / reference.duration_s) if reference.duration_s > 0 else 1.0,
    }
    if not interpolate_rotation:
        info["rotation_interpolation_note"] = "rotation interpolation disabled by config"
    elif ref_unique.rotations is None:
        info["rotation_interpolation_note"] = "rotation interpolation skipped: no reference rotation"
    if info["coverage_estimate_ratio"] < 0.8:
        info["warning"] = "low interpolate_gt coverage; check timestamp units, GT/VO time ranges, time_offset_s, and max_interpolation_gap_s"
    if not len(est_indices):
        info["warning"] = "no VO timestamp remains after interpolation filtering"
    elif len(est_indices) < 2:
        info["warning"] = "fewer than two VO timestamps remain after interpolation filtering"
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


def interpolate_positions(src_stamps: np.ndarray, src_positions: np.ndarray, target_stamps: np.ndarray) -> np.ndarray:
    """GT 位置插值：x/y/z 三个轴分别按时间线性插值。"""
    return np.column_stack([np.interp(target_stamps, src_stamps, src_positions[:, axis]) for axis in range(3)])


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


def interpolation_bracket_gaps(src_stamps: np.ndarray, target_stamps: np.ndarray) -> np.ndarray:
    """计算每个目标时间戳两侧 GT 样本的时间间隔，用于过滤大缺口插值。"""
    return interpolation_brackets(src_stamps, target_stamps)["gap_s"]


def interpolation_brackets(
    src_stamps: np.ndarray,
    target_stamps: np.ndarray,
    allow_extrapolation: bool = False,
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
    if allow_extrapolation and len(src) >= 2:
        left[before] = 0
        right[before] = 1
        left[after] = len(src) - 2
        right[after] = len(src) - 1
    else:
        left[outside] = np.clip(insert[outside] - 1, 0, max(0, len(src) - 1))
        right[outside] = np.clip(insert[outside], 0, max(0, len(src) - 1))

    gaps = np.zeros(len(target), dtype=float)
    gaps[middle] = src[right[middle]] - src[left[middle]]
    extrapolated = outside & allow_extrapolation & (len(src) >= 2)
    gaps[extrapolated] = src[right[extrapolated]] - src[left[extrapolated]]
    gaps[outside & ~extrapolated] = math.inf

    alpha = np.zeros(len(target), dtype=float)
    valid_denominator = gaps > 0
    alpha[valid_denominator] = (target[valid_denominator] - src[left[valid_denominator]]) / gaps[valid_denominator]
    if not allow_extrapolation:
        alpha = np.clip(alpha, 0.0, 1.0)

    left_offset = np.abs(target - src[left])
    right_offset = np.abs(src[right] - target)
    nearest_side_offset = np.minimum(left_offset, right_offset)
    invalid = outside & ~extrapolated
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


def interpolate_rotations(src_stamps: np.ndarray, src_rotations: np.ndarray | None, target_stamps: np.ndarray) -> np.ndarray | None:
    """GT 姿态插值：旋转矩阵先转四元数，再对相邻姿态做 SLERP。"""
    if src_rotations is None:
        return None
    quats = matrix_to_quaternion(src_rotations)
    src = np.asarray(src_stamps, dtype=float)
    target = np.asarray(target_stamps, dtype=float)
    insert = np.searchsorted(src, target, side="left")
    out = np.empty((len(target), 4), dtype=float)
    for i, pos in enumerate(insert):
        if pos <= 0:
            out[i] = quats[0]
        elif pos >= len(src):
            out[i] = quats[-1]
        elif np.isclose(src[pos], target[i]):
            out[i] = quats[pos]
        else:
            alpha = float((target[i] - src[pos - 1]) / (src[pos] - src[pos - 1]))
            out[i] = slerp_quaternion(quats[pos - 1], quats[pos], alpha)
    return quaternion_to_matrix(out[:, 0], out[:, 1], out[:, 2], out[:, 3])


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
    for i, (left, right, alpha) in enumerate(zip(left_indices, right_indices, alphas, strict=False)):
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


def _gt_coverage_ratio(assoc: dict[str, Any], total_duration_s: float, original_gt: Trajectory, used_count: int) -> float:
    """GT 覆盖率口径：插值模式按时间覆盖率，最近邻/索引模式按位姿数量覆盖率。"""
    if assoc.get("mode") == "interpolate_gt":
        return float(total_duration_s / original_gt.duration_s) if original_gt.duration_s > 0 else 1.0
    return float(used_count / max(1, len(original_gt.positions)))


def associate_trajectories(
    gt: Trajectory,
    est: Trajectory,
    max_time_diff_s: float | None,
    time_offset_s: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Associate timestamps using the TUM RGB-D benchmark greedy matching rule.

    TUM's associate.py builds all pairs with abs(t_gt - (t_est + offset))
    below max_difference, sorts by time difference, then greedily keeps
    one-to-one matches.

    指标对应：
    - report["association"]["matches"]：成功匹配数量。
    - max_time_diff_s / mean_time_diff_s：时间关联质量。
    - summary 里的 GT/VO 覆盖率由这里返回的索引数量计算。

    来源对应：
    - 直接对应 Sturm12 提供的 TUM RGB-D benchmark association 工具口径。
    - 后续 ATE/RPE 的可比性依赖这个一对一匹配。
    """
    if len(gt.stamps) == len(est.stamps):
        diffs = np.abs(gt.stamps - (est.stamps + time_offset_s))
        if max_time_diff_s is None or np.nanmax(diffs) <= max_time_diff_s:
            idx = np.arange(len(gt.stamps), dtype=int)
            return idx, idx, {
                "method": "index_equal_length",
                "matches": int(len(idx)),
                "time_offset_s": float(time_offset_s),
                "max_time_diff_s": float(np.nanmax(diffs)) if len(diffs) else 0.0,
                "mean_time_diff_s": float(np.nanmean(diffs)) if len(diffs) else 0.0,
            }

    if max_time_diff_s is None:
        n = min(len(gt.stamps), len(est.stamps))
        idx = np.arange(n, dtype=int)
        return idx, idx, {"method": "index_truncated", "matches": int(n), "time_offset_s": float(time_offset_s)}

    potential_matches: list[tuple[float, int, int]] = []
    shifted_est_stamps = est.stamps + time_offset_s
    for gt_i, gt_t in enumerate(gt.stamps):
        left = int(np.searchsorted(shifted_est_stamps, gt_t - max_time_diff_s, side="left"))
        right = int(np.searchsorted(shifted_est_stamps, gt_t + max_time_diff_s, side="right"))
        for est_i in range(left, right):
            diff = abs(float(gt_t - shifted_est_stamps[est_i]))
            if diff < max_time_diff_s:
                potential_matches.append((diff, gt_i, est_i))
    potential_matches.sort(key=lambda item: item[0])

    gt_available = set(range(len(gt.stamps)))
    est_available = set(range(len(est.stamps)))
    matches: list[tuple[int, int, float]] = []
    for diff, gt_i, est_i in potential_matches:
        if gt_i in gt_available and est_i in est_available:
            gt_available.remove(gt_i)
            est_available.remove(est_i)
            matches.append((gt_i, est_i, diff))
    matches.sort(key=lambda item: item[0])

    gt_indices = [m[0] for m in matches]
    est_indices = [m[1] for m in matches]
    diffs = [m[2] for m in matches]

    if len(gt_indices) < 2 and len(gt.stamps) == len(est.stamps):
        idx = np.arange(len(gt.stamps), dtype=int)
        return idx, idx, {
            "method": "index_equal_length_fallback",
            "matches": int(len(idx)),
            "time_offset_s": float(time_offset_s),
            "warning": "timestamp association found fewer than two matches; fell back to equal-length index pairing",
        }

    return np.asarray(gt_indices, dtype=int), np.asarray(est_indices, dtype=int), {
        "method": "tum_greedy_timestamp",
        "matches": int(len(gt_indices)),
        "max_allowed_time_diff_s": float(max_time_diff_s),
        "time_offset_s": float(time_offset_s),
        "max_time_diff_s": float(np.max(diffs)) if diffs else math.nan,
        "mean_time_diff_s": float(np.mean(diffs)) if diffs else math.nan,
    }


def compute_alignment(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None = None,
    est_rot: np.ndarray | None = None,
    mode: str = "se3",
) -> dict[str, Any]:
    """计算 VO 到 GT 的轨迹对齐变换。

    指标对应：
    - SE3: 尺度固定为 1，适合双目/VIO/尺度已知。
    - Sim3: 同时估计尺度，适合单目 VO/尺度未知。
    - first_pose: 只把首帧对齐，用于观察误差随航程增长。
    - alignment["scale"] 最终显示为页面“对齐尺度”。

    实现细节：
    - 位置对齐用 Umeyama SVD。输入 src=VO，dst=GT，输出 scale/rotation/translation。
    - 姿态只在 first_pose 模式中用于首帧旋转对齐；SE3/Sim3 的旋转主要由位置轨迹估计。
    - 所有 ATE、RPE、segment_errors 都基于对齐后的 est_pos_aligned 计算。

    来源对应：
    - Sturm12 的 ATE 需要先把估计轨迹配准到 GT 后再算绝对误差。
    - Zhang18 明确说明轨迹对齐方式要随传感器可观性变化：
      单目无尺度通常看 Sim3，尺度已知的双目/VIO 更应看 SE3。
    """
    mode = mode.lower()
    if mode in {"none", "identity"}:
        # 不对齐模式用于调试原始坐标系；如果 GT/VO 不在同一坐标系，误差会很大。
        return _alignment_dict(mode, 1.0, np.eye(3), np.zeros(3))
    if mode in {"first_pose", "first", "origin"}:
        # 首帧对齐只消除起点坐标差，不用全局最小二乘消除后续漂移；
        # 适合观察误差是否随距离逐渐累积。
        scale = 1.0
        if gt_rot is not None and est_rot is not None:
            rot = gt_rot[0] @ est_rot[0].T
        else:
            rot = np.eye(3)
        trans = gt_pos[0] - scale * (rot @ est_pos[0])
        return _alignment_dict("first_pose", scale, rot, trans)
    if mode in {"se3", "rigid"}:
        # SE3 固定 scale=1。双目、VIO、带尺度传感器的 VO 应优先用它，
        # 因为它不会替算法隐藏尺度错误。
        scale, rot, trans = umeyama_alignment(est_pos, gt_pos, with_scale=False)
        return _alignment_dict("se3", scale, rot, trans)
    if mode in {"sim3", "similarity"}:
        # Sim3 允许估计全局尺度。单目无尺度 VO 用它可以评估“轨迹形状”，
        # 但不能证明原始输出已经具备真实米制尺度。
        scale, rot, trans = umeyama_alignment(est_pos, gt_pos, with_scale=True)
        return _alignment_dict("sim3", scale, rot, trans)
    raise ValueError(f"Unknown alignment mode: {mode}")


def umeyama_alignment(src: np.ndarray, dst: np.ndarray, with_scale: bool) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama SVD 对齐。

    src 是 VO，dst 是 GT。with_scale=False 得到 SE3；with_scale=True 得到 Sim3。

    代码意义：
    - 通过最小二乘求 R/t/s，使 s * R * VO + t 尽量贴近 GT。
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

    # 2. 交叉协方差描述 VO 与 GT 的主方向关系，SVD 从中恢复最优旋转。
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
    """把 VO 位置应用到 GT 坐标系。

    公式：p_aligned = scale * R * p_vo + t。
    之后所有位置误差字段都基于这个结果：
    - per_pose.error_m / horizontal_error_m / vertical_error_m
    - ate_position_m / ate_horizontal_m / ate_vertical_m
    - rpe_frame_delta.translation_m
    - segment_errors.translation_error_*
    """
    scale = float(alignment["scale"])
    rot = np.asarray(alignment["rotation"], dtype=float)
    trans = np.asarray(alignment["translation"], dtype=float)
    return scale * (positions @ rot.T) + trans


def apply_rotation_alignment(rotations: np.ndarray | None, alignment: dict[str, Any]) -> np.ndarray | None:
    """把 VO 姿态应用同一个对齐旋转。

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
    - 默认系统可以按 VO 时间戳统一评估，也可以按连续段分别对齐/评估。
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


def select_orientation_correction(
    gt: Trajectory,
    est: Trajectory,
    gt_idx: np.ndarray,
    est_idx: np.ndarray,
    eval_ranges: list[dict[str, int]],
    cfg: EvaluationConfig,
) -> dict[str, Any]:
    """选择 VO 姿态修正方式。

    指标对应：
    - report["orientation_correction"]["selected"] 是最终应用到 VO 姿态上的修正。
    - requested="auto" 时，系统会在 AUTO_ORIENTATION_CORRECTION_CANDIDATES 中逐个试算，
      根据姿态 RMSE、yaw RMSE、RPE 平移和 RPE 旋转组成的 score 选最优候选。
    - requested="ignore" 时，后续 RPE/子轨迹误差退化为 position-only 口径。

    来源对应：
    - 不是 5 篇论文里的标准指标，是为 ENU/NED、camera-to-body、旋转矩阵方向不一致增加的工程扩展。
    - 评分里使用的 orientation/RPE 误差来自 Zhang18/Sturm12；坐标约定问题在 Schubert18 这类 VIO 数据中很常见。
    """
    requested = normalize_orientation_correction(cfg.orientation_correction)
    base = {
        "requested": requested,
        "selected": requested,
        "auto": requested == "auto",
        "available": bool(gt.rotations is not None and est.rotations is not None),
        "score_metric": "orientation_rmse_deg + 0.25*yaw_rmse_deg + 2*rpe_rotation_rmse_deg + rpe_translation_rmse_m",
    }
    if requested == "ignore":
        # ignore 是明确告诉系统不要使用姿态；位置 ATE 仍然可算，
        # 但 rotation RPE、rotation_error_deg_per_m、ate_orientation_deg 会缺失或退化。
        return {**base, "uses_rotations": False, "note": "orientation fields ignored; RPE/segment errors use position-only relative motion"}
    if gt.rotations is None or est.rotations is None:
        # 有些 VO 只输出 xyz，没有姿态。此时不能强行计算旋转误差，
        # 否则报告会给出没有物理意义的角度指标。
        return {**base, "selected": "none", "uses_rotations": False, "note": "GT or VO has no orientation; correction skipped"}
    if requested != "auto":
        # 手动模式直接信任用户选择。validate 只检查模式合法，不判断好坏。
        validate_orientation_correction(requested)
        return {**base, "uses_rotations": True}

    candidates: list[dict[str, Any]] = []
    for candidate in AUTO_ORIENTATION_CORRECTION_CANDIDATES:
        # auto 会遍历常见坐标系/外参候选：取逆、ENU/NED、绕轴 180 度等。
        # 每个候选只快速算姿态/RPE 分数，不生成完整 report，避免页面等待过久。
        result = score_orientation_correction_candidate(gt, est, gt_idx, est_idx, eval_ranges, cfg, candidate)
        if result is not None:
            candidates.append(result)
    if not candidates:
        return {**base, "selected": "none", "uses_rotations": True, "note": "no valid orientation correction candidate"}

    best = min(candidates, key=lambda item: item["score"])
    return {
        **base,
        "selected": best["mode"],
        "uses_rotations": True,
        "best_score": best["score"],
        "candidates": candidates,
    }


def score_orientation_correction_candidate(
    gt: Trajectory,
    est: Trajectory,
    gt_idx: np.ndarray,
    est_idx: np.ndarray,
    eval_ranges: list[dict[str, int]],
    cfg: EvaluationConfig,
    candidate: str,
) -> dict[str, Any] | None:
    """给一个姿态修正候选打分，供 auto 模式选择。

    只使用姿态 ATE 和 RPE，不重新计算完整子轨迹表，避免自动选择过慢。

    评分含义：
    - orientation_rmse_deg: 整体姿态是否和 GT 接近。
    - yaw_rmse_deg: 航向角是否合理；无人机航向通常很重要，但欧拉 yaw 容易受坐标约定影响。
    - rpe_rotation_rmse_deg: 相对旋转是否稳定，避免只靠全局姿态 ATE 误选。
    - rpe_translation_rmse_m: 姿态修正会影响首帧/SE3 对齐和相对运动，因此也纳入少量位置约束。

    指标对应：
    - 最优候选写入 report["orientation_correction"]["selected"]。
    - 所有候选分数写入 report["orientation_correction"]["candidates"]，方便报告里复查。

    来源对应：
    - 候选选择不是论文标准流程；它是把 Zhang18 的姿态误差和 Sturm12 的 RPE 作为可解释评分项。
    - 目的是避免无人机数据因 ENU/NED 或外参约定不同而把本来可比的姿态误判为算法错误。
    """
    orientation_parts: list[np.ndarray] = []
    yaw_parts: list[np.ndarray] = []
    rpe_trans_parts: list[np.ndarray] = []
    rpe_rot_parts: list[np.ndarray] = []
    for seg in eval_ranges:
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
        est_rot = apply_orientation_correction(est_rot_raw, candidate) if est_rot_raw is not None else None
        if gt_rot is None or est_rot is None:
            continue
        # 对每个候选都重新做一次对齐，因为不同姿态修正会影响 first_pose/姿态旋转对齐。
        alignment = compute_alignment(gt_pos, est_pos, gt_rot, est_rot, mode=cfg.alignment)
        est_pos_aligned = apply_alignment(est_pos, alignment)
        est_rot_aligned = apply_rotation_alignment(est_rot, alignment)
        if est_rot_aligned is None:
            continue
        orientation_parts.append(np.degrees(rotation_errors(gt_rot, est_rot_aligned)))
        yaw_parts.append(np.abs(np.degrees(wrap_pi(yaw_from_rot(est_rot_aligned) - yaw_from_rot(gt_rot)))))
        rpe_frame = rpe_frame_dataframe(
            gt_pos,
            est_pos_aligned,
            gt_rot,
            est_rot_aligned,
            gt.stamps[cur_gt_idx],
            segment_id=0,
            match_indices=np.arange(len(cur_gt_idx), dtype=int),
            delta=max(1, int(cfg.rpe_delta_frames)),
            delta_value=cfg.rpe_delta_value,
            delta_unit=cfg.rpe_delta_unit,
            distance_tolerance_ratio=cfg.rpe_distance_tolerance_ratio,
        )
        rpe_valid = rpe_frame["rpe_available"].to_numpy(dtype=bool) if "rpe_available" in rpe_frame else np.asarray([], dtype=bool)
        rpe_trans = rpe_frame.loc[rpe_valid, "rpe_translation_m"].to_numpy(dtype=float) if len(rpe_frame) else np.asarray([], dtype=float)
        rpe_rot = rpe_frame.loc[rpe_valid, "rpe_rotation_deg"].dropna().to_numpy(dtype=float) if len(rpe_frame) else np.asarray([], dtype=float)
        rpe_trans_parts.append(rpe_trans)
        if len(rpe_rot):
            rpe_rot_parts.append(rpe_rot)
    if not orientation_parts:
        return None

    orientation = np.concatenate(orientation_parts)
    yaw = np.concatenate(yaw_parts) if yaw_parts else np.asarray([], dtype=float)
    rpe_trans = np.concatenate(rpe_trans_parts) if rpe_trans_parts else np.asarray([], dtype=float)
    rpe_rot = np.concatenate(rpe_rot_parts) if rpe_rot_parts else np.asarray([], dtype=float)
    orientation_rmse = rmse(orientation)
    yaw_rmse = rmse(yaw)
    rpe_trans_rmse = rmse(rpe_trans)
    rpe_rot_rmse = rmse(rpe_rot)
    # 权重是经验规则：旋转 RPE 权重大一些，避免选到全局角度看似接近但相对旋转不稳定的候选。
    # 这不是学习模型，只是一套可解释的确定性评分。
    score = orientation_rmse + 0.25 * yaw_rmse + 2.0 * rpe_rot_rmse + rpe_trans_rmse
    return {
        "mode": candidate,
        "score": float(score),
        "orientation_rmse_deg": float(orientation_rmse),
        "yaw_rmse_deg": float(yaw_rmse),
        "rpe_translation_rmse_m": float(rpe_trans_rmse),
        "rpe_rotation_rmse_deg": float(rpe_rot_rmse),
    }


def rmse(values: np.ndarray) -> float:
    """RMSE 基础函数。

    NaN/Inf 会被忽略；空数组返回 inf，用于 auto 姿态评分时自动排在最后。
    """
    arr = np.asarray(values, dtype=float).reshape(-1)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return math.inf
    return float(np.sqrt(np.mean(arr * arr)))


def normalize_orientation_correction(mode: str | None) -> str:
    """把用户输入/前端选项归一化成内部姿态修正关键字。"""
    normalized = (mode or "none").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": "none",
        "off": "none",
        "identity": "none",
        "no_correction": "none",
        "auto_select": "auto",
        "automatic": "auto",
        "position_only": "ignore",
        "ignore_orientation": "ignore",
        "no_orientation": "ignore",
        "rt": "inverse",
        "transpose": "inverse",
        "ned_enu_left": "enu_ned_left",
        "ned_enu_right": "enu_ned_right",
        "ned_enu_both": "enu_ned_both",
        "rz180": "rz180_right",
        "z180": "rz180_right",
    }
    return aliases.get(normalized, normalized)


def validate_orientation_correction(mode: str) -> None:
    """检查姿态修正模式是否合法。

    这里不判断某个模式是否适合当前数据，只保证 apply_orientation_correction()
    后续可以找到对应矩阵操作。
    """
    if mode in {"none", "auto", "ignore", "inverse"}:
        return
    pure = mode.removesuffix("_inverse")
    if pure in {
        "enu_ned_left",
        "enu_ned_right",
        "enu_ned_both",
        "rx180_left",
        "rx180_right",
        "ry180_left",
        "ry180_right",
        "rz180_left",
        "rz180_right",
    }:
        return
    raise ValueError(f"Unknown orientation_correction mode: {mode}")


def apply_orientation_correction(rotations: np.ndarray | None, mode: str) -> np.ndarray | None:
    """把 VO 姿态从其输出约定修正到评估使用的姿态约定。

    left 表示 M @ R，常用于世界坐标轴转换；right 表示 R @ M，常用于相机系到机体系外参；
    both 表示 M @ R @ M.T，常用于同一个旋转矩阵两侧坐标基变换。
    """
    if rotations is None:
        return None
    normalized = normalize_orientation_correction(mode)
    validate_orientation_correction(normalized)
    if normalized in {"none", "auto"}:
        return rotations
    if normalized == "ignore":
        return None

    out = np.asarray(rotations, dtype=float)
    if normalized == "inverse":
        # 有些数据保存的是 body->world，有些保存的是 world->body；取逆用于修正方向相反的旋转定义。
        return np.transpose(out, (0, 2, 1))

    use_inverse = normalized.endswith("_inverse")
    pure = normalized.removesuffix("_inverse")
    if use_inverse:
        out = np.transpose(out, (0, 2, 1))

    if pure.startswith("enu_ned"):
        # ENU/NED 是无人机和机器人数据中最常见的世界坐标约定差异。
        matrix = enu_ned_matrix()
    elif pure.startswith("rx180"):
        matrix = axis_flip_matrix("x")
    elif pure.startswith("ry180"):
        matrix = axis_flip_matrix("y")
    elif pure.startswith("rz180"):
        matrix = axis_flip_matrix("z")
    else:
        raise ValueError(f"Unknown orientation_correction mode: {mode}")

    if pure.endswith("_left"):
        # 左乘：改变世界/参考坐标轴。
        return np.einsum("ij,njk->nik", matrix, out)
    if pure.endswith("_right"):
        # 右乘：改变机体/相机自身坐标轴，常用于 camera-to-body 外参。
        return np.einsum("nij,jk->nik", out, matrix)
    if pure.endswith("_both"):
        # 两侧变换：同一个旋转矩阵在两套坐标基之间表达。
        return np.einsum("ij,njk,kl->nil", matrix, out, matrix.T)
    raise ValueError(f"Unknown orientation_correction mode: {mode}")


def enu_ned_matrix() -> np.ndarray:
    """ENU/NED 世界坐标轴转换矩阵：交换 x/y，并翻转 z。"""
    return np.asarray([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0]], dtype=float)


def axis_flip_matrix(axis: str) -> np.ndarray:
    """绕 x/y/z 轴旋转 180 度的固定外参候选。"""
    if axis == "x":
        return np.diag([1.0, -1.0, -1.0])
    if axis == "y":
        return np.diag([-1.0, 1.0, -1.0])
    if axis == "z":
        return np.diag([-1.0, -1.0, 1.0])
    raise ValueError(f"Unknown axis: {axis}")


def rpe_error_arrays(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    delta: int,
) -> tuple[np.ndarray, np.ndarray]:
    """固定帧间隔 RPE。

    对每个 i 取 j=i+delta，比较 GT 相对运动和 VO 相对运动。
    返回值对应 report["rpe_frame_delta"]["translation_m"] 和 rotation_deg。

    与 ATE 的区别：
    - ATE 看对齐后每一帧的绝对位置差。
    - RPE 看 i->j 这段相对运动是否一致，更敏感于帧间估计稳定性。
    - delta_frames 越大，越接近中短程累计漂移；越小，越接近单帧运动误差。

    来源对应：
    - 直接对应 Sturm12 的 Relative Pose Error。
    - Zhang18 也把它作为相对轨迹误差解释；Schubert18/TUM VI 在 VIO 评估中使用固定时间间隔 RPE 语境。
    """
    n = len(gt_pos)
    if n <= delta:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    trans_errors: list[float] = []
    rot_errors: list[float] = []
    for i in range(n - delta):
        j = i + delta
        # relative_error() 同时支持有姿态和无姿态两种口径：
        # 有姿态时在局部坐标系比较相对运动；无姿态时退化成世界系位移差。
        terr, rerr = relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j)
        trans_errors.append(terr)
        if rerr is not None:
            rot_errors.append(rerr)
    return np.asarray(trans_errors, dtype=float), np.asarray(rot_errors, dtype=float)


def rpe_by_frame_delta(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    delta: int,
) -> dict[str, Any]:
    """把 RPE 数组包装成 report["rpe_frame_delta"] 使用的统计结构。

    来源对应：
    - translation_m / rotation_deg 直接来自 Sturm12 的 RPE 平移和旋转误差。
    - count/rmse/mean 等统计是报告层汇总，不改变 RPE 公式。
    """
    trans_errors, rot_errors = rpe_error_arrays(gt_pos, est_pos, gt_rot, est_rot, delta)
    return {
        "delta_frames": int(delta),
        "count": int(len(trans_errors)),
        "translation_m": describe(trans_errors),
        "rotation_deg": describe(np.degrees(rot_errors)) if len(rot_errors) else None,
    }


def rpe_error_arrays_by_time(
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    stamps: np.ndarray,
    delta_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    """固定时间间隔 RPE。

    对每个起点 i，寻找时间最接近 stamps[i] + delta_s 的终点 j。
    这比固定帧数更适合不均匀时间戳、丢帧或 VO 输出频率变化的数据。
    """
    if len(stamps) < 2 or delta_s <= 0:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    stamps = np.asarray(stamps, dtype=float)
    trans_errors: list[float] = []
    rot_errors: list[float] = []
    for i, stamp in enumerate(stamps[:-1]):
        target = stamp + delta_s
        j = nearest_time_index(stamps, i, target)
        if j <= i:
            continue
        terr, rerr = relative_error(gt_pos, est_pos, gt_rot, est_rot, i, j)
        trans_errors.append(terr)
        if rerr is not None:
            rot_errors.append(rerr)
    return np.asarray(trans_errors, dtype=float), np.asarray(rot_errors, dtype=float)


def nearest_time_index(stamps: np.ndarray, start_idx: int, target: float) -> int:
    """从 start_idx 后面找到最接近目标时间的索引。"""
    left = int(np.searchsorted(stamps, target, side="left"))
    candidates = [idx for idx in (left - 1, left, left + 1) if start_idx < idx < len(stamps)]
    if not candidates:
        return -1
    return min(candidates, key=lambda idx: abs(float(stamps[idx] - target)))


def summarize_time_rpe(
    trans_parts: dict[float, list[np.ndarray]],
    rot_parts: dict[float, list[np.ndarray]],
) -> dict[str, Any]:
    """汇总固定时间间隔 RPE，输出 report["rpe_time_delta"]。"""
    out: dict[str, Any] = {}
    for delta_s in sorted(trans_parts):
        trans = np.concatenate(trans_parts[delta_s]) if trans_parts[delta_s] else np.asarray([], dtype=float)
        rot = np.concatenate(rot_parts.get(delta_s, [])) if rot_parts.get(delta_s) else np.asarray([], dtype=float)
        out[f"{delta_s:g}s"] = {
            "delta_s": float(delta_s),
            "count": int(len(trans)),
            "translation_m": describe(trans),
            "rotation_deg": describe(rot) if len(rot) else None,
        }
    return out


def compute_global_ate(
    gt: Trajectory,
    est: Trajectory,
    used_gt_idx: np.ndarray,
    used_est_idx: np.ndarray,
    orientation_correction: str,
    mode: str = "sim3",
) -> dict[str, Any]:
    """对所有已使用匹配点做一次全局对齐 ATE。

    segment-wise Sim3 可以评估每个连续段形状，但会掩盖跨 reset 的坐标不连续；
    global Sim3 使用一个统一尺度/旋转/平移，更适合判断整条航线是否能被一个尺度解释。
    """
    gt_pos = gt.positions[used_gt_idx]
    est_pos = est.positions[used_est_idx]
    gt_rot = gt.rotations[used_gt_idx] if gt.rotations is not None else None
    est_rot_raw = est.rotations[used_est_idx] if est.rotations is not None else None
    est_rot = apply_orientation_correction(est_rot_raw, orientation_correction) if est_rot_raw is not None else None
    if orientation_correction == "ignore":
        gt_rot = None
        est_rot = None
    alignment = compute_alignment(gt_pos, est_pos, gt_rot, est_rot, mode=mode)
    est_pos_aligned = apply_alignment(est_pos, alignment)
    errors = est_pos_aligned - gt_pos
    pos_error_m = np.linalg.norm(errors, axis=1)
    return {
        "alignment": alignment,
        "position_m": describe(pos_error_m),
        "horizontal_m": describe(np.linalg.norm(errors[:, :2], axis=1)),
        "vertical_abs_m": describe(np.abs(errors[:, 2])),
        "vertical_signed_m": describe(errors[:, 2]),
    }


def build_ate_report(
    segment_wise_pos_error_m: np.ndarray,
    global_sim3_ate: dict[str, Any],
    cfg: EvaluationConfig,
    alignment: dict[str, Any],
) -> dict[str, Any]:
    """构造新的 ATE 结构，明确区分分段对齐和全局对齐。"""
    is_segment_wise = cfg.continuous_segment_policy == "segments" and cfg.alignment.lower() in {"sim3", "similarity"}
    primary_label = "segment-wise Sim3 ATE" if is_segment_wise else f"{cfg.alignment.upper()} ATE"
    warning = None
    if is_segment_wise:
        warning = "segment-wise Sim3 ATE only evaluates each continuous segment shape; it may hide cross-reset discontinuity and scale inconsistency."
    return {
        "primary_label": primary_label,
        "primary_position_m": describe(segment_wise_pos_error_m),
        "segment_wise": {
            "alignment_mode": alignment.get("base_mode") or alignment.get("mode"),
            "position_m": describe(segment_wise_pos_error_m),
        },
        "global": {
            "sim3": global_sim3_ate,
        },
        "global_sim3_ate_position_m": global_sim3_ate.get("position_m"),
        "segment_wise_sim3_ate_position_m": describe(segment_wise_pos_error_m) if cfg.alignment.lower() in {"sim3", "similarity"} else None,
        "warning": warning,
    }


def segment_errors(
    gt_pos: np.ndarray,
    est_pos_aligned: np.ndarray,
    est_pos_raw: np.ndarray,
    gt_rot: np.ndarray | None,
    est_rot: np.ndarray | None,
    stamps: np.ndarray,
    lengths_m: Iterable[float],
    max_segments_per_length: int = 10000,
    step_frames: int = 10,
    max_length_diff_ratio: float = 0.05,
) -> dict[str, Any]:
    """按距离的 KITTI/rpg 风格子轨迹误差。

    这是物流无人机长航程最重要的漂移指标之一：
    - length_m: 目标子轨迹长度 L。
    - translation_error_percent: 100 * 相对位移误差 / actual_length_m。
    - rotation_error_deg_per_m: 姿态相对误差除以 actual_length_m。
    - raw_scale_ratio_est_over_gt: 原始 VO 段路程 / GT 实际段路程。
    - aligned_scale_ratio_est_over_gt: 对齐后 VO 段路程 / GT 实际段路程。

    计算口径：
    - 先按 GT 累计路程找到起点 i 和目标终点 j，使 GT 路程约等于 L。
    - 再比较 i->j 的 GT 相对运动和 VO 相对运动。
    - 每个长度 L 会抽很多段，最后用 describe() 汇总成 mean/p95/max 等统计。

    指标解释：
    - 短距离 L 偏高：通常是前端跟踪、RANSAC、图像质量或运动模糊问题。
    - 长距离 L 偏高：通常是累计漂移、尺度、后端约束或闭环/重定位能力问题。

    来源对应：
    - translation_error_percent 和 rotation_error_deg_per_m 直接对应 Geiger12/KITTI odometry 的子轨迹漂移口径。
    - scale_ratio_est_over_gt / scale_drift_percent 是 Zhang18/rpg 相对误差和尺度可观性思想下的扩展。
    - 本系统把 KITTI 常用车载长度扩展到 1000m、2000m、5000m 等物流无人机长航程长度。
    """
    cumulative = path_distance(gt_pos)
    total_length = cumulative[-1] if len(cumulative) else 0.0
    records: list[dict[str, float]] = []
    summaries: list[dict[str, Any]] = []

    for length in sorted({float(x) for x in lengths_m if float(x) > 0}):
        if length > total_length:
            # 轨迹总长不够时不能强行统计该长度，否则会让长航程指标失真。
            continue
        step = max(1, int(step_frames))
        candidate_starts = np.arange(0, len(gt_pos) - 1, step, dtype=int)
        if len(candidate_starts) > max_segments_per_length:
            # 长轨迹可能有几十万帧，这里通过抽样限制计算量；
            # 抽样只减少样本数量，不改变单个子轨迹误差公式。
            stride = int(math.ceil(len(candidate_starts) / max_segments_per_length))
            candidate_starts = candidate_starts[::stride]
        length_records: list[dict[str, float]] = []
        for i in candidate_starts:
            target = cumulative[i] + length
            max_diff_m = max(10.0, length * max(0.0, max_length_diff_ratio))
            j = find_segment_end(cumulative, i, target, max_diff_m)
            if j >= len(gt_pos) or j <= i:
                continue
            actual_length = float(cumulative[j] - cumulative[i])
            if actual_length <= 0:
                continue
            # terr/rerr 是该固定距离子轨迹的核心误差；百分比使用 actual_length，
            # 避免 1000m 目标段实际只有 900m 时仍按 1000m 分母低估误差。
            terr, rerr = relative_error(gt_pos, est_pos_aligned, gt_rot, est_rot, i, j)
            duration = float(stamps[j] - stamps[i]) if len(stamps) else math.nan
            speed = actual_length / duration if duration > 0 else math.nan
            raw_est_segment = float(path_distance(est_pos_raw[i : j + 1])[-1])
            aligned_est_segment = float(path_distance(est_pos_aligned[i : j + 1])[-1])
            raw_scale_ratio = raw_est_segment / actual_length if actual_length > 0 else math.nan
            aligned_scale_ratio = aligned_est_segment / actual_length if actual_length > 0 else math.nan
            gt_delta_world = gt_pos[j] - gt_pos[i]
            est_delta_world = est_pos_aligned[j] - est_pos_aligned[i]
            delta_error_world = est_delta_world - gt_delta_world
            horizontal_error_m = float(np.linalg.norm(delta_error_world[:2]))
            vertical_error_signed_m = float(delta_error_world[2])
            vertical_error_abs_m = abs(vertical_error_signed_m)
            yaw_error_signed_deg = math.nan
            yaw_error_abs_deg = math.nan
            yaw_error_deg_per_m = math.nan
            if gt_rot is not None and est_rot is not None:
                gt_r_rel, _ = relative_pose(gt_rot[i], gt_pos[i], gt_rot[j], gt_pos[j])
                est_r_rel, _ = relative_pose(est_rot[i], est_pos_aligned[i], est_rot[j], est_pos_aligned[j])
                yaw_error_signed = float(wrap_pi(yaw_from_rot(est_r_rel[np.newaxis, :, :]) - yaw_from_rot(gt_r_rel[np.newaxis, :, :]))[0])
                yaw_error_signed_deg = float(np.degrees(yaw_error_signed))
                yaw_error_abs_deg = abs(yaw_error_signed_deg)
                yaw_error_deg_per_m = yaw_error_abs_deg / actual_length if actual_length > 0 else math.nan
            rec = {
                "length_m": float(length),
                "start_index": float(i),
                "end_index": float(j),
                "start_time_s": float(stamps[i]) if len(stamps) else math.nan,
                "end_time_s": float(stamps[j]) if len(stamps) else math.nan,
                "duration_s": float(duration),
                "start_distance_m": float(cumulative[i]),
                "end_distance_m": float(cumulative[j]),
                "actual_length_m": actual_length,
                "length_diff_m": float(actual_length - length),
                "translation_error_m": float(terr),
                "translation_error_percent": float(100.0 * terr / actual_length),
                "horizontal_translation_error_m": horizontal_error_m,
                "horizontal_translation_error_percent": float(100.0 * horizontal_error_m / actual_length),
                "vertical_error_signed_m": vertical_error_signed_m,
                "vertical_error_abs_m": vertical_error_abs_m,
                "vertical_error_percent_of_length": float(100.0 * vertical_error_abs_m / actual_length),
                "rotation_error_deg": float(np.degrees(rerr)) if rerr is not None else math.nan,
                "rotation_error_deg_per_m": float(np.degrees(rerr) / actual_length) if rerr is not None else math.nan,
                "segment_yaw_error_signed_deg": yaw_error_signed_deg,
                "segment_yaw_error_abs_deg": yaw_error_abs_deg,
                "segment_yaw_error_deg_per_m": yaw_error_deg_per_m,
                "speed_mps": float(speed),
                "raw_scale_ratio_est_over_gt": float(raw_scale_ratio),
                "raw_scale_drift_percent": float((raw_scale_ratio - 1.0) * 100.0) if math.isfinite(raw_scale_ratio) else math.nan,
                "aligned_scale_ratio_est_over_gt": float(aligned_scale_ratio),
                "aligned_scale_drift_percent": float((aligned_scale_ratio - 1.0) * 100.0) if math.isfinite(aligned_scale_ratio) else math.nan,
                "scale_ratio_est_over_gt": float(raw_scale_ratio),
                "scale_drift_percent": float((raw_scale_ratio - 1.0) * 100.0) if math.isfinite(raw_scale_ratio) else math.nan,
            }
            length_records.append(rec)
            records.append(rec)
        if length_records:
            frame = pd.DataFrame(length_records)
            summaries.append(
                {
                    "length_m": float(length),
                    "count": int(len(frame)),
                    "translation_error_percent": describe(frame["translation_error_percent"].to_numpy()),
                    "translation_error_m": describe(frame["translation_error_m"].to_numpy()),
                    "horizontal_translation_error_m": describe_clean(frame, "horizontal_translation_error_m"),
                    "horizontal_translation_error_percent": describe_clean(frame, "horizontal_translation_error_percent"),
                    "vertical_error_signed_m": describe_clean(frame, "vertical_error_signed_m"),
                    "vertical_error_abs_m": describe_clean(frame, "vertical_error_abs_m"),
                    "vertical_error_percent_of_length": describe_clean(frame, "vertical_error_percent_of_length"),
                    "rotation_error_deg_per_m": describe(frame["rotation_error_deg_per_m"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()),
                    "segment_yaw_error_signed_deg": describe_clean(frame, "segment_yaw_error_signed_deg"),
                    "segment_yaw_error_abs_deg": describe_clean(frame, "segment_yaw_error_abs_deg"),
                    "segment_yaw_error_deg_per_m": describe_clean(frame, "segment_yaw_error_deg_per_m"),
                    "raw_scale_ratio_est_over_gt": describe_clean(frame, "raw_scale_ratio_est_over_gt"),
                    "raw_scale_drift_percent": describe_clean(frame, "raw_scale_drift_percent"),
                    "aligned_scale_ratio_est_over_gt": describe_clean(frame, "aligned_scale_ratio_est_over_gt"),
                    "aligned_scale_drift_percent": describe_clean(frame, "aligned_scale_drift_percent"),
                    "scale_ratio_est_over_gt": describe_clean(frame, "raw_scale_ratio_est_over_gt"),
                    "scale_drift_percent": describe_clean(frame, "raw_scale_drift_percent"),
                }
            )
    records_frame = pd.DataFrame(records)
    return {"summary": summaries or summarize_segment_records(records_frame), "records": records_frame}


def summarize_segment_records(records: pd.DataFrame) -> list[dict[str, Any]]:
    """按子轨迹目标长度聚合 segment_records。

    指标对应：
    - translation_error_percent: 长距离漂移百分比，物流无人机长航程重点看。
    - rotation_error_deg_per_m: 每米旋转误差。
    - scale_ratio_est_over_gt / scale_drift_percent: 分段尺度和尺度漂移。

    代码意义：
    - segment_records 是“每一个子轨迹样本”的明细表。
    - segment_errors 是“按 length_m 聚合后的统计表”，页面图表和报告主表主要看它。
    - 每个误差数组都通过 describe() 生成 count/rmse/mean/median/std/min/max/p95/p99。

    来源对应：
    - 聚合维度 length_m 来自 Geiger12/KITTI 按固定路径长度汇总误差的设计。
    - describe() 的统计项用于报告展示；其中 RMSE 是 Sturm12/Zhang18 常见的轨迹误差汇总方式。
    """
    if records.empty or "length_m" not in records:
        return []
    summaries: list[dict[str, Any]] = []
    for length, frame in records.groupby("length_m", sort=True):
        summaries.append(
            {
                "length_m": float(length),
                "count": int(len(frame)),
                "translation_error_percent": describe(frame["translation_error_percent"].to_numpy()),
                "translation_error_m": describe(frame["translation_error_m"].to_numpy()),
                "horizontal_translation_error_m": describe_clean(frame, "horizontal_translation_error_m"),
                "horizontal_translation_error_percent": describe_clean(frame, "horizontal_translation_error_percent"),
                "vertical_error_signed_m": describe_clean(frame, "vertical_error_signed_m"),
                "vertical_error_abs_m": describe_clean(frame, "vertical_error_abs_m"),
                "vertical_error_percent_of_length": describe_clean(frame, "vertical_error_percent_of_length"),
                "rotation_error_deg_per_m": describe_clean(frame, "rotation_error_deg_per_m"),
                "segment_yaw_error_signed_deg": describe_clean(frame, "segment_yaw_error_signed_deg"),
                "segment_yaw_error_abs_deg": describe_clean(frame, "segment_yaw_error_abs_deg"),
                "segment_yaw_error_deg_per_m": describe_clean(frame, "segment_yaw_error_deg_per_m"),
                "raw_scale_ratio_est_over_gt": describe_clean(frame, "raw_scale_ratio_est_over_gt"),
                "raw_scale_drift_percent": describe_clean(frame, "raw_scale_drift_percent"),
                "aligned_scale_ratio_est_over_gt": describe_clean(frame, "aligned_scale_ratio_est_over_gt"),
                "aligned_scale_drift_percent": describe_clean(frame, "aligned_scale_drift_percent"),
                "scale_ratio_est_over_gt": describe_clean(frame, "raw_scale_ratio_est_over_gt"),
                "scale_drift_percent": describe_clean(frame, "raw_scale_drift_percent"),
            }
        )
    return summaries


def describe_clean(frame: pd.DataFrame, column: str) -> dict[str, float | int] | None:
    """对 DataFrame 某列做 describe()，自动过滤 inf/nan 和缺失列。"""
    if column not in frame:
        return None
    values = frame[column].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    return describe(values)


def find_segment_end(cumulative: np.ndarray, start_idx: int, target_distance: float, max_diff: float) -> int:
    """为 KITTI/rpg 风格子轨迹寻找最接近目标长度的终点。

    代码意义：
    - cumulative 是 GT 累计路程。
    - 给定起点 start_idx 和目标路程 target_distance，找最接近的终点 j。
    - max_diff 控制实际长度和目标长度允许偏差，避免把 800m 段误当成 1000m 段。

    指标影响：
    - 如果找不到合格终点，该子轨迹样本会被跳过。
    - max_segment_length_diff_ratio 过严时，长距离子轨迹样本数可能变少。

    来源对应：
    - 按累计路程寻找固定长度子轨迹来自 Geiger12/KITTI odometry 评估思想。
    - 长度容差是工程扩展，避免无人机/稀疏轨迹采样时误把长度不合格的段纳入统计。
    """
    left = int(np.searchsorted(cumulative, target_distance, side="left"))
    candidates = [idx for idx in (left - 1, left, left + 1) if start_idx < idx < len(cumulative)]
    if not candidates:
        return -1
    best = min(candidates, key=lambda idx: abs(float(cumulative[idx] - target_distance)))
    if abs(float(cumulative[best] - target_distance)) > max_diff:
        return -1
    return best


def summarize_by_speed_bins(records: pd.DataFrame, bins: Iterable[float]) -> list[dict[str, Any]]:
    """速度分箱误差。

    segment_errors() 已经给每个子轨迹记录了 speed_mps，这里按速度区间聚合，
    用于观察高速/低速飞行时 VO 漂移是否不同。

    指标对应：
    - speed_bins[*].translation_error_percent: 不同速度下的平移漂移。
    - speed_bins[*].rotation_error_deg_per_m: 不同速度下的旋转漂移。

    解释方式：
    - 高速段误差高：常见原因是运动模糊、曝光、滚快门或特征跟踪跟不上。
    - 低速/悬停段误差高：常见原因是视差不足、弱纹理或初始化/尺度退化。

    来源对应：
    - 直接参考 Geiger12/KITTI 的 error-vs-speed 分析方式。
    - 无人机没有“车速”语义限制，所以这里用子轨迹平均速度 speed_mps 做泛化。
    """
    if records.empty or "speed_mps" not in records:
        return []
    clean = records.replace([np.inf, -np.inf], np.nan).dropna(subset=["speed_mps", "translation_error_percent"])
    if clean.empty:
        return []
    bin_values = list(bins)
    if len(bin_values) < 2:
        return []
    labels: list[str] = []
    for left, right in zip(bin_values[:-1], bin_values[1:]):
        right_label = "inf" if math.isinf(right) else f"{right:g}"
        labels.append(f"{left:g}-{right_label}")
    clean = clean.copy()
    # pd.cut 采用左闭右开区间 [left, right)，这样 5m/s 会进入 5-10 而不是 0-5。
    clean["speed_bin_mps"] = pd.cut(clean["speed_mps"], bins=bin_values, labels=labels, include_lowest=True, right=False)
    out: list[dict[str, Any]] = []
    for label, group in clean.groupby("speed_bin_mps", observed=True):
        out.append(
            {
                "speed_bin_mps": str(label),
                "count": int(len(group)),
                "translation_error_percent": describe(group["translation_error_percent"].to_numpy()),
                "rotation_error_deg_per_m": describe(group["rotation_error_deg_per_m"].dropna().to_numpy()),
            }
        )
    return out


def summarize_runtime(est: Trajectory, est_idx: np.ndarray) -> dict[str, Any] | None:
    """运行资源统计。

    如果 VO 输出 CSV 中包含 process_time_ms、fps、cpu_percent、memory_mb 等字段，
    这里会按匹配到的 VO 帧做 describe() 汇总，对应 report["runtime"]。

    代码意义：
    - runtime 字段不是轨迹格式必需字段，因此只在 extras 中存在时才统计。
    - est_idx 只取实际参与评估的 VO 帧，避免把未匹配的开机/落地前后日志纳入运行统计。

    指标解释：
    - process_time_ms / latency_ms 高：算法可能无法实时运行。
    - fps 低或波动大：长航程部署可能掉帧，进一步影响 VO 稳定性。
    - memory/cpu 高：边缘设备部署风险更高。

    来源对应：
    - Delmerico18 飞行机器人 VIO benchmark 明确把每帧处理时间、CPU、内存负载作为部署相关维度。
    - 这些字段不是 Sturm12/KITTI 的轨迹几何误差，但对物流无人机上线同样关键。
    """
    runtime_keys = {
        "process_time_ms",
        "processing_time_ms",
        "frame_time_ms",
        "latency_ms",
        "cpu_percent",
        "memory_percent",
        "memory_mb",
        "fps",
    }
    out: dict[str, Any] = {}
    for key, values in est.extras.items():
        if key not in runtime_keys:
            continue
        try:
            arr = np.asarray(values, dtype=float)[est_idx]
        except Exception:
            continue
        out[key] = describe(arr)
    return out or None


def detect_divergence(
    errors_m: np.ndarray,
    cumulative_m: np.ndarray,
    abs_threshold_m: float,
    rel_threshold_percent: float,
    stamps: np.ndarray,
    min_distance_m: float = 0.0,
    min_time_s: float = 0.0,
    discontinuities: dict[str, Any] | None = None,
    segment_summary: list[dict[str, Any]] | None = None,
    alignment: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """发散检测。

    阈值取 max(绝对阈值, 当前累计路程 * 相对阈值百分比)，
    第一个超过阈值的点就是页面提示的“首次发散”。

    指标对应：
    - divergence.diverged: 是否触发。
    - first_divergence_distance_m: 第一次触发时已经飞过的路程。
    - first_divergence_error_m: 第一次触发时的误差。
    - max_error_m/final_error_m: 最坏误差和终点误差。

    为什么同时用绝对阈值和相对阈值：
    - 起飞初期累计路程很短，只用相对阈值会过于严格。
    - 长航程后只用固定米级阈值又不能体现“误差占路程比例”。

    来源对应：
    - 这是工程扩展，5 篇论文没有统一发散阈值公式。
    - 设计动机来自 Schubert18/TUM VI 与 Delmerico18 对长序列 VIO 鲁棒性、跟踪失败和飞行可用性的关注。
    """
    if len(errors_m) == 0:
        return {"diverged": False, "metric_divergence": {"diverged": False}}
    # 动态阈值随路程增长；例如 2% 路程在 1000m 处就是 20m。
    dynamic_threshold = np.maximum(abs_threshold_m, cumulative_m * rel_threshold_percent / 100.0)
    elapsed = stamps - stamps[0] if len(stamps) else np.asarray([], dtype=float)
    valid = (cumulative_m >= min_distance_m) & (elapsed >= min_time_s)
    exceeded = np.flatnonzero(valid & (errors_m > dynamic_threshold))
    ignored_prefix = int(np.count_nonzero(~valid))
    metric_result: dict[str, Any] = {
        "diverged": bool(len(exceeded)),
        "abs_threshold_m": float(abs_threshold_m),
        "rel_threshold_percent": float(rel_threshold_percent),
        "min_distance_m": float(min_distance_m),
        "min_time_s": float(min_time_s),
        "ignored_prefix_samples": ignored_prefix,
        "max_error_m": float(np.nanmax(errors_m)),
        "final_error_m": float(errors_m[-1]),
    }
    if len(exceeded):
        idx = int(exceeded[0])
        metric_result.update(
            {
                "first_divergence_index": idx,
                "first_divergence_time_s": float(stamps[idx]),
                "first_divergence_distance_m": float(cumulative_m[idx]),
                "first_divergence_error_m": float(errors_m[idx]),
                "threshold_at_divergence_m": float(dynamic_threshold[idx]),
            }
        )
    tracking_result = classify_tracking_failure(discontinuities)
    scale_result = classify_scale_divergence(segment_summary or [], alignment or {}, summary or {})
    return {
        **metric_result,
        "tracking_failure": tracking_result,
        "metric_divergence": metric_result,
        "scale_divergence": scale_result,
        "diverged": bool(metric_result["diverged"] or tracking_result["diverged"] or scale_result["diverged"]),
    }


def classify_tracking_failure(discontinuities: dict[str, Any] | None) -> dict[str, Any]:
    """基于断点和时间 gap 判断是否存在跟踪连续性问题。"""
    if not discontinuities:
        return {"diverged": False, "break_count": 0}
    breaks = discontinuities.get("breaks") or []
    max_gap = max((float(item.get("time_gap_s", 0.0)) for item in breaks), default=0.0)
    return {
        "diverged": bool(discontinuities.get("break_count", 0) > 0),
        "break_count": int(discontinuities.get("break_count", 0)),
        "max_time_gap_s": float(max_gap),
        "reason": "VO reset/gap detected" if discontinuities.get("break_count", 0) > 0 else "no break detected",
    }


def classify_scale_divergence(
    segment_summary: list[dict[str, Any]],
    alignment: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """基于 raw scale、分段 scale 和 Sim3 scale 范围判断尺度是否失控。"""
    raw_ratio = float(summary.get("raw_path_scale_ratio_est_over_gt", math.nan))
    raw_ratio_bad = math.isfinite(raw_ratio) and (raw_ratio < 0.8 or raw_ratio > 1.25)
    scale = float(alignment.get("scale", math.nan))
    scale_min = float(alignment.get("scale_min", math.nan))
    scale_max = float(alignment.get("scale_max", math.nan))
    sim3_range_percent = math.nan
    if math.isfinite(scale) and scale != 0 and math.isfinite(scale_min) and math.isfinite(scale_max):
        sim3_range_percent = 100.0 * (scale_max - scale_min) / abs(scale)
    worst_raw_drift = max(
        (
            abs(float((row.get("raw_scale_drift_percent") or {}).get("p95", math.nan)))
            for row in segment_summary
            if row.get("raw_scale_drift_percent") is not None
        ),
        default=math.nan,
    )
    raw_drift_bad = math.isfinite(worst_raw_drift) and worst_raw_drift > 20.0
    sim3_range_bad = math.isfinite(sim3_range_percent) and sim3_range_percent > 15.0
    return {
        "diverged": bool(raw_ratio_bad or raw_drift_bad or sim3_range_bad),
        "raw_path_scale_ratio_est_over_gt": raw_ratio,
        "sim3_scale_range_percent": sim3_range_percent,
        "worst_raw_scale_drift_p95_percent": worst_raw_drift,
        "raw_path_ratio_flag": bool(raw_ratio_bad),
        "raw_segment_drift_flag": bool(raw_drift_bad),
        "sim3_segment_scale_flag": bool(sim3_range_bad),
    }


def detect_associated_discontinuities(
    stamps: np.ndarray,
    gt_pos: np.ndarray,
    est_pos: np.ndarray,
    step_threshold_m: float,
    time_gap_threshold_s: float,
) -> dict[str, Any]:
    """断点/重置诊断。

    根据 GT 步长、VO 步长、时间间隔判断是否存在大跳变。
    默认评估策略不会丢弃这些点，只把信息放入 report["discontinuities"] 供诊断。

    断点来源：
    - gt_step: GT 自己相邻点跳得很远，可能是 GT 数据中断或坐标跳变。
    - est_step: VO 相邻点跳得很远，可能是 VO 重置、丢跟踪后重新初始化。
    - time_gap: 相邻评估时间差很大，可能是日志中断或算法停顿。

    指标/页面影响：
    - break_count > 0 会触发“检测到 VO 重置或大跳变”提示。
    - segment_ids 会写入 per_pose，让可视化在断点处断开，不错误连线。

    来源对应：
    - 这是工程扩展，5 篇论文没有把“VO 重置断点”定义成标准数值指标。
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
    break_after = np.zeros(n - 1, dtype=bool)
    breaks: list[dict[str, Any]] = []
    for idx, (gt_step, est_step, time_gap) in enumerate(zip(gt_steps, est_steps, time_gaps)):
        reasons: list[str] = []
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


def summarize_continuity(
    discontinuities: dict[str, Any],
    stamps: np.ndarray,
    gt_pos: np.ndarray,
    total_gt_path_m: float,
) -> dict[str, Any]:
    """连续性 summary：长航程调参优先看断点、最长连续段和 reset/km。"""
    segments = discontinuities.get("segments") or []
    if not len(stamps) or not segments:
        return {
            "longest_continuous_segment_m": 0.0,
            "longest_continuous_segment_s": 0.0,
            "longest_continuous_segment_pose_count": 0,
            "reset_rate_per_km": math.nan,
            "reset_rate_per_hour": math.nan,
            "coverage_time_ratio": 0.0,
            "coverage_distance_ratio": 0.0,
        }
    cumulative = path_distance(gt_pos)
    segment_infos: list[dict[str, Any]] = []
    for seg in segments:
        start = int(seg["start"])
        end = int(seg["end"])
        if end <= start:
            continue
        distance_m = float(cumulative[end - 1] - cumulative[start]) if end - 1 < len(cumulative) else 0.0
        duration_s = float(stamps[end - 1] - stamps[start]) if end - 1 < len(stamps) else 0.0
        info = {
            "start_index": start,
            "end_index": end,
            "pose_count": int(end - start),
            "distance_m": distance_m,
            "duration_s": duration_s,
        }
        segment_infos.append(info)
    longest = max(segment_infos, key=lambda item: item["distance_m"], default={"distance_m": 0.0, "duration_s": 0.0, "pose_count": 0})
    total_duration_h = (float(stamps[-1] - stamps[0]) / 3600.0) if len(stamps) > 1 else 0.0
    break_count = int(discontinuities.get("break_count", 0))
    total_distance_km = total_gt_path_m / 1000.0 if total_gt_path_m > 0 else 0.0
    return {
        "longest_continuous_segment_m": float(longest["distance_m"]),
        "longest_continuous_segment_s": float(longest["duration_s"]),
        "longest_continuous_segment_pose_count": int(longest["pose_count"]),
        "reset_rate_per_km": float(break_count / total_distance_km) if total_distance_km > 0 else math.nan,
        "reset_rate_per_hour": float(break_count / total_duration_h) if total_duration_h > 0 else math.nan,
        "coverage_time_ratio": float(sum(item["duration_s"] for item in segment_infos) / (stamps[-1] - stamps[0])) if len(stamps) > 1 and stamps[-1] > stamps[0] else 1.0,
        "coverage_distance_ratio": float(sum(item["distance_m"] for item in segment_infos) / total_gt_path_m) if total_gt_path_m > 0 else 1.0,
        "segments": segment_infos,
    }


def build_worst_segments(records: pd.DataFrame, discontinuities: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    """按 translation_error_percent 排序，输出最差子轨迹定位表。"""
    if records.empty or top_k <= 0 or "translation_error_percent" not in records:
        return []
    clean = records.replace([np.inf, -np.inf], np.nan).dropna(subset=["translation_error_percent"]).copy()
    if clean.empty:
        return []
    clean = clean.sort_values("translation_error_percent", ascending=False).head(int(top_k))
    break_indices = [int(item.get("after_index", -10_000)) for item in discontinuities.get("breaks", [])]
    out: list[dict[str, Any]] = []
    for rank, (_, row) in enumerate(clean.iterrows(), start=1):
        start_idx = int(row.get("global_start_match_index", row.get("start_index", -1)))
        end_idx = int(row.get("global_end_match_index", row.get("end_index", -1)))
        near_break = any((start_idx - 10) <= idx <= (end_idx + 10) for idx in break_indices)
        out.append(
            {
                "rank": rank,
                "length_m": float(row.get("length_m", math.nan)),
                "start_time_s": float(row.get("start_time_s", math.nan)),
                "end_time_s": float(row.get("end_time_s", math.nan)),
                "duration_s": float(row.get("duration_s", math.nan)),
                "start_distance_m": float(row.get("start_distance_m", math.nan)),
                "end_distance_m": float(row.get("end_distance_m", math.nan)),
                "translation_error_percent": float(row.get("translation_error_percent", math.nan)),
                "translation_error_m": float(row.get("translation_error_m", math.nan)),
                "yaw_error_abs_deg": float(row.get("segment_yaw_error_abs_deg", math.nan)),
                "vertical_error_abs_m": float(row.get("vertical_error_abs_m", math.nan)),
                "speed_mps": float(row.get("speed_mps", math.nan)),
                "near_break": bool(near_break),
                "segment_id": int(row.get("segment_id", -1)),
                "start_index": start_idx,
                "end_index": end_idx,
            }
        )
    return out


def select_evaluation_segments(segments: list[dict[str, int]], policy: str, total_count: int) -> list[dict[str, int]]:
    """根据断点策略选择实际参与误差计算的连续段。

    三种策略：
    - vo_timestamps/all: 默认策略。保留所有 VO 时间戳统一评估，断点只作为诊断提示。
    - segments: 按检测出的连续段逐段评估，每段单独对齐，适合 VO 重置后局部坐标系变化的情况。
    - longest: 只评估最长连续段，适合想排除重置前后不连续影响的情况。

    指标影响：
    - 这里决定 used_gt_idx/used_est_idx，进而影响 ATE、RPE、segment_errors、speed_bins 和 summary coverage。
    - dropped_matches 会告诉用户断点策略丢掉了多少匹配点。

    来源对应：
    - all/segments/longest 是工程策略，不是论文标准公式。
    - 这些策略用于在 Schubert18/Delmerico18 关注的长序列、可能丢跟踪场景里解释指标。
    """
    valid_segments = [seg for seg in segments if int(seg.get("count", 0)) >= 2]
    if policy in {"vo_timestamps", "all"}:
        return [{"start": 0, "end": int(total_count), "count": int(total_count)}] if total_count >= 2 else []
    if policy == "segments":
        return valid_segments
    if policy == "longest":
        if not valid_segments:
            return []
        start, end = longest_segment_bounds(valid_segments)
        return [{"start": start, "end": end, "count": end - start}]
    raise ValueError(f"Unknown continuous_segment_policy: {policy}")


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


def longest_segment_bounds(segments: list[dict[str, int]]) -> tuple[int, int]:
    """返回最长连续段的起止索引。"""
    if not segments:
        return 0, 0
    best = max(segments, key=lambda seg: seg["count"])
    return int(best["start"]), int(best["end"])


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


def relative_pose(r_i: np.ndarray, p_i: np.ndarray, r_j: np.ndarray, p_j: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """计算从第 i 帧到第 j 帧的相对位姿。

    r_rel = R_i^T R_j，p_rel = R_i^T (p_j - p_i)。
    这个局部坐标系表达会被 relative_error() 用来比较 GT 和 VO 的相对运动。
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
    - 用户的 imu.txt/vo.txt 可能只给 yaw/pitch/roll，而不是四元数。
    - 单位已经在 _angle_unit_for_columns() 中统一成弧度。

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

    主要用于姿态插值：interpolate_rotations() 先把矩阵转四元数，再做 SLERP。
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

    原始输入、插值后 GT、筛选后 VO 和 Sim3 输出都通过这个函数统一导出，
    避免不同 sheet 的列顺序或四元数顺序不一致。
    """
    return tum_dataframe_from_arrays(traj.stamps, traj.positions, traj.rotations, extra=extra)


def raw_numeric_table(traj: Trajectory) -> np.ndarray | None:
    """取解析阶段保留的原始数字表，用于检测 VO 倒数第四列跳变。"""
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
    """根据原始 VO 倒数第四列的 +1 变化生成导出分段列。

    用户要求：如果 VO 输出文件倒数第四列出现 0->1、1->2 这类 +1 跳变，
    就把跳变后的数据视为新的 TUM 文件，例如 vo_tum_01、vo_tum_02。

    Excel 只有 6 个固定 sheet，因此这里不额外创建无限多个 sheet，而是在相关 sheet 中写入：
    - tum_file: 逻辑文件名，如 vo_tum_01。
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

    rpe_delta_unit 支持 frames/f 和 meters/m 两类：
    - frames: 终点固定为 j=i+N。
    - meters: 终点从 GT 累计路程的 target*(1±tolerance) 范围内选择。

    rpe_delta_value 是新参数；如果为空则退回旧的 rpe_delta_frames，保证旧配置还能复现。
    """
    unit_raw = str(cfg.rpe_delta_unit or "frames").strip().lower()
    if unit_raw in {"f", "frame", "frames"}:
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
    if unit_raw in {"m", "meter", "meters"}:
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
    if unit_raw in {"f", "frame", "frames"}:
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
    if unit_raw in {"m", "meter", "meters"}:
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
    if unit_raw in {"f", "frame", "frames"}:
        unit = "frames"
    elif unit_raw in {"m", "meter", "meters"}:
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

    注意这里使用未对齐的 VO 位置 est_pos_raw。否则 Sim3 对齐后的轨迹已经被整体缩放，
    会掩盖原始 VO 的局部尺度变化。
    """
    stamps = np.asarray(stamps, dtype=float)
    match_indices = np.asarray(match_indices, dtype=int)
    n = len(stamps)
    unit_raw = str(delta_unit or "frames").strip().lower()
    if unit_raw in {"f", "frame", "frames"}:
        unit = "frames"
    elif unit_raw in {"m", "meter", "meters"}:
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
    2. input_vo_tum: 原始 VO 转 TUM，并按倒数第四列 +1 跳变标记 vo_tum_XX。
    3. filtered_vo_tum: 时间同步后保留下来的 VO。
    4. interpolated_gt_tum: 插值到 VO 时间戳后的 GT。
    5. sim3_gt_tum: Sim3 评估时使用的 GT。
    6. sim3_vo_tum: Sim3 对齐后的 VO。
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


def _jsonable_dict(data: dict[str, Any]) -> dict[str, Any]:
    """兼容旧调用的 dict 转 JSON 工具。"""
    return _jsonable_value(data)


def _jsonable_value(value: Any) -> Any:
    """把 report 递归转成标准 JSON 值。

    代码意义：
    - DataFrame -> records list，供 per_pose/segment_records 导出。
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
        "profile": cfg.profile,
        "alignment": cfg.alignment,
        "orientation_correction": cfg.orientation_correction,
        "association_mode": cfg.association_mode,
        "max_time_diff_s": cfg.max_time_diff_s,
        "max_interpolation_gap_s": cfg.max_interpolation_gap_s,
        "allow_extrapolation": cfg.allow_extrapolation,
        "interpolate_rotation": cfg.interpolate_rotation,
        "interpolation_position_method": cfg.interpolation_position_method,
        "interpolation_rotation_method": cfg.interpolation_rotation_method,
        "time_offset_s": cfg.time_offset_s,
        "rpe_delta_frames": cfg.rpe_delta_frames,
        "rpe_delta_value": cfg.rpe_delta_value,
        "rpe_delta_unit": cfg.rpe_delta_unit,
        "rpe_distance_tolerance_ratio": cfg.rpe_distance_tolerance_ratio,
        "scale_delta_value": cfg.scale_delta_value,
        "scale_delta_unit": cfg.scale_delta_unit,
        "scale_distance_tolerance_ratio": cfg.scale_distance_tolerance_ratio,
        "rpe_delta_seconds": list(cfg.rpe_delta_seconds),
        "segment_lengths_m": list(cfg.segment_lengths_m),
        "max_segments_per_length": cfg.max_segments_per_length,
        "segment_step_frames": cfg.segment_step_frames,
        "max_segment_length_diff_ratio": cfg.max_segment_length_diff_ratio,
        "continuous_segment_policy": cfg.continuous_segment_policy,
        "discontinuity_step_m": cfg.discontinuity_step_m,
        "discontinuity_time_gap_s": cfg.discontinuity_time_gap_s,
        "divergence_abs_m": cfg.divergence_abs_m,
        "divergence_rel_percent": cfg.divergence_rel_percent,
        "divergence_min_distance_m": cfg.divergence_min_distance_m,
        "divergence_min_time_s": cfg.divergence_min_time_s,
        "speed_bins_mps": list(cfg.speed_bins_mps),
        "top_k_worst_segments": cfg.top_k_worst_segments,
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


def _detect_format(lines: list[str]) -> str:
    """根据第一行内容粗略识别无表头轨迹格式。

    规则：
    - 含字母/下划线：认为是 CSV 表头。
    - 12 列数字：KITTI 3x4 pose。
    - 8 列数字：TUM timestamp tx ty tz qx qy qz qw。
    - 3/4 列数字：XYZ 或 timestamp XYZ。

    只用第一行是为了快速分发；真正的宽度一致性和字段校验在后续 parser 中完成。
    """
    first = lines[0]
    if re.search(r"[A-Za-z_]", first):
        return "csv"
    values = _parse_float_line(first)
    if len(values) == 12:
        return "kitti"
    if len(values) == 8:
        return "tum"
    if len(values) in {3, 4}:
        return "xyz"
    return "csv"


def _parse_float_line(line: str) -> list[float]:
    """解析一行纯数字，支持空格、逗号和分号分隔。"""
    tokens = re.split(r"[\s,;]+", line.strip())
    values = []
    for token in tokens:
        if not token:
            continue
        values.append(float(token))
    return values


def _parse_numeric_table(lines: list[str], name: str, fmt: str) -> Trajectory:
    """解析无表头数字表。

    TUM: timestamp tx ty tz qx qy qz qw。
    KITTI: 每行 12 个数，表示 3x4 pose matrix。
    XYZ: x y z 或 timestamp x y z。
    TUM/XYZ 的 timestamp 会调用 _normalize_timestamps()，避免 ns 被当成秒。
    """
    rows = [_parse_float_line(line) for line in lines]
    width = max(len(row) for row in rows)
    if any(len(row) != width for row in rows):
        raise ValueError(f"{name}: inconsistent number of columns")
    data = np.asarray(rows, dtype=float)
    if fmt == "tum":
        # TUM 口径保留论文/开源工具常用格式，姿态直接由四元数转矩阵。
        if data.shape[1] < 8:
            raise ValueError(f"{name}: TUM format needs at least 8 columns")
        stamps = _normalize_timestamps(data[:, 0])
        positions = data[:, 1:4]
        rotations = quaternion_to_matrix(data[:, 4], data[:, 5], data[:, 6], data[:, 7])
        return Trajectory(name, stamps, positions, rotations, extras={"raw_numeric_table": data}, source_format="tum")
    if fmt == "kitti":
        # KITTI odometry 文件通常没有时间戳；这里用行号当时间，适合按 index 或固定帧间隔评估。
        if data.shape[1] != 12:
            raise ValueError(f"{name}: KITTI format needs exactly 12 columns")
        mats = data.reshape((-1, 3, 4))
        rotations = mats[:, :, :3]
        positions = mats[:, :, 3]
        stamps = np.arange(len(positions), dtype=float)
        return Trajectory(name, stamps, positions, rotations, extras={"raw_numeric_table": data}, source_format="kitti")
    if fmt == "xyz":
        # XYZ 只支持位置指标；没有姿态时 rotation RPE/姿态 ATE 不会生成。
        if data.shape[1] == 3:
            stamps = np.arange(len(data), dtype=float)
            positions = data[:, 0:3]
        elif data.shape[1] >= 4:
            stamps = _normalize_timestamps(data[:, 0])
            positions = data[:, 1:4]
        else:
            raise ValueError(f"{name}: XYZ format needs 3 or 4 columns")
    return Trajectory(name, stamps, positions, None, extras={"raw_numeric_table": data}, source_format="xyz")
    raise ValueError(fmt)


SF_EXTRA_CANONICAL = {
    "status": "status",
    "flightmode": "flight_mode",
    "vx": "vx",
    "vy": "vy",
    "vz": "vz",
    "resetcount1": "reset_count1",
    "resetcount2": "reset_count2",
    "resetcount3": "reset_count3",
    "lati": "lati",
    "longi": "longi",
    "alti": "alti",
    "altimsl": "alti_msl",
    "height": "height",
    "numinliers": "num_inliers",
    "iskeyframe": "is_keyframe",
    "framecost": "frame_cost",
    "resetcount": "reset_count",
    "depthmean": "depth_mean",
    "depthmin": "depth_min",
    "depthmax": "depth_max",
}


VLOC_EXTRA_CANONICAL = {
    "status": "status",
    "numinliers": "num_inliers",
    "resetcount": "reset_count",
    "latitude": "latitude",
    "longitude": "longitude",
    "altitude": "altitude",
}


def _parse_sf(text: str, name: str) -> Trajectory:
    """解析 SF 项目格式。

    支持两种表头：
    - GT: #ts1 ts2 status flight_mode x y z yaw pitch roll vx vy vz reset_count1 ...
    - VO: # ts num_inliers tx ty tz yaw pitch roll(degree) is_keyframe ...

    解析规则：
    - GT 位置固定读取 x/y/z；VO 位置固定读取 tx/ty/tz。
    - yaw/pitch/roll 固定按角度制读取，再转成内部统一的弧度旋转矩阵。
    - GT 同时有 ts1/ts2 时优先把 ts2 当作与 VO 对齐的秒级时间戳；如果 ts2 不像独立时间轴，
      则退回 ts1 + ts2 的秒/纳秒组合。
    - reset、速度、深度等不参与几何误差，但会放入 extras 供导出和诊断使用。
    """
    frame = _read_dataframe(text)
    if frame.empty:
        raise ValueError(f"{name}: empty SF trajectory")
    normalized = {_normalize_col(col): col for col in frame.columns}
    numeric = frame.apply(pd.to_numeric, errors="coerce")

    sf_kind = _detect_sf_kind_from_columns(normalized)
    if sf_kind == "gt":
        stamps = _sf_gt_stamps(numeric, normalized)
        position_cols = [_required_col(normalized, col, name, "SF GT") for col in ["x", "y", "z"]]
        source_format = "sf_gt"
    elif sf_kind == "vo":
        ts_col = _required_col(normalized, "ts", name, "SF VO")
        stamps = _normalize_timestamps(numeric[ts_col].to_numpy(dtype=float), _timestamp_unit_hint(text, str(ts_col)))
        position_cols = [_required_col(normalized, col, name, "SF VO") for col in ["tx", "ty", "tz"]]
        source_format = "sf_vo"
    else:
        raise ValueError(f"{name}: SF format needs either GT or VO SF header columns")

    positions = numeric[position_cols].to_numpy(dtype=float)
    yaw_col = _required_col(normalized, "yaw", name, "SF")
    pitch_col = _required_col(normalized, "pitch", name, "SF")
    roll_col = _required_col(normalized, "roll", name, "SF")
    angles = numeric[[yaw_col, pitch_col, roll_col]].to_numpy(dtype=float)
    unit = _angle_unit_for_columns([yaw_col, pitch_col, roll_col], frame.attrs.get("angle_unit"), angles)
    if unit == "deg":
        angles = np.deg2rad(angles)
    rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])

    valid = np.isfinite(stamps) & np.isfinite(positions).all(axis=1)
    valid &= np.isfinite(rotations.reshape(len(rotations), -1)).all(axis=1)
    stamps = stamps[valid]
    positions = positions[valid]
    rotations = rotations[valid]

    extras: dict[str, np.ndarray] = {"raw_numeric_table": numeric.to_numpy(dtype=float)[valid]}
    for norm_name, col in normalized.items():
        canonical = SF_EXTRA_CANONICAL.get(norm_name)
        if canonical is not None:
            extras[canonical] = numeric[col].to_numpy(dtype=float)[valid]

    return Trajectory(name, stamps, positions, rotations, extras=extras, source_format=source_format)


def _parse_vloc(text: str, name: str) -> Trajectory:
    """解析 VLOC VO 输出格式。

    表头：
    ts status num_inliers reset_count tx ty tz yaw pitch roll latitude longitude altitude

    解析规则：
    - ts 是秒级或可由 _normalize_timestamps() 推断的时间戳。
    - tx/ty 是 VO 水平位置。
    - 如果 latitude/longitude/altitude 中存在有效 GPS 高度，则使用 -altitude 作为 z。
      这和当前 SF IMU 的 z 轴方向一致；lat/lon/alt 为 0 的初始化/无效定位行会被过滤。
    - 如果整份 VLOC 没有有效 GPS 高度，则退回旧行为，使用 tx/ty/tz。
    - yaw/pitch/roll 按角度制读取，再转成内部统一的旋转矩阵。
    - status、num_inliers、reset_count、latitude/longitude/altitude 存入 extras 供导出和诊断。
    """
    frame = _read_dataframe(text)
    if frame.empty:
        raise ValueError(f"{name}: empty VLOC trajectory")
    normalized = {_normalize_col(col): col for col in frame.columns}
    if not _is_vloc_columns(normalized):
        raise ValueError(f"{name}: VLOC format needs ts/status/num_inliers/reset_count/tx/ty/tz/yaw/pitch/roll/latitude/longitude/altitude")
    numeric = frame.apply(pd.to_numeric, errors="coerce")

    ts_col = _required_col(normalized, "ts", name, "VLOC")
    stamps = _normalize_timestamps(numeric[ts_col].to_numpy(dtype=float), _timestamp_unit_hint(text, str(ts_col)))
    tx_col = _required_col(normalized, "tx", name, "VLOC")
    ty_col = _required_col(normalized, "ty", name, "VLOC")
    tz_col = _required_col(normalized, "tz", name, "VLOC")
    positions = numeric[[tx_col, ty_col, tz_col]].to_numpy(dtype=float)

    # VLOC 日志里同时有 tx/ty/tz 和 latitude/longitude/altitude。
    # 当前 2839_traj 数据的 MATLAB 对比图使用的是 tx、ty、-altitude：
    #   - tx/ty 与 IMU x/y 同坐标系；
    #   - altitude 为向上为正，高度方向和 IMU z 相反，因此写入 z 时取负；
    #   - latitude/longitude/altitude 为 0 的行是初始化或无效定位输出，不应纳入轨迹评估。
    # 为了不破坏没有 GPS 高度的 VLOC 文件，只有当文件中确实存在足够的有效经纬高行时才启用该规则。
    lat_col = _required_col(normalized, "latitude", name, "VLOC")
    lon_col = _required_col(normalized, "longitude", name, "VLOC")
    alt_col = _required_col(normalized, "altitude", name, "VLOC")
    lat_values = numeric[lat_col].to_numpy(dtype=float)
    lon_values = numeric[lon_col].to_numpy(dtype=float)
    alt_values = numeric[alt_col].to_numpy(dtype=float)
    gps_height_valid = (
        np.isfinite(lat_values)
        & np.isfinite(lon_values)
        & np.isfinite(alt_values)
        & (np.abs(lat_values) > 1e-9)
        & (np.abs(lon_values) > 1e-9)
        & (np.abs(alt_values) > 1e-9)
    )
    use_gps_height = int(np.count_nonzero(gps_height_valid)) >= 2
    if use_gps_height:
        positions[:, 2] = -alt_values

    yaw_col = _required_col(normalized, "yaw", name, "VLOC")
    pitch_col = _required_col(normalized, "pitch", name, "VLOC")
    roll_col = _required_col(normalized, "roll", name, "VLOC")
    angles = numeric[[yaw_col, pitch_col, roll_col]].to_numpy(dtype=float)
    unit = _angle_unit_for_columns([yaw_col, pitch_col, roll_col], frame.attrs.get("angle_unit"), angles)
    if unit == "deg":
        angles = np.deg2rad(angles)
    rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])

    valid = np.isfinite(stamps) & np.isfinite(positions).all(axis=1)
    if use_gps_height:
        valid &= gps_height_valid
    valid &= np.isfinite(rotations.reshape(len(rotations), -1)).all(axis=1)
    stamps = stamps[valid]
    positions = positions[valid]
    rotations = rotations[valid]

    extras: dict[str, np.ndarray] = {"raw_numeric_table": numeric.to_numpy(dtype=float)[valid]}
    for norm_name, col in normalized.items():
        canonical = VLOC_EXTRA_CANONICAL.get(norm_name)
        if canonical is not None:
            extras[canonical] = numeric[col].to_numpy(dtype=float)[valid]

    return Trajectory(name, stamps, positions, rotations, extras=extras, source_format="vloc")


def _detect_sf_kind_from_columns(normalized: dict[str, Any]) -> str | None:
    """根据归一化列名判断 SF 表头属于 GT 还是 VO。"""
    keys = set(normalized)
    has_gt_pose = {"ts1", "ts2", "x", "y", "z", "yaw", "pitch", "roll"}.issubset(keys)
    has_gt_marker = bool({"flightmode", "resetcount1", "lati", "longi"} & keys)
    if has_gt_pose and has_gt_marker:
        return "gt"
    has_vo_pose = {"ts", "tx", "ty", "tz", "yaw", "pitch", "roll"}.issubset(keys)
    has_vo_marker = bool({"iskeyframe", "framecost", "depthmean", "depthmin", "depthmax"} & keys)
    if has_vo_pose and has_vo_marker:
        return "vo"
    return None


def _is_vloc_columns(normalized: dict[str, Any]) -> bool:
    """判断表头是否满足 VLOC VO 输出格式。"""
    keys = set(normalized)
    return {
        "ts",
        "status",
        "numinliers",
        "resetcount",
        "tx",
        "ty",
        "tz",
        "yaw",
        "pitch",
        "roll",
        "latitude",
        "longitude",
        "altitude",
    }.issubset(keys)


def _sf_gt_stamps(numeric: pd.DataFrame, normalized: dict[str, Any]) -> np.ndarray:
    """读取 SF GT 时间戳。

    ts2 在用户数据中通常是与 VO 对齐的秒级时间轴，因此优先使用；
    如果 ts2 像纳秒/微秒余量，则使用 ts1 + ts2 组合，兼容 sec/nsec 拆分式日志。
    """
    ts1_col = _required_col(normalized, "ts1", "SF GT", "SF GT")
    ts2_col = _required_col(normalized, "ts2", "SF GT", "SF GT")
    ts1 = numeric[ts1_col].to_numpy(dtype=float)
    ts2 = numeric[ts2_col].to_numpy(dtype=float)

    finite_ts2 = ts2[np.isfinite(ts2)]
    if len(finite_ts2):
        ts2_duration = float(np.nanmax(finite_ts2) - np.nanmin(finite_ts2))
        ts2_has_fraction = bool(np.any(np.abs(finite_ts2 - np.round(finite_ts2)) > 1e-9))
        ts2_median_abs = float(np.nanmedian(np.abs(finite_ts2)))
        if ts2_duration > 0 and (ts2_has_fraction or ts2_median_abs < 1e6):
            return _normalize_timestamps(ts2, "s")

    ts1_seconds = _normalize_timestamps(ts1)
    ts2_seconds = _normalize_timestamps(ts2)
    return ts1_seconds + ts2_seconds


def _required_col(normalized: dict[str, Any], name: str, trajectory_name: str, fmt_name: str) -> Any:
    """按归一化列名取必需列，缺失时给出清晰错误。"""
    col = _pick(normalized, [name])
    if col is None:
        raise ValueError(f"{trajectory_name}: {fmt_name} format needs column {name}")
    return col


def _parse_csv(text: str, name: str) -> Trajectory:
    """解析 CSV/TSV/空格表/注释表头。

    这里做三件事：
    1. 自动识别 time/x/y/z 列，兼容 EuRoC 的 p_RS_R_x/y/z。
    2. 自动识别四元数 qx/qy/qz/qw 或 yaw/pitch/roll。
    3. 抽取 runtime extras，供 summarize_runtime() 统计。
    """
    frame = _read_dataframe(text)
    if frame.empty:
        raise ValueError(f"{name}: empty CSV")
    angle_unit_hint = frame.attrs.get("angle_unit")
    timestamp_unit_hint = frame.attrs.get("timestamp_unit")
    normalized = {_normalize_col(col): col for col in frame.columns}
    numeric = frame.apply(pd.to_numeric, errors="coerce")

    time_col = _pick(normalized, TIME_COLUMN_CANDIDATES)
    x_col = _pick(normalized, X_COLUMN_CANDIDATES)
    y_col = _pick(normalized, Y_COLUMN_CANDIDATES)
    z_col = _pick(normalized, Z_COLUMN_CANDIDATES)

    if x_col is None or y_col is None or z_col is None:
        # 没有可靠列名时，退回到数字表解析，尽量支持老式无表头日志。
        # 这个 fallback 仍然只读取轨迹需要的数据列，不会要求用户改原始文件。
        numeric_values = numeric.dropna(axis=1, how="all").to_numpy(dtype=float)
        numeric_values = numeric_values[~np.isnan(numeric_values).all(axis=1)]
        if numeric_values.shape[1] == 12:
            return _parse_numeric_table([" ".join(map(str, row)) for row in numeric_values], name, "kitti")
        if numeric_values.shape[1] >= 8:
            return _parse_numeric_table([" ".join(map(str, row[:8])) for row in numeric_values], name, "tum")
        if numeric_values.shape[1] >= 3:
            return _parse_numeric_table([" ".join(map(str, row[:4])) for row in numeric_values], name, "xyz")
        raise ValueError(f"{name}: could not detect x/y/z columns")

    positions = numeric[[x_col, y_col, z_col]].to_numpy(dtype=float)
    if time_col is not None:
        # 所有时间戳在进入 Trajectory 前统一转成秒；
        # EuRoC 的 timestamp [ns] 和无表头 ns 时间戳都在这里处理。
        stamps = _normalize_timestamps(
            numeric[time_col].to_numpy(dtype=float),
            timestamp_unit_hint or _timestamp_unit_hint("", str(time_col)),
        )
    else:
        stamps = np.arange(len(frame), dtype=float)

    qx_col = _pick(normalized, QX_COLUMN_CANDIDATES)
    qy_col = _pick(normalized, QY_COLUMN_CANDIDATES)
    qz_col = _pick(normalized, QZ_COLUMN_CANDIDATES)
    qw_col = _pick(normalized, QW_COLUMN_CANDIDATES)
    rotations = None
    if all(col is not None for col in [qx_col, qy_col, qz_col, qw_col]):
        # 四元数优先级最高，因为它比欧拉角少一个顺序歧义。
        rotations = quaternion_to_matrix(
            numeric[qx_col].to_numpy(dtype=float),
            numeric[qy_col].to_numpy(dtype=float),
            numeric[qz_col].to_numpy(dtype=float),
            numeric[qw_col].to_numpy(dtype=float),
        )
    else:
        matrix_cols = [_pick(normalized, [f"r{i}{j}", f"rot{i}{j}", f"rotation{i}{j}"]) for i in range(3) for j in range(3)]
        if all(col is not None for col in matrix_cols):
            # 如果日志直接给旋转矩阵，就按行展开的 r00...r22 读取。
            rotations = numeric[matrix_cols].to_numpy(dtype=float).reshape((-1, 3, 3))
        else:
            yaw_col = _pick_angle_col(normalized, "yaw", ["heading", "psi"])
            pitch_col = _pick_angle_col(normalized, "pitch", ["theta"])
            roll_col = _pick_angle_col(normalized, "roll", ["row", "phi"])
            if yaw_col is not None and pitch_col is not None and roll_col is not None:
                angles = numeric[[yaw_col, pitch_col, roll_col]].to_numpy(dtype=float)
                # 自动识别角度/弧度，兼容用户 IMU/VO 表头单位不同的情况。
                unit = _angle_unit_for_columns([yaw_col, pitch_col, roll_col], angle_unit_hint, angles)
                if unit == "deg":
                    angles = np.deg2rad(angles)
                rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])

    valid = np.isfinite(stamps) & np.isfinite(positions).all(axis=1)
    if rotations is not None:
        valid &= np.isfinite(rotations.reshape(len(rotations), -1)).all(axis=1)
    # 只保留轨迹计算所需字段都有效的行；原文件不改动，坏行只是不进入统计。
    stamps = stamps[valid]
    positions = positions[valid]
    if rotations is not None:
        rotations = rotations[valid]

    extras: dict[str, np.ndarray] = {}
    extras["raw_numeric_table"] = numeric.to_numpy(dtype=float)[valid]
    for col in frame.columns:
        key = _normalize_col(col)
        # extras 只收集 runtime/资源字段，不参与轨迹几何计算。
        if key in {
            "processtimems",
            "processingtimems",
            "frametimems",
            "latencyms",
            "cpupercent",
            "memorypercent",
            "memorymb",
            "fps",
        }:
            canonical = {
                "processtimems": "process_time_ms",
                "processingtimems": "processing_time_ms",
                "frametimems": "frame_time_ms",
                "latencyms": "latency_ms",
                "cpupercent": "cpu_percent",
                "memorypercent": "memory_percent",
                "memorymb": "memory_mb",
                "fps": "fps",
            }[key]
            extras[canonical] = numeric[col].to_numpy(dtype=float)[valid]

    return Trajectory(name, stamps, positions, rotations, extras=extras, source_format="csv")


def _read_dataframe(text: str) -> pd.DataFrame:
    """把文本读取为 DataFrame。

    优先处理 # 开头的注释表头，例如 "# ts x y z yaw pitch roll ..."；
    否则交给 pandas 尝试自动分隔符、空格分隔和逗号分隔。
    """
    header = _comment_header(text)
    if header:
        frame = _read_commented_header_table(text, header)
        frame.attrs["angle_unit"] = _angle_unit_hint(text)
        frame.attrs["timestamp_unit"] = _timestamp_unit_hint(text)
        return frame

    for kwargs in (
        {"sep": None, "engine": "python"},
        {"sep": r"\s+", "engine": "python"},
        {"sep": ",", "engine": "python"},
    ):
        try:
            # pandas 自动分隔符优先，其次强制空白分隔，再强制逗号分隔。
            # 这样可以兼容 CSV、TSV、空格日志以及混合空白日志。
            frame = pd.read_csv(io.StringIO(text), comment="#", **kwargs)
            if len(frame.columns) > 1 or not frame.empty:
                frame.attrs["timestamp_unit"] = _timestamp_unit_hint(text)
                return frame
        except Exception:
            continue
    raise ValueError("Could not parse CSV-like trajectory")


def _detect_commented_format(text: str) -> str:
    """识别带 # 注释表头的文本应走 SF、VLOC 还是通用 CSV。

    SF 是项目内固定表头；一旦检测到 flight_mode/reset_count1 或 num_inliers/depth_* 等标记，
    就走 _parse_sf()，让 ts1/ts2 和角度单位按 SF 规则处理。
    """
    header = _comment_header(text)
    if not header:
        return "csv"
    normalized = {_normalize_col(token): token for token in header}
    if _is_vloc_columns(normalized):
        return "vloc"
    return "sf" if _detect_sf_kind_from_columns(normalized) is not None else "csv"


def _detect_plain_header_format(lines: list[str]) -> str | None:
    """识别普通第一行表头的项目格式。

    例如 VLOC 文件的第一行不是注释，而是：
    ts status num_inliers reset_count tx ty tz yaw pitch roll latitude longitude altitude
    """
    if not lines:
        return None
    first = lines[0]
    if not re.search(r"[A-Za-z_]", first):
        return None
    tokens = _comment_header_tokens(first)
    normalized = {_normalize_col(token): token for token in tokens}
    if _is_vloc_columns(normalized):
        return "vloc"
    return None


def _comment_header(text: str) -> list[str] | None:
    """从注释行中寻找表头。

    例如：
    # timestamp x y z yaw pitch roll
    # ts [ns], p_x, p_y, p_z

    只有当注释行里能识别到 x/y/z 时才认为它是轨迹表头。
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        content = stripped.lstrip("#").strip()
        tokens = _comment_header_tokens(content)
        normalized = {_normalize_col(token): token for token in tokens}
        if (
            len(tokens) >= 3
            and _pick(normalized, X_COLUMN_CANDIDATES) is not None
            and _pick(normalized, Y_COLUMN_CANDIDATES) is not None
            and _pick(normalized, Z_COLUMN_CANDIDATES) is not None
        ):
            return tokens
    return None


def _comment_header_tokens(content: str) -> list[str]:
    """把注释表头内容拆成列名 token。

    会去掉 [unit] 和 (unit)，比如 yaw[deg] -> yaw。
    这样列名识别和单位识别可以分开处理。
    """
    if "," in content:
        pieces = content.split(",")
    else:
        pieces = re.split(r"[\s,;]+", content)

    tokens: list[str] = []
    for piece in pieces:
        token = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", piece).strip()
        if not token:
            continue
        if not _is_column_token(token) and " " in token:
            token = token.split()[0]
        if _is_column_token(token):
            tokens.append(token)
    return tokens


def _read_commented_header_table(text: str, header: list[str]) -> pd.DataFrame:
    """按注释表头读取后续数字行。

    只读取 header 长度以内的数字列；多余字段不影响轨迹解析。
    非数字行、空行、Inf/NaN 行会被跳过。
    """
    rows: list[list[float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        data_part = stripped.split("#", 1)[0].strip()
        if not data_part:
            continue
        tokens = [token for token in re.split(r"[\s,;]+", data_part) if token]
        if len(tokens) < len(header):
            continue
        try:
            row = [float(token) for token in tokens[: len(header)]]
        except ValueError:
            continue
        if any(math.isnan(value) or math.isinf(value) for value in row):
            continue
        rows.append(row)
    return pd.DataFrame(rows, columns=header)


def _is_column_token(token: str) -> bool:
    """判断 token 是否像一个列名，而不是普通说明文字。"""
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token))


def _timestamp_unit_hint(text: str, column: str | None = None) -> str | None:
    """从表头/列名中提取时间单位提示：ns/us/ms/s。

    代码意义：
    - 很多数据会写 timestamp[ns]、time_ms 或中文“毫秒”。
    - 如果能从文本中读到单位，就优先使用单位提示，而不是靠数量级猜。
    """
    snippets: list[str] = []
    if column:
        snippets.append(str(column))
    for line in text.splitlines()[:50]:
        lower = line.lower()
        if any(marker in lower for marker in ["timestamp", "time", "stamp", "ts", "时间"]):
            snippets.append(line)

    scan = "\n".join(snippets).lower()
    if not scan:
        return None
    if re.search(r"\[\s*ns\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*ns\b|nanosecond|nanoseconds|纳秒", scan):
        return "ns"
    if re.search(r"\[\s*us\s*\]|\[\s*µs\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*(?:us|µs)\b|microsecond|microseconds|微秒", scan):
        return "us"
    if re.search(r"\[\s*ms\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*ms\b|millisecond|milliseconds|毫秒", scan):
        return "ms"
    if re.search(r"\[\s*s\s*\]|(?:timestamp|time|stamp|ts)[_\-\s]*(?:s|sec|secs|second|seconds)\b", scan):
        return "s"
    return None


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


def _angle_unit_hint(text: str) -> str | None:
    """从注释行推断 yaw/pitch/roll 是角度制还是弧度制。

    用户之前的数据里 GT 和 VO 的角度单位可能不同：
    - yaw/pitch/roll[deg] -> 角度制。
    - yaw/pitch/roll[rad] -> 弧度制。
    这个函数只提供提示；最终仍由 _angle_unit_for_columns() 综合列名和数值范围判断。
    """
    for line in text.splitlines():
        lower = line.lower()
        if any(word in lower for word in ["角度", "degree", "degrees", " deg"]):
            if any(axis in lower for axis in ["yaw", "pitch", "roll", "row", "heading"]):
                return "deg"
        if any(word in lower for word in ["弧度", "radian", "radians", " rad"]):
            if any(axis in lower for axis in ["yaw", "pitch", "roll", "row", "heading"]):
                return "rad"
    return None


def _pick_angle_col(normalized: dict[str, Any], base: str, aliases: list[str]) -> Any | None:
    """查找 yaw/pitch/roll 列，兼容带单位后缀的列名。"""
    candidates: list[str] = []
    for name in [base, *aliases]:
        candidates.extend(
            [
                name,
                f"{name}_rad",
                f"{name}_radian",
                f"{name}_radians",
                f"{name}_deg",
                f"{name}_degree",
                f"{name}_degrees",
            ]
        )
    return _pick(normalized, candidates)


def _angle_unit_for_columns(cols: list[Any], hint: str | None, values: np.ndarray) -> str:
    """确定欧拉角单位。

    优先级：列名 > 注释提示 > 数值范围启发式。

    数值范围启发：
    - 如果最大绝对值明显超过 2*pi，基本可以判定为角度制。
    - 否则默认弧度制，避免把小角度度数误判成弧度造成过大旋转。
    """
    col_text = " ".join(str(col).lower() for col in cols)
    if any(marker in col_text for marker in ["deg", "degree", "degrees"]):
        return "deg"
    if any(marker in col_text for marker in ["rad", "radian", "radians"]):
        return "rad"
    if hint in {"deg", "rad"}:
        return hint
    finite = values[np.isfinite(values)]
    if len(finite) and np.nanmax(np.abs(finite)) > 2.0 * np.pi + 1e-6:
        return "deg"
    return "rad"


def _normalize_col(col: Any) -> str:
    """列名归一化。

    去掉单位、括号、大小写和非字母数字字符：
    - "p_RS_R_x [m]" -> "prsrx"
    - "timestamp(ns)" -> "timestamp"
    这样候选列名匹配更稳。
    """
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", str(col).strip().lower())
    return re.sub(r"[^a-z0-9]", "", text)


def _pick(normalized: dict[str, Any], names: list[str]) -> Any | None:
    """从 normalized 列名字典中按候选名寻找真实列名。"""
    normalized_names = [_normalize_col(name) for name in names]
    for name in normalized_names:
        if name in normalized:
            return normalized[name]
    return None
