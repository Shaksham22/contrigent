import subprocess

import pytest

from contrigent_api.services import (
    docker_runtime_manager,
)
from contrigent_api.services.docker_runtime_manager import (
    DockerRuntimeError,
    DockerRuntimeSession,
    start_docker_runtime_if_needed,
    stop_docker_runtime_if_started,
)


def test_existing_docker_runtime_is_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_cli_is_installed",
        lambda: True,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_engine_is_ready",
        lambda: True,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "ensure_linux_container_engine",
        lambda: None,
    )

    session = (
        start_docker_runtime_if_needed()
    )

    assert (
        session.started_by_contrigent
        is False
    )


def test_docker_desktop_is_started_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_cli_is_installed",
        lambda: True,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_engine_is_ready",
        lambda: False,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_desktop_cli_is_available",
        lambda: True,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "wait_for_docker_engine",
        lambda: None,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "ensure_linux_container_engine",
        lambda: None,
    )

    commands: list[list[str]] = []

    def fake_run_docker_command(
        command: list[str],
        timeout_seconds: int = 15,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        docker_runtime_manager,
        "run_docker_command",
        fake_run_docker_command,
    )

    session = (
        start_docker_runtime_if_needed()
    )

    assert (
        session.started_by_contrigent
        is True
    )

    assert [
        "docker",
        "desktop",
        "start",
        "--detach",
        "--timeout",
        "30",
    ] in commands


def test_docker_is_not_stopped_when_already_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_run_docker_command(
        command: list[str],
        timeout_seconds: int = 15,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True

        return subprocess.CompletedProcess(
            command,
            0,
        )

    monkeypatch.setattr(
        docker_runtime_manager,
        "run_docker_command",
        fake_run_docker_command,
    )

    stop_docker_runtime_if_started(
        DockerRuntimeSession(
            started_by_contrigent=False
        )
    )

    assert called is False


def test_missing_running_runtime_and_desktop_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_cli_is_installed",
        lambda: True,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_engine_is_ready",
        lambda: False,
    )

    monkeypatch.setattr(
        docker_runtime_manager,
        "docker_desktop_cli_is_available",
        lambda: False,
    )

    with pytest.raises(
        DockerRuntimeError,
        match="daemon",
    ):
        start_docker_runtime_if_needed()