from pathlib import Path
import subprocess

import pytest

from contrigent_api.services import (
    repository_test_runner,
)
from contrigent_api.services.repository_test_runner import (
    RepositoryTestRunnerError,
    run_repository_tests,
)


def create_uv_test_repository(
    tmp_path: Path,
) -> Path:
    repository = (
        tmp_path / "repository"
    )

    repository.mkdir()

    (
        repository / "pyproject.toml"
    ).write_text(
        "[project]\n"
        'name = "example"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.12"\n',
        encoding="utf-8",
    )

    (
        repository / "uv.lock"
    ).write_text(
        "version = 1\n",
        encoding="utf-8",
    )

    return repository


def test_repository_tests_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = (
        create_uv_test_repository(
            tmp_path
        )
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        if len(commands) == 1:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Dependencies ready.",
                stderr="",
            )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="10 passed",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = run_repository_tests(
        repository
    )

    assert result.passed is True
    assert result.stage == "tests"
    assert result.exit_code == 0
    assert "10 passed" in result.stdout

    assert len(commands) == 2

    assert "--network" not in commands[0]

    assert "--network" in commands[1]

    network_index = commands[1].index(
        "--network"
    )

    assert (
        commands[1][network_index + 1]
        == "none"
    )


def test_repository_test_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = (
        create_uv_test_repository(
            tmp_path
        )
    )

    call_count = 0

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Dependencies ready.",
                stderr="",
            )

        return subprocess.CompletedProcess(
            command,
            1,
            stdout="1 failed, 9 passed",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = run_repository_tests(
        repository
    )

    assert result.passed is False
    assert result.stage == "tests"
    assert result.exit_code == 1
    assert "1 failed" in result.stdout


def test_repository_without_uv_lock_is_rejected(
    tmp_path: Path,
) -> None:
    repository = (
        tmp_path / "repository"
    )

    repository.mkdir()

    (
        repository / "pyproject.toml"
    ).write_text(
        "[project]\n"
        'name = "example"\n'
        'version = "0.1.0"\n',
        encoding="utf-8",
    )

    with pytest.raises(
        RepositoryTestRunnerError,
        match="requires uv.lock",
    ):
        run_repository_tests(
            repository
        )