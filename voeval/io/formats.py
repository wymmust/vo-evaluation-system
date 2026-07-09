"""Fixed SF file contracts and evaluation constants."""

from __future__ import annotations

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
