from pathlib import Path

from test_evaluator import sample_calib_text


def test_local_path_server_uses_entry_specific_required_files():
    from static_web.local_server import required_local_files

    assert required_local_files("vo") == {
        "data": ("imu.txt",),
        "log": ("vo.txt", "calib_raw.yaml"),
    }
    assert required_local_files("vloc") == {
        "data": ("imu.txt",),
        "log": ("vloc.txt", "home_point.txt", "calib_raw.yaml"),
    }


def test_static_path_inputs_use_local_server_endpoint_for_direct_path_mode():
    source = Path("static_web/app.js").read_text()

    assert "/api/evaluate-paths" in source
    assert "/api/report-slice" in source
    assert "state.reportSource" in source
    assert "evaluateLocalPathBundle" in source
    assert "localPathServerErrorMessage" in source
    assert "static_web/local_server.py" in source
    assert "isBusy || !hasRuntime || missingBundleFiles().length > 0" not in source


def test_set_busy_reuses_run_button_state_for_local_path_mode():
    source = Path("static_web/app.js").read_text()
    start = source.index("function setBusy")
    end = source.index("function renderReport", start)
    set_busy_source = source[start:end]

    assert "updateRunButton();" in set_busy_source
    assert "missingBundleFiles().length > 0" not in set_busy_source


def test_local_path_server_evaluates_vo_without_home_point(tmp_path):
    from static_web.local_server import evaluate_paths_payload, get_report_slice

    data_dir = tmp_path / "data_dir"
    log_dir = tmp_path / "log_dir"
    data_dir.mkdir()
    log_dir.mkdir()
    imu_rows = [
        "ts ts_fcc status flight_mode x y z yaw pitch roll vx vy vz position_reset_count altitude_reset_count heading_reset_count latitude longitude altitude altitude_msl height"
    ]
    for i in range(220):
        t = 10.0 + i * 0.1
        imu_rows.append(
            f"{t:.1f} {100.0 + i * 0.1:.1f} 4194305 3 {t:.6f} 0 0 0 0 0 1 0 0 0 1 2 31.1 121.2 50 51 5"
        )
    vo_rows = ["ts num_inliers x y z yaw pitch roll is_keyframe time_cost reset_count"]
    for i in range(201):
        t = 10.0 + i * 0.1
        vo_rows.append(f"{t:.1f} 50 {t:.6f} 0 0 0 0 0 1 12.5 0")
    (data_dir / "imu.txt").write_text("\n".join(imu_rows), encoding="utf-8")
    (log_dir / "vo.txt").write_text("\n".join(vo_rows), encoding="utf-8")
    (log_dir / "calib_raw.yaml").write_text(sample_calib_text(), encoding="utf-8")

    light_report = evaluate_paths_payload(
        {
            "entryMode": "vo",
            "dataDirPath": str(data_dir),
            "logDirPath": str(log_dir),
            "config": {"segment_lengths_m": [50, 100]},
        }
    )

    assert light_report["inputs"]["entry_mode"] == "vo"
    assert light_report["summary"]["matched_poses"] == 201
    full_report = get_report_slice("full_report")
    assert full_report["inputs"]["entry_mode"] == "vo"
