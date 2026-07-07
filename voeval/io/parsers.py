"""Fixed SF parsers and TUM trajectory text loading."""

from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np

from .calibration import Calibration, HomePoint
from .formats import IMU_FIXED_COLUMNS, VLOC_FIXED_COLUMNS, VO_FIXED_COLUMNS
from .trajectory import Trajectory

def parse_imu_fixed(text: str, name: str = "imu.txt") -> Trajectory:
    """按需求文档固定 21 列解析 IMU/nav GT。

    不根据表头猜列名；表头只会被当作非数字说明行跳过。
    yaw/pitch/roll 固定为弧度。
    """

    from ..core.geometry import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(text, len(IMU_FIXED_COLUMNS), name, "IMU")
    status = _require_integer_column(data[:, 2], name, "status")
    flight_mode = _require_integer_column(data[:, 3], name, "flight_mode")
    position_reset_count = _require_integer_column(data[:, 13], name, "position_reset_count")
    altitude_reset_count = _require_integer_column(data[:, 14], name, "altitude_reset_count")
    heading_reset_count = _require_integer_column(data[:, 15], name, "heading_reset_count")
    extras = {
        "ts_fcc": data[:, 1],
        "status": status,
        "flight_mode": flight_mode,
        "vx": data[:, 10],
        "vy": data[:, 11],
        "vz": data[:, 12],
        "position_reset_count": position_reset_count,
        "altitude_reset_count": altitude_reset_count,
        "heading_reset_count": heading_reset_count,
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
        _normalize_timestamps(data[:, 0]),
        data[:, 4:7],
        rotations,
        extras=extras,
        source_format="sf_imu",
    )
def parse_vloc_fixed(text: str, name: str = "vloc.txt") -> Trajectory:
    """按需求文档固定 13 列解析 VLOC 输出。

    不根据表头猜列名；yaw/pitch/roll 固定为角度。
    """

    from ..core.geometry import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(text, len(VLOC_FIXED_COLUMNS), name, "VLOC")
    status = _require_integer_column(data[:, 1], name, "status")
    reset_count = _require_integer_column(data[:, 3], name, "reset_count")
    extras = {
        "status": status,
        "num_inliers": data[:, 2],
        "reset_count": reset_count,
        "latitude": data[:, 10],
        "longitude": data[:, 11],
        "altitude": data[:, 12],
        "altitude_msl": data[:, 12],
        "height": data[:, 12],
        "vloc_mode": (status & 0x0F).astype(float),
    }
    angles = np.deg2rad(data[:, 7:10])
    rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])
    return Trajectory(
        name,
        _normalize_timestamps(data[:, 0]),
        data[:, 4:7],
        rotations,
        extras=extras,
        source_format="sf_vloc",
    )
def parse_vo_fixed(text: str, name: str = "vo.txt") -> Trajectory:
    """按需求文档固定 11 列解析 VO 输出。

    不根据表头猜列名；yaw/pitch/roll 固定为角度。
    新版主线为 11 列；旧版 14 列会读取前 11 列，最后三列 depth 不参与评估。
    """

    from ..core.geometry import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(text, len(VO_FIXED_COLUMNS), name, "VO", legacy_column_counts={14: 11})
    is_keyframe = _require_integer_column(data[:, 8], name, "is_keyframe")
    reset_count = _require_integer_column(data[:, 10], name, "reset_count")
    extras = {
        "num_inliers": data[:, 1],
        "is_keyframe": is_keyframe,
        "time_cost": data[:, 9],
        "reset_count": reset_count,
    }
    angles = np.deg2rad(data[:, 5:8])
    rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])
    return Trajectory(
        name,
        _normalize_timestamps(data[:, 0]),
        data[:, 2:5],
        rotations,
        extras=extras,
        source_format="sf_vo",
    )
def parse_home_point_fixed(text: str, name: str = "home_point.txt") -> HomePoint:
    """按固定三列解析 home_point.txt：longitude latitude altitude_msl。"""

    data = _read_fixed_numeric_table(text, 3, name, "home_point")
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
def _read_fixed_numeric_table(
    text: str,
    expected_cols: int,
    name: str,
    fmt_name: str,
    *,
    legacy_column_counts: dict[int, int] | None = None,
) -> np.ndarray:
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
        if legacy_column_counts and len(values) in legacy_column_counts:
            values = values[: legacy_column_counts[len(values)]]
        if len(values) != expected_cols:
            legacy_note = ""
            if legacy_column_counts:
                legacy_note = " (or legacy " + ", ".join(str(item) for item in sorted(legacy_column_counts)) + ")"
            raise ValueError(f"{name}: {fmt_name} format expects {expected_cols} columns{legacy_note}, got {len(values)} on line {line_no}")
        rows.append(values)
    if not rows:
        raise ValueError(f"{name}: {fmt_name} file contains no numeric data rows")
    data = np.asarray(rows, dtype=float)
    _require_finite_numeric_table(data, name)
    return data
def _require_finite_numeric_table(data: np.ndarray, name: str) -> None:
    if not np.isfinite(data).all():
        raise ValueError(f"{name}: fixed-format input contains NaN or infinite values")
def _require_integer_column(values: np.ndarray, name: str, column_name: str) -> np.ndarray:
    """固定格式中的状态位/reset_count 必须是真整数。"""
    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all() or not np.allclose(arr, np.round(arr), rtol=0.0, atol=1e-9):
        raise ValueError(f"{name}: column {column_name} must contain integer values")
    return np.round(arr).astype(np.int64)
def _extract_fixed_yaml_matrix(text: str, key: str, name: str, required: bool) -> np.ndarray | None:
    match = re.search(rf"{re.escape(key)}\s*:\s*\[([^\]]+)\]", text, flags=re.DOTALL)
    block = ""
    if match:
        block = match.group(1)
    else:
        block_match = re.search(
            rf"(?m)^\s*{re.escape(key)}\s*:\s*\n((?:\s*-\s*\[[^\n]+\]\s*\n?)+)",
            text,
        )
        if block_match:
            block = block_match.group(1)
    if not block:
        if required:
            raise ValueError(f"{name}: missing required calibration matrix {key}")
        return None
    values = [float(token) for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", block)]
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
    - bytes / BytesIO: 浏览器上传内容或类文件对象。
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
        if hasattr(source, "seek"):
            source.seek(0)
        data = source.read()
        if isinstance(data, str):
            return data, getattr(source, "name", "uploaded")
        return data.decode("utf-8", errors="replace"), getattr(source, "name", "uploaded")
    path = Path(str(source))
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace"), path.name
    source_text = str(source)
    if "\n" not in source_text and _looks_like_path(source_text):
        raise FileNotFoundError(source_text)
    return source_text, "text"
def _looks_like_path(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if any(ch.isspace() for ch in stripped):
        return False
    return (
        "/" in stripped
        or "\\" in stripped
        or stripped.startswith(("~", "."))
        or Path(stripped).suffix.lower() in {".txt", ".tum", ".csv", ".tsv", ".log", ".yaml", ".yml"}
    )
def _meaningful_lines(text: str) -> list[str]:
    """去掉空行和注释行，供无表头格式识别使用。"""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
def _parse_float_line(line: str) -> list[float]:
    """解析一行空格分隔的纯数字。"""
    return [float(token) for token in line.split()]
def _parse_tum_numeric_table(lines: list[str], name: str) -> Trajectory:
    """解析无表头 TUM 数字表：timestamp tx ty tz qx qy qz qw。"""
    from ..core.geometry import quaternion_to_matrix

    rows = [_parse_float_line(line) for line in lines]
    width = max(len(row) for row in rows)
    if any(len(row) != width for row in rows):
        raise ValueError(f"{name}: inconsistent number of columns")
    data = np.asarray(rows, dtype=float)
    if data.shape[1] != 8:
        raise ValueError(f"{name}: TUM format expects exactly 8 columns, got {data.shape[1]}")
    stamps = _normalize_timestamps(data[:, 0])
    positions = data[:, 1:4]
    rotations = quaternion_to_matrix(data[:, 4], data[:, 5], data[:, 6], data[:, 7])
    return Trajectory(name, stamps, positions, rotations, source_format="tum")
def _normalize_timestamps(stamps: np.ndarray) -> np.ndarray:
    """固定把输入时间戳作为秒读取。

    这直接影响 duration_s、RPE、局部尺度窗口、时间间隔断点和 TUM 时间关联阈值。

    当前支持的 sf_vo、sf_vloc 和 TUM 输入都已固定为秒，不再按数量级推断或换算 ns/us/ms。
    """
    return np.asarray(stamps, dtype=float)
