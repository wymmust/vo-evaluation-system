"""Evaluation core algorithms and workflow pipeline."""

from .alignment import apply_alignment, sim3_alignment, umeyama_alignment
from .config import EvaluationConfig
from .errors import relative_error, relative_pose, rotation_errors
from .geometry import euler_yaw_pitch_roll_from_matrix, euler_yaw_pitch_roll_to_matrix, geodetic_to_ecef, geodetic_to_ned, matrix_to_quaternion, quaternion_to_matrix, rotation_angle, sf_nav_to_body_ned_trajectory, sf_nav_to_camera_trajectory, sf_vloc_to_body_ned_trajectory, wrap_pi, yaw_from_rot
from .interpolation import extra_values_linear, extra_values_nearest, interpolate_positions_from_brackets, interpolate_reference_to_estimate, interpolate_rotations_from_brackets, interpolation_brackets, nearest_indices_for_stamps, prepare_evaluation_trajectories, slerp_quaternion, subset_trajectory, trajectory_extra_or_nan
from .pipeline import BundleEvaluationResult, TrajectoryEvaluationResult, evaluate_trajectory_result, evaluate_vloc_bundle_core, evaluate_vo_bundle_core
from .segments import detect_associated_discontinuities, segments_from_breaks, vo_valid_segment_indices
from .statistics import describe, normalize_delta_config, path_distance, rpe_frame_dataframe, scale_frame_dataframe

__all__ = [name for name in globals() if not name.startswith("_")]
