"""Input formats, trajectory models, and bundle loaders."""

from .bundle import SfVlocBundle, SfVoBundle, load_vloc_evaluation_bundle, load_vo_evaluation_bundle
from .calibration import Calibration, HomePoint
from .formats import (
    FIXED_DISCONTINUITY_STEP_M,
    FIXED_DISCONTINUITY_TIME_GAP_S,
    FIXED_TIME_OFFSET_S,
    IMU_FIXED_COLUMNS,
    VLOC_FIXED_COLUMNS,
    VLOC_FIXED_MAX_INTERPOLATION_GAP_S,
    VO_FIXED_COLUMNS,
    VO_FIXED_MAX_INTERPOLATION_GAP_S,
    VO_MIN_VALID_SEGMENT_DURATION_S,
    VO_MIN_VALID_SEGMENT_FRAMES,
    WGS84_A_M,
    WGS84_E2,
    WGS84_F,
)
from .parsers import parse_calib_raw_fixed, parse_home_point_fixed, parse_imu_fixed, parse_vloc_fixed, parse_vo_fixed
from .trajectory import Trajectory

__all__ = [
    "Calibration",
    "FIXED_DISCONTINUITY_STEP_M",
    "FIXED_DISCONTINUITY_TIME_GAP_S",
    "FIXED_TIME_OFFSET_S",
    "HomePoint",
    "IMU_FIXED_COLUMNS",
    "SfVlocBundle",
    "SfVoBundle",
    "Trajectory",
    "VLOC_FIXED_COLUMNS",
    "VLOC_FIXED_MAX_INTERPOLATION_GAP_S",
    "VO_FIXED_COLUMNS",
    "VO_FIXED_MAX_INTERPOLATION_GAP_S",
    "VO_MIN_VALID_SEGMENT_DURATION_S",
    "VO_MIN_VALID_SEGMENT_FRAMES",
    "WGS84_A_M",
    "WGS84_E2",
    "WGS84_F",
    "load_vloc_evaluation_bundle",
    "load_vo_evaluation_bundle",
    "parse_calib_raw_fixed",
    "parse_home_point_fixed",
    "parse_imu_fixed",
    "parse_vloc_fixed",
    "parse_vo_fixed",
]
