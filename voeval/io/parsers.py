"""Fixed SF parsers."""

from __future__ import annotations

import re

import numpy as np

from .calibration import Calibration, HomePoint
from .formats import IMU_FIXED_COLUMNS, VLOC_FIXED_COLUMNS, VO_FIXED_COLUMNS
from .trajectory import Trajectory

def parse_imu_fixed(text: str, name: str = "imu.txt") -> Trajectory:
    """按需求文档读取 IMU/nav GT 的前 21 列。

    不根据表头猜列名；表头只会被当作非数字说明行跳过。
    少于 21 列时拒绝，多余列允许存在但不参与评估。
    最后一条非空、非注释的轨迹记录固定忽略。
    yaw/pitch/roll 固定为弧度。
    """

    from ..core.geometry import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(
        text,
        len(IMU_FIXED_COLUMNS),
        name,
        "IMU",
        allow_extra_columns=True,
        ignore_last_record=True,
    )
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
        data[:, 0],
        data[:, 4:7],
        rotations,
        extras=extras,
        source_format="sf_imu",
    )
def parse_vloc_fixed(text: str, name: str = "vloc.txt") -> Trajectory:
    """按需求文档读取 VLOC 输出的前 13 列。

    不根据表头猜列名；少于 13 列时拒绝，多余列忽略。
    最后一条非空、非注释的轨迹记录固定忽略。
    yaw/pitch/roll 固定为角度。
    """

    from ..core.geometry import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(
        text,
        len(VLOC_FIXED_COLUMNS),
        name,
        "VLOC",
        allow_extra_columns=True,
        ignore_last_record=True,
    )
    status = _require_integer_column(data[:, 1], name, "status")
    reset_count = _require_integer_column(data[:, 3], name, "reset_count")
    altitude_msl = np.abs(data[:, 6])
    extras = {
        "status": status,
        "num_inliers": data[:, 2],
        "reset_count": reset_count,
        "latitude": data[:, 10],
        "longitude": data[:, 11],
        "altitude": altitude_msl,
        "altitude_msl": altitude_msl,
        "height": data[:, 12],
        "vloc_mode": (status & 0x0F).astype(float),
    }
    angles = np.deg2rad(data[:, 7:10])
    rotations = euler_yaw_pitch_roll_to_matrix(angles[:, 0], angles[:, 1], angles[:, 2])
    return Trajectory(
        name,
        data[:, 0],
        data[:, 4:7],
        rotations,
        extras=extras,
        source_format="sf_vloc",
    )
def parse_vo_fixed(text: str, name: str = "vo.txt") -> Trajectory:
    """按需求文档读取 VO 输出的前 11 列。

    不根据表头猜列名；yaw/pitch/roll 固定为角度。
    少于 11 列时拒绝；11 列后的内容全部允许但不参与评估。
    最后一条非空、非注释的轨迹记录固定忽略。
    """

    from ..core.geometry import euler_yaw_pitch_roll_to_matrix

    data = _read_fixed_numeric_table(
        text,
        len(VO_FIXED_COLUMNS),
        name,
        "VO",
        allow_extra_columns=True,
        ignore_last_record=True,
    )
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
        data[:, 0],
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
    allow_extra_columns: bool = False,
    ignore_last_record: bool = False,
) -> np.ndarray:
    """读取固定列数字表。

    为了兼容文件首行写死的表头，非数字说明行只允许出现在第一条数据之前。
    真正的数据行至少要包含所需列；允许扩展列时只读取前 expected_cols 列。
    轨迹文件启用 ignore_last_record 时，最后一条非空、非注释记录不会进入解析。
    该记录可以是不完整数据，适用于忽略日志结束时尚未写完的末行。
    """

    lines = text.splitlines()
    if ignore_last_record:
        for index in range(len(lines) - 1, -1, -1):
            line = lines[index].strip()
            if line and not line.startswith("#"):
                del lines[index]
                break

    rows: list[list[float]] = []
    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [token for token in re.split(r"[\s,;]+", line) if token]
        parse_tokens = tokens[:expected_cols] if allow_extra_columns else tokens
        try:
            values = [float(token) for token in parse_tokens]
        except ValueError:
            if not rows:
                continue
            raise ValueError(f"{name}: {fmt_name} line {line_no} contains non-numeric values after data started")
        if len(tokens) < expected_cols:
            raise ValueError(f"{name}: {fmt_name} format expects at least {expected_cols} columns, got {len(tokens)} on line {line_no}")
        if len(tokens) > expected_cols:
            if not allow_extra_columns:
                raise ValueError(f"{name}: {fmt_name} format expects {expected_cols} columns, got {len(tokens)} on line {line_no}")
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
