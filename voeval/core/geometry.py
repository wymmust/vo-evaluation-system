"""Coordinate transforms and rotation helpers."""

from __future__ import annotations

import math

import numpy as np

from ..io.calibration import Calibration, HomePoint
from ..io.formats import WGS84_A_M, WGS84_E2
from ..io.trajectory import Trajectory

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
    valid = np.isfinite(norms) & (norms > 0)
    if not np.all(valid):
        raise ValueError("TUM quaternion contains zero-norm or non-finite values")
    q /= norms[:, None]
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
    quats = np.asarray(out, dtype=float)
    norms = np.linalg.norm(quats, axis=1)
    valid = np.isfinite(norms) & (norms > 0)
    if not np.all(valid):
        raise ValueError("rotation matrix produced zero-norm or non-finite quaternion")
    return quats / norms[:, None]
