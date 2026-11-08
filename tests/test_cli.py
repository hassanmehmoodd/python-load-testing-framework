"""CLI safeguards and the Locust command line."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from perfload import __file__ as package_file
from perfload.cli import main
from perfload.config import load_config
from perfload.runner import build_locust_command
from perfload.safeguards import prepare_run
from tests.conftest import BASE_CONFIG, write_config


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_rejects_user_cap(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    with pytest.raises(SystemExit) as exc:
        main(["run", "--config", str(path), "--users", "40"])
    assert exc.value.code == 2


def test_rejects_public_host_with_acknowledgement(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "run",
                "--config",
                str(path),
                "--base-url",
                "https://github.com",
                "--acknowledge-authorization",
            ]
        )
    assert exc.value.code == 2


def test_acknowledgement_allows_a_private_host_and_calls_the_runner(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    called = {}

    def fake_execute(plan, output, **kwargs):
        called["host"] = plan.host
        called["output"] = output
        return {"metrics": {"total_requests": 1}}

    monkeypatch.setattr("perfload.cli.execute", fake_execute)
    main(
        [
            "run",
            "--config",
            str(path),
            "--base-url",
            "http://example.com:8080",
            "--acknowledge-authorization",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert called["host"] == "example.com"
    assert called["output"] == tmp_path / "out"


def test_check_target_reports_unreachable(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "check-target",
                "--config",
                str(path),
                "--base-url",
                "http://127.0.0.1:59999",
                "--wait-for-target",
                "0",
            ]
        )
    assert exc.value.code == 3


def test_locust_command_uses_virtual_users_as_concurrency(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(path, BASE_CONFIG)
    plan = prepare_run(load_config(path, environ={}), acknowledge=False)
    command = build_locust_command(plan, tmp_path)
    assert command[command.index("--users") + 1] == "5"
    assert command[command.index("--spawn-rate") + 1] == "1.0"
    assert "--headless" in command
    assert command[command.index("--host") + 1] == "http://127.0.0.1:8000"
    assert Path(command[command.index("-f") + 1]).name == "locustfile.py"


def test_locustfile_refuses_a_denylisted_host(tmp_path):
    runtime = {
        "base_url": "https://github.com",
        "allowed_hosts": ["localhost"],
        "acknowledge_authorization": True,
        "stages": [{"end": 25, "users": 5, "spawn_rate": 1}],
        "users": 5,
        "spawn_rate": 1,
        "duration_seconds": 25,
        "max_users": 25,
        "max_spawn_rate": 10,
        "request_log": str(tmp_path / "requests.jsonl"),
    }
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(runtime), encoding="utf-8")
    locustfile = Path(package_file).resolve().parent / "locustfile.py"
    env = os.environ.copy()
    env["PERFLOAD_RUNTIME_JSON"] = str(path)
    completed = subprocess.run(
        [sys.executable, str(locustfile)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2
    assert "denylist" in completed.stderr.lower()
