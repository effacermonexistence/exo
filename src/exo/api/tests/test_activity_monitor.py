import json
import socket
from pathlib import Path

from exo.api.main import (
    _counter_rate,
    _read_recent_fleet_jobs,
    _sanitize_fleet_snapshot,
)


def test_counter_rate_is_per_second_and_never_negative() -> None:
    assert _counter_rate(150, 100, 2.0) == 25.0
    assert _counter_rate(90, 100, 1.0) == 0.0
    assert _counter_rate(150, 100, 0.0) == 0.0


def test_fleet_snapshot_excludes_unknown_or_sensitive_fields() -> None:
    sanitized = _sanitize_fleet_snapshot(
        {
            "nodes": [
                {
                    "device_id": "device:test",
                    "hostname": "test.local",
                    "queue_depth": 1,
                    "secret": "must-not-leak",
                }
            ],
            "credential": "must-not-leak",
        }
    )

    assert sanitized == {
        "nodes": [
            {
                "device_id": "device:test",
                "hostname": "test.local",
                "queue_depth": 1,
            }
        ]
    }


def test_recent_fleet_jobs_exposes_metadata_only(tmp_path: Path) -> None:
    receipt = {
        "job_id": "job-1",
        "profile": "codex",
        "state": "complete",
        "executor_device_id": "device:air",
        "execution_mode": "single_node",
        "objective_version": "os1-fleet-objective-v1",
        "result": "private model output",
        "result_hash": "private-hash",
    }
    (tmp_path / "job-1.json").write_text(json.dumps(receipt), encoding="utf-8")

    jobs = _read_recent_fleet_jobs(tmp_path)

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "job-1"
    assert jobs[0]["profile"] == "codex"
    assert "updated_at_ms" in jobs[0]
    assert "result" not in jobs[0]
    assert "result_hash" not in jobs[0]


def test_hostname_is_available_for_activity_fallback() -> None:
    assert socket.gethostname()
