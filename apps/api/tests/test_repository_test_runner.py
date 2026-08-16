from pathlib import Path
import subprocess
from collections.abc import Callable

import pytest

from contrigent_api.services import (
    repository_test_runner,
)
from contrigent_api.services.repository_test_runner import (
    RepositoryTestRunnerError,
    run_repository_tests,
)

from contrigent_api.services.docker_runtime_manager import (
    DockerRuntimeSession,
)

from contrigent_api.models.worker_result import (
    FileReplacement,
)


@pytest.fixture(autouse=True)
def disable_real_docker_management(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        repository_test_runner,
        "start_docker_runtime_if_needed",
        lambda: DockerRuntimeSession(
            started_by_contrigent=False
        ),
    )

    monkeypatch.setattr(
        repository_test_runner,
        "stop_docker_runtime_if_started",
        lambda _session: None,
    )


@pytest.fixture
def python_repository_factory(
    tmp_path: Path,
) -> Callable[..., Path]:
    repository_index = 0

    def create_repository(
        *,
        with_tests: bool = True,
    ) -> Path:
        nonlocal repository_index
        repository_index += 1
        repository = (
            tmp_path
            / f"repository-{repository_index}"
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

        if with_tests:
            (
                repository / "tests"
            ).mkdir()

        return repository

    return create_repository


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
        'requires-python = ">=3.12"\n'
        "\n"
        "[dependency-groups]\n"
        'test = ["pytest>=8"]\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n',
        encoding="utf-8",
    )

    (
        repository / "uv.lock"
    ).write_text(
        "version = 1\n",
        encoding="utf-8",
    )

    (
        repository / "tests"
    ).mkdir()

    return repository

def create_poetry_test_repository(
    tmp_path: Path,
) -> Path:
    repository = (
        tmp_path / "poetry-repository"
    )

    repository.mkdir()

    (
        repository / "pyproject.toml"
    ).write_text(
        "[tool.poetry]\n"
        'name = "example"\n'
        'version = "0.1.0"\n'
        'description = ""\n'
        'authors = []\n'
        "\n"
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        "\n"
        "[tool.poetry.group.testing.dependencies]\n"
        'pytest = "^8.0"\n'
        "\n"
        "[build-system]\n"
        'requires = ["poetry-core"]\n'
        'build-backend = "poetry.core.masonry.api"\n',
        encoding="utf-8",
    )

    (
        repository / "poetry.lock"
    ).write_text(
        "# test poetry lock\n",
        encoding="utf-8",
    )

    (
        repository / "tests"
    ).mkdir()

    return repository

def test_poetry_setup_uses_poetry_to_regenerate_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = (
        create_poetry_test_repository(
            tmp_path
        )
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(
            command
        )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Dependencies ready."
                if len(commands) == 1
                else "10 passed"
            ),
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

    dependency_shell_command = (
        commands[0][-1]
    )
    test_shell_command = (
        commands[1][-1]
    )

    assert (
        "uvx poetry lock"
        in dependency_shell_command
    )

    assert (
        "uvx poetry install --with testing"
        in dependency_shell_command
    )

    assert (
        "--all-groups"
        not in dependency_shell_command
    )

    assert (
        'export VIRTUAL_ENV='
        '"/test-environment/workspace/.venv"'
        in test_shell_command
    )

    assert (
        "/test-environment/workspace/"
        ".venv/bin/python -m pytest"
        in test_shell_command
    )

def test_repository_python_version_takes_priority_over_issue_text(
    tmp_path: Path,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )

    assert (
        repository_test_runner
        .select_test_python_version(
            repository,
            "The failure mentions Python 3.11.",
        )
        == "3.12"
    )


def test_python_version_file_has_highest_priority(
    tmp_path: Path,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )

    (
        repository / ".python-version"
    ).write_text(
        "3.13.4\n",
        encoding="utf-8",
    )

    assert (
        repository_test_runner
        .select_test_python_version(
            repository,
            "Python 3.11",
        )
        == "3.13"
    )


def test_uv_tests_use_active_virtual_environment(
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
        commands.append(
            command
        )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Dependencies ready."
                if len(commands) == 1
                else "10 passed"
            ),
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

    dependency_shell_command = (
        commands[0][-1]
    )
    test_shell_command = (
        commands[1][-1]
    )

    assert (
        "uv sync --python 3.12 --group test"
        in dependency_shell_command
    )

    assert "--locked" not in dependency_shell_command
    assert "--all-groups" not in dependency_shell_command

    assert (
        'export VIRTUAL_ENV='
        '"/test-environment/workspace/.venv"'
        in test_shell_command
    )

    assert (
        'export PATH="$VIRTUAL_ENV/bin:$PATH"'
        in test_shell_command
    )

    assert (
        "/test-environment/workspace/.venv/"
        "bin/python -m pytest"
        in test_shell_command
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


def test_repository_without_lockfile_uses_generic_pytest_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = (
        tmp_path / "repository"
    )

    repository.mkdir()
    (
        repository / "tests"
    ).mkdir()
    (
        repository / "requirements-test.txt"
    ).write_text(
        "pytest>=8\n",
        encoding="utf-8",
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Dependencies ready."
                if len(commands) == 1
                else "10 passed"
            ),
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
    assert (
        "-r requirements-test.txt pytest"
        in commands[0][-1]
    )


def test_ci_uv_setup_and_nox_test_form_one_strategy(
    python_repository_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = python_repository_factory()
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)

    (
        workflows / "tests.yml"
    ).write_text(
        "jobs:\n"
        "  unit:\n"
        "    steps:\n"
        "      - name: Install\n"
        "        run: uv pip install . --group test --system\n"
        "      - name: Test\n"
        "        run: nox -t unit\n",
        encoding="utf-8",
    )
    (
        repository / "CONTRIBUTING.md"
    ).write_text(
        "Run tests with `nox`.\n",
        encoding="utf-8",
    )
    (
        repository / "noxfile.py"
    ).write_text(
        "import nox\n",
        encoding="utf-8",
    )

    strategy = (
        repository_test_runner
        .build_repository_test_strategy(
            repository
        )
    )

    assert strategy.dependency_setup_commands == (
        "uv python install 3.12",
        (
            "uv venv --python 3.12 "
            "/test-environment/repository-venv"
        ),
        (
            "uv pip install --python "
            "/test-environment/repository-venv/bin/python "
            ". --group test"
        ),
        (
            "/test-environment/repository-venv/bin/nox "
            "--install-only -t unit"
        ),
    )
    assert strategy.test_command == (
        "/test-environment/repository-venv/bin/nox "
        "--reuse-existing-virtualenvs "
        "--no-install -t unit"
    )
    assert any(
        (
            ".github/workflows/tests.yml"
            in evidence
            and (
                "uv pip install . --group test --system"
                in evidence
            )
        )
        for evidence in strategy.evidence
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ready",
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
    assert (
        "uv pip install --python "
        "/test-environment/repository-venv/bin/python "
        ". --group test"
        in commands[0][-1]
    )
    assert "--system" not in commands[0][-1]
    assert "runner-venv" not in commands[0][-1]
    assert "--network none" in " ".join(commands[1])
    assert "export VIRTUAL_ENV" not in commands[1][-1]
    all_command_arguments = " ".join(
        argument
        for command in commands
        for argument in command
    )
    assert (
        "UV_PROJECT_ENVIRONMENT"
        not in all_command_arguments
    )
    assert (
        "POETRY_VIRTUALENVS_IN_PROJECT"
        not in all_command_arguments
    )


def test_more_specific_ci_nox_command_wins_over_documentation(
    python_repository_factory: Callable[..., Path],
) -> None:
    repository = python_repository_factory()
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)

    (
        workflows / "checks.yaml"
    ).write_text(
        "steps:\n"
        "  - name: Test\n"
        "    run: nox -t integration\n",
        encoding="utf-8",
    )
    (
        repository / "CONTRIBUTING.md"
    ).write_text(
        "Run tests with `nox`.\n",
        encoding="utf-8",
    )
    (
        repository / "noxfile.py"
    ).write_text(
        "import nox\n",
        encoding="utf-8",
    )

    strategy = (
        repository_test_runner
        .build_repository_test_strategy(
            repository
        )
    )

    assert (
        "runner-venv/bin/nox "
        "--install-only -t integration"
        in strategy.dependency_setup_commands[0]
    )
    assert strategy.test_command.endswith(
        "--no-install -t integration"
    )
    assert any(
        ".github/workflows/checks.yaml"
        in evidence
        for evidence in strategy.evidence
    )
    assert not any(
        "CONTRIBUTING.md"
        in evidence
        for evidence in strategy.evidence
    )


def test_uv_sync_and_nox_use_the_repository_environment(
    python_repository_factory: Callable[..., Path],
) -> None:
    repository = python_repository_factory()
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)
    (
        workflows / "tests.yml"
    ).write_text(
        "steps:\n"
        "  - run: uv sync --group test\n"
        "  - run: nox -t unit\n",
        encoding="utf-8",
    )

    strategy = (
        repository_test_runner
        .build_repository_test_strategy(
            repository
        )
    )

    assert strategy.dependency_setup_commands == (
        "uv python install 3.12",
        "uv sync --python 3.12 --group test",
        (
            "/test-environment/workspace/.venv/bin/nox "
            "--install-only -t unit"
        ),
    )
    assert strategy.test_command == (
        "/test-environment/workspace/.venv/bin/nox "
        "--reuse-existing-virtualenvs "
        "--no-install -t unit"
    )


def test_uv_sync_and_pytest_use_the_repository_environment(
    python_repository_factory: Callable[..., Path],
) -> None:
    repository = python_repository_factory()
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)
    (
        workflows / "tests.yml"
    ).write_text(
        "steps:\n"
        "  - run: uv sync --group test\n"
        "  - run: pytest -q\n",
        encoding="utf-8",
    )

    strategy = (
        repository_test_runner
        .build_repository_test_strategy(
            repository
        )
    )

    assert strategy.dependency_setup_commands == (
        "uv python install 3.12",
        "uv sync --python 3.12 --group test",
    )
    assert strategy.test_command == (
        "/test-environment/workspace/.venv/"
        "bin/python -m pytest -q"
    )


def test_pip_install_and_pytest_use_selected_python_environment(
    python_repository_factory: Callable[..., Path],
) -> None:
    repository = python_repository_factory()
    (
        repository / ".python-version"
    ).write_text(
        "3.13.2\n",
        encoding="utf-8",
    )
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)
    (
        workflows / "tests.yml"
    ).write_text(
        "steps:\n"
        "  - run: python -m pip install -e .\n"
        "  - run: pytest -q\n",
        encoding="utf-8",
    )

    strategy = (
        repository_test_runner
        .build_repository_test_strategy(
            repository
        )
    )

    assert strategy.python_version == "3.13"
    assert strategy.dependency_setup_commands == (
        "uv python install 3.13",
        (
            "uv venv --python 3.13 "
            "/test-environment/repository-venv"
        ),
        (
            "uv pip install --python "
            "/test-environment/repository-venv/"
            "bin/python -e ."
        ),
    )
    assert strategy.test_command == (
        "/test-environment/repository-venv/"
        "bin/python -m pytest -q"
    )


def test_lock_check_without_install_uses_dependency_fallback(
    python_repository_factory: Callable[..., Path],
) -> None:
    repository = python_repository_factory()
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)
    (
        workflows / "tests.yml"
    ).write_text(
        "steps:\n"
        "  - run: uv lock --check\n"
        "  - run: pytest -q\n",
        encoding="utf-8",
    )

    strategy = (
        repository_test_runner
        .build_repository_test_strategy(
            repository
        )
    )

    dependency_setup = " && ".join(
        strategy.dependency_setup_commands
    )

    assert "uv lock --check" not in dependency_setup
    assert (
        "uv pip install --python "
        "/test-environment/venv/bin/python "
        "-e . pytest"
        in dependency_setup
    )
    assert strategy.test_command == (
        "/test-environment/venv/bin/python "
        "-m pytest -q"
    )


def test_contributing_nox_command_controls_native_test_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )

    (
        repository / "CONTRIBUTING.md"
    ).write_text(
        "Run tests with `nox -t unit`.\n",
        encoding="utf-8",
    )

    (
        repository / "noxfile.py"
    ).write_text(
        "import nox\n",
        encoding="utf-8",
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Dependencies ready."
                if len(commands) == 1
                else "10 passed"
            ),
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
    assert (
        "runner-venv/bin/nox --install-only -t unit"
        in commands[0][-1]
    )
    assert (
        "runner-venv/bin/nox "
        "--reuse-existing-virtualenvs "
        "--no-install -t unit"
        in commands[1][-1]
    )
    assert (
        "--network none"
        in " ".join(commands[1])
    )


def test_ci_tox_command_controls_native_test_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)

    (
        workflows / "ci.yml"
    ).write_text(
        "steps:\n"
        "  - name: Test\n"
        "    run: tox -e py312\n",
        encoding="utf-8",
    )

    (
        repository / "tox.ini"
    ).write_text(
        "[tox]\n",
        encoding="utf-8",
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Dependencies ready."
                if len(commands) == 1
                else "10 passed"
            ),
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
    assert (
        "runner-venv/bin/tox --notest -e py312"
        in commands[0][-1]
    )
    assert (
        "runner-venv/bin/tox "
        "--skip-env-install -e py312"
        in commands[1][-1]
    )


def test_dependency_setup_failure_is_reported_before_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Dependency setup failed.",
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
    assert result.stage == "dependency_setup"
    assert result.exit_code == 1
    assert len(commands) == 1


def test_available_pytest_runner_proceeds_to_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "pytest 8.0"
                if len(commands) == 1
                else "10 passed"
            ),
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
    assert len(commands) == 2
    assert (
        "/test-environment/workspace/.venv/"
        "bin/python -m pytest --version"
        in commands[0][-1]
    )
    assert (
        "/test-environment/workspace/.venv/"
        "bin/python -m pytest"
        in commands[1][-1]
    )


def test_unavailable_pytest_runner_is_dependency_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert (
            "/test-environment/workspace/.venv/"
            "bin/python -m pytest --version"
            in command[-1]
        )
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="No module named pytest",
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
    assert result.stage == "dependency_setup"
    assert result.exit_code == 1
    assert "No module named pytest" in result.stderr
    assert len(commands) == 1


def test_unavailable_nox_executable_is_dependency_failure(
    python_repository_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = python_repository_factory()
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)
    (
        workflows / "tests.yml"
    ).write_text(
        "steps:\n"
        "  - run: uv sync --group test\n"
        "  - run: nox -t unit\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert (
            "/test-environment/workspace/.venv/"
            "bin/nox --version"
            in command[-1]
        )
        return subprocess.CompletedProcess(
            command,
            127,
            stdout="",
            stderr="nox: not found",
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
    assert result.stage == "dependency_setup"
    assert result.exit_code == 127
    assert len(commands) == 1


def test_unavailable_tox_executable_is_dependency_failure(
    python_repository_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = python_repository_factory()
    workflows = (
        repository / ".github" / "workflows"
    )
    workflows.mkdir(parents=True)
    (
        workflows / "tests.yml"
    ).write_text(
        "steps:\n"
        "  - run: uv sync --group test\n"
        "  - run: tox -e py312\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert (
            "/test-environment/workspace/.venv/"
            "bin/tox --version"
            in command[-1]
        )
        return subprocess.CompletedProcess(
            command,
            127,
            stdout="",
            stderr="tox: not found",
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
    assert result.stage == "dependency_setup"
    assert result.exit_code == 127
    assert len(commands) == 1


def test_missing_runner_never_reaches_test_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )
    commands: list[list[str]] = []
    progress_events: list[tuple[int, str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="No module named pytest",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = run_repository_tests(
        repository,
        progress_callback=(
            lambda percentage, message:
            progress_events.append(
                (percentage, message)
            )
        ),
    )

    assert result.stage == "dependency_setup"
    assert len(commands) == 1
    assert "--network none" not in " ".join(
        commands[0]
    )
    assert not any(
        message == "Running repository tests"
        for _percentage, message in progress_events
    )


def test_repository_test_progress_is_reported(
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

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Dependencies ready."
                if call_count == 1
                else "10 passed"
            ),
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    progress_events: list[
        tuple[int, str]
    ] = []

    result = run_repository_tests(
        repository,
        progress_callback=(
            lambda percentage, message:
            progress_events.append(
                (
                    percentage,
                    message,
                )
            )
        ),
    )

    assert result.passed is True

    assert progress_events == [
        (
            5,
            "Checking Docker",
        ),
        (
            15,
            "Docker ready",
        ),
        (
            25,
            "Preparing test environment",
        ),
        (
            50,
            "Dependencies ready",
        ),
        (
            60,
            "Running repository tests",
        ),
        (
            90,
            "Tests finished",
        ),
        (
            95,
            "Processing test results",
        ),
    ]

def test_candidate_files_are_overlaid_before_dependency_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )

    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(
            command
        )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "Dependencies ready."
                if len(commands) == 1
                else "10 passed"
            ),
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = run_repository_tests(
        repository,
        proposed_files=[
            FileReplacement(
                file_path="src/example.py",
                reason="Candidate implementation.",
                replacement_content=(
                    "VALUE = 2\n"
                ),
            )
        ],
    )

    assert result.passed is True

    dependency_shell_command = (
        commands[0][-1]
    )

    assert (
        "cp -a /workspace/. "
        "/test-environment/workspace/"
        in dependency_shell_command
    )

    assert (
        "cp -a "
        "/test-environment/candidate-overrides/. "
        "/test-environment/workspace/"
        in dependency_shell_command
    )

    workspace_mount = next(
        commands[0][index + 1]
        for index, value
        in enumerate(commands[0])
        if (
            value == "--mount"
            and "/workspace"
            in commands[0][index + 1]
        )
    )

    assert workspace_mount.endswith(
        ",readonly"
    )
