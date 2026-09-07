import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from exo.api.main import (
    _counter_rate,
    _read_recent_fleet_jobs,
    _read_roaming_status,
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


def test_roaming_status_requires_fresh_evidence_and_excludes_private_fields(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    path = tmp_path / "status.json"
    payload = {
        "schema": 1,
        "role": "pro",
        "state": "connected",
        "sampled_at": now.isoformat(),
        "recovery_count": 1,
        "peer_reachable": True,
        "peer_api_ip": "10.215.90.216",
        "ssid": "private hotel network",
        "token": "must-not-leak",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    fresh = _read_roaming_status(path, now=now)
    assert fresh["available"] is True
    assert fresh["stale"] is False
    assert fresh["peer_api_ip"] == "10.215.90.216"
    assert "ssid" not in fresh
    assert "token" not in fresh
    assert _read_roaming_status(path, now=now + timedelta(seconds=61))["stale"]
    assert _read_roaming_status(path, now=now - timedelta(seconds=10))["stale"]


def test_roaming_status_missing_corrupt_and_oversized_are_unavailable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    assert _read_roaming_status(path) == {
        "available": False,
        "stale": True,
        "state": "unavailable",
    }
    for content in ("{", "[]", "x" * 16_385):
        path.write_text(content, encoding="utf-8")
        status = _read_roaming_status(path)
        assert status["available"] is False
        assert status["stale"] is True


def test_roaming_status_naive_timestamp_and_unknown_state_are_not_healthy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    for state, sampled_at in (
        ("connected", "2026-09-07T00:00:00"),
        ("private detail", "2026-09-07T00:00:00Z"),
    ):
        path.write_text(
            json.dumps(
                {"schema": 1, "role": "air", "state": state, "sampled_at": sampled_at}
            ),
            encoding="utf-8",
        )
        assert _read_roaming_status(path)["available"] is False
