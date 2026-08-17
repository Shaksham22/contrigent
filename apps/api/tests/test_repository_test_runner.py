from pathlib import Path
import subprocess
from collections.abc import Callable

import pytest

from contrigent_api.services import (
    repository_test_runner,
)
from contrigent_api.services.repository_test_runner import (
    RepositoryTestRunnerError,
    RepositoryService,
    RepositoryTestStrategy,
    RepositoryTestNetworkMode,
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


def make_service_strategy(
    *,
    network_mode: RepositoryTestNetworkMode,
    services: tuple[RepositoryService, ...] = (),
) -> RepositoryTestStrategy:
    return RepositoryTestStrategy(
        ecosystem="node",
        runtime_version="22",
        project_root=".",
        docker_image="node:22-bookworm-slim",
        setup_commands=(("npm", "ci"),),
        background_commands=(),
        pre_test_commands=(),
        test_commands=(("npm", "test"),),
        environment_variables={"NODE_ENV": "test"},
        test_network_mode=network_mode,
        services=services,
        evidence=("package.json",),
    )

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
    assert strategy.background_commands == ()
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
            "Preparing and running repository tests",
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


def test_explicit_strategy_execution_does_not_redetect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = create_uv_test_repository(
        tmp_path
    )
    strategy = RepositoryTestStrategy(
        ecosystem="python",
        runtime_version="3.12",
        project_root=".",
        docker_image=(
            "ghcr.io/astral-sh/uv:"
            "python3.12-bookworm-slim"
        ),
        setup_commands=(
            ("uv", "sync", "--group", "test"),
        ),
        background_commands=(),
        pre_test_commands=(),
        test_commands=(("pytest", "-q"),),
        environment_variables={},
        test_network_mode=RepositoryTestNetworkMode.NONE,
        services=(),
        evidence=("verified recipe",),
    )
    commands: list[list[str]] = []

    def fail_if_redetected(*_args, **_kwargs):
        raise AssertionError(
            "Stored strategies must not be rediscovered."
        )

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
        repository_test_runner,
        "build_repository_test_strategy",
        fail_if_redetected,
    )
    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is True
    assert "uv sync --group test" in commands[0][-1]
    assert strategy.test_command in commands[1][-1]


def test_repository_setup_may_generate_and_modify_workspace_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    pyproject_path = repository / "pyproject.toml"
    original_pyproject = "[project]\nname = 'example'\n"
    pyproject_path.write_text(
        original_pyproject,
        encoding="utf-8",
    )
    strategy = RepositoryTestStrategy(
        ecosystem="python",
        runtime_version="3.12",
        project_root=".",
        docker_image=(
            "ghcr.io/astral-sh/uv:"
            "python3.12-bookworm-slim"
        ),
        setup_commands=(("uv", "sync"),),
        background_commands=(),
        pre_test_commands=(),
        test_commands=(("pytest",),),
        environment_variables={},
        test_network_mode=RepositoryTestNetworkMode.NONE,
        services=(),
        evidence=("pyproject.toml",),
    )
    calls = 0

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1

        if calls == 1:
            environment_mount = next(
                command[index + 1]
                for index, token in enumerate(command)
                if (
                    token == "--mount"
                    and "dst=/test-environment"
                    in command[index + 1]
                )
            )
            source = next(
                part.removeprefix("src=")
                for part in environment_mount.split(",")
                if part.startswith("src=")
            )
            workspace = Path(source) / "workspace"
            workspace.mkdir(exist_ok=True)
            (workspace / "uv.lock").write_text(
                "version = 1\n",
                encoding="utf-8",
            )
            (workspace / "pyproject.toml").write_text(
                "[project]\nname = 'generated'\n",
                encoding="utf-8",
            )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ready" if calls == 1 else "1 passed",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = repository_test_runner.execute_repository_test_strategy(
        repository,
        strategy,
    )

    assert result.passed is True
    assert pyproject_path.read_text(encoding="utf-8") == original_pyproject
    assert not (repository / "uv.lock").exists()


def test_node_package_lock_uses_node_image_and_real_npm_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "node-repository"
    repository.mkdir()
    (repository / "package.json").write_text(
        (
            '{"name":"example","scripts":'
            '{"test":"node --test"}}'
        ),
        encoding="utf-8",
    )
    (repository / "package-lock.json").write_text(
        '{"lockfileVersion":3}',
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
            stdout="ready" if len(commands) == 1 else "1 passed",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = run_repository_tests(repository)
    strategy = (
        repository_test_runner
        .build_repository_test_strategy(repository)
    )

    assert result.passed is True
    assert result.stage == "tests"
    assert strategy.ecosystem == "node"
    assert strategy.background_commands == ()
    assert strategy.setup_commands == (("npm", "ci"),)
    assert strategy.test_commands == (("npm", "test"),)
    assert strategy.docker_image == "node:22-bookworm-slim"
    assert "node:22-bookworm-slim" in commands[0]
    assert "npm ci" in commands[0][-1]
    assert "npm test" in commands[1][-1]
    assert "uv " not in commands[0][-1]
    assert "python" not in commands[0][-1].lower()


def test_node_package_manager_comes_from_lockfile(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "pnpm-repository"
    repository.mkdir()
    (repository / "package.json").write_text(
        '{"scripts":{"test:unit":"vitest run"}}',
        encoding="utf-8",
    )
    (repository / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n",
        encoding="utf-8",
    )

    strategy = (
        repository_test_runner
        .build_repository_test_strategy(repository)
    )

    assert strategy.setup_commands == (
        ("corepack", "enable"),
        ("pnpm", "install", "--frozen-lockfile"),
    )
    assert strategy.test_commands == (
        ("pnpm", "run", "test:unit"),
    )


def test_monorepo_strategy_executes_only_selected_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "monorepo"
    repository.mkdir()
    (repository / "tests").mkdir()
    (repository / "tests" / "test_broken.py").write_text(
        "raise RuntimeError('unrelated')\n",
        encoding="utf-8",
    )
    project = repository / "sdk" / "python"
    (project / "tests").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        (
            "[project]\nname = 'sdk'\n"
            "requires-python = '>=3.12'\n"
        ),
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
            stdout="ready",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )
    strategy = (
        repository_test_runner
        .build_repository_test_strategy(
            repository,
            project_root="sdk/python",
        )
    )
    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is True
    assert strategy.project_root == "sdk/python"
    assert all(
        "cd /test-environment/workspace/sdk/python"
        in command[-1]
        for command in commands
    )
    assert all(
        "test_broken.py" not in command[-1]
        for command in commands
    )


def test_service_only_network_starts_readies_and_cleans_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository-with-service"
    repository.mkdir()
    service = RepositoryService(
        name="search",
        image="example/service:1.2.3",
        command=("serve", "--test-mode"),
        environment_variables={"SERVICE_MODE": "test"},
        network_alias="search",
        readiness_command=("service-health",),
        startup_timeout_seconds=5,
    )
    strategy = make_service_strategy(
        network_mode=(
            RepositoryTestNetworkMode.SERVICES_ONLY
        ),
        services=(service,),
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        stdout = ""

        if command[:2] == ["docker", "inspect"]:
            stdout = "true\n"
        elif (
            command[:2] == ["docker", "run"]
            and "--detach" not in command
        ):
            stdout = "tests passed"

        return subprocess.CompletedProcess(
            command,
            0,
            stdout=stdout,
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is True
    network_create = next(
        command
        for command in commands
        if command[:3]
        == ["docker", "network", "create"]
    )
    network_name = network_create[-1]
    assert "--internal" in network_create

    service_run = next(
        command
        for command in commands
        if (
            command[:2] == ["docker", "run"]
            and "--detach" in command
        )
    )
    assert "--network" in service_run
    assert network_name in service_run
    assert "--network-alias" in service_run
    assert "--security-opt" in service_run
    assert "--privileged" not in service_run
    assert "--publish" not in service_run
    assert "--mount" not in service_run

    test_run = next(
        command
        for command in commands
        if (
            command[:2] == ["docker", "run"]
            and "--detach" not in command
            and "npm test" in command[-1]
        )
    )
    assert test_run[test_run.index("--network") + 1] == network_name
    assert ["docker", "exec"] == next(
        command[:2]
        for command in commands
        if command[:2] == ["docker", "exec"]
    )
    assert any(
        command[:3] == ["docker", "rm", "--force"]
        for command in commands
    )
    assert commands[-1] == [
        "docker",
        "network",
        "rm",
        network_name,
    ]


def test_service_start_failure_is_environment_failure_and_cleans_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository-service-failure"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=(
            RepositoryTestNetworkMode.SERVICES_ONLY
        ),
        services=(
            RepositoryService(
                name="dependency",
                image="example/dependency:1",
                network_alias="dependency",
            ),
        ),
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        failed = (
            command[:2] == ["docker", "run"]
            and "--detach" in command
        )
        return subprocess.CompletedProcess(
            command,
            1 if failed else 0,
            stdout="",
            stderr="service failed" if failed else "",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is False
    assert result.stage == "dependency_setup"
    assert "failed to start" in result.stderr
    assert not any(
        "npm test" in command[-1]
        for command in commands
    )
    assert commands[-1][:3] == [
        "docker",
        "network",
        "rm",
    ]


def test_service_readiness_retries_then_starts_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository-readiness-retry"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=(
            RepositoryTestNetworkMode.SERVICES_ONLY
        ),
        services=(
            RepositoryService(
                name="dependency",
                image="example/dependency:1",
                network_alias="dependency",
                readiness_command=("wait-ready",),
                startup_timeout_seconds=5,
            ),
        ),
    )
    commands: list[list[str]] = []
    readiness_calls = 0
    sleep_calls: list[float] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal readiness_calls
        commands.append(command)

        if command[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="true\n",
                stderr="",
            )

        if command[:2] == ["docker", "exec"]:
            readiness_calls += 1
            return subprocess.CompletedProcess(
                command,
                0 if readiness_calls == 2 else 1,
                stdout=(
                    "ready"
                    if readiness_calls == 2
                    else "starting"
                ),
                stderr="",
            )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="tests passed",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )
    monkeypatch.setattr(
        repository_test_runner.time,
        "sleep",
        sleep_calls.append,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is True
    assert readiness_calls == 2
    assert sleep_calls == [
        repository_test_runner
        .SERVICE_READINESS_POLL_INTERVAL_SECONDS
    ]
    assert any(
        command[:2] == ["docker", "run"]
        and "npm test" in command[-1]
        for command in commands
    )
    assert commands[-1][:3] == [
        "docker",
        "network",
        "rm",
    ]


def test_service_readiness_timeout_cleans_container_and_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository-readiness-timeout"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=(
            RepositoryTestNetworkMode.SERVICES_ONLY
        ),
        services=(
            RepositoryService(
                name="dependency",
                image="example/dependency:1",
                network_alias="dependency",
                readiness_command=("wait-ready",),
                startup_timeout_seconds=1,
            ),
        ),
    )
    commands: list[list[str]] = []
    current_time = 0.0
    sleep_calls: list[float] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        if command[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="true\n",
                stderr="",
            )

        if command[:2] == ["docker", "exec"]:
            raise subprocess.TimeoutExpired(
                command,
                timeout=1,
                output="waiting",
                stderr="not ready",
            )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    def fake_monotonic() -> float:
        return current_time

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        sleep_calls.append(seconds)
        current_time += seconds

    monkeypatch.setattr(
        repository_test_runner.time,
        "monotonic",
        fake_monotonic,
    )
    monkeypatch.setattr(
        repository_test_runner.time,
        "sleep",
        fake_sleep,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is False
    assert result.stage == "dependency_setup"
    assert result.timed_out is True
    assert sleep_calls == [0.5, 0.5]
    assert current_time == 1.0
    assert any(
        command[:3] == ["docker", "rm", "--force"]
        for command in commands
    )
    assert commands[-1][:3] == [
        "docker",
        "network",
        "rm",
    ]


def test_service_exit_during_readiness_fails_immediately_and_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository-readiness-exit"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=(
            RepositoryTestNetworkMode.SERVICES_ONLY
        ),
        services=(
            RepositoryService(
                name="dependency",
                image="example/dependency:1",
                network_alias="dependency",
                readiness_command=("wait-ready",),
                startup_timeout_seconds=5,
            ),
        ),
    )
    commands: list[list[str]] = []
    inspect_calls = 0

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal inspect_calls
        commands.append(command)

        if command[:2] == ["docker", "inspect"]:
            inspect_calls += 1
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "true\n"
                    if inspect_calls == 1
                    else "false\n"
                ),
                stderr="",
            )

        if command[:2] == ["docker", "exec"]:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="starting",
                stderr="",
            )

        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )
    monkeypatch.setattr(
        repository_test_runner.time,
        "sleep",
        lambda _seconds: None,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is False
    assert result.stage == "dependency_setup"
    assert "stopped before readiness" in result.stderr
    assert inspect_calls == 2
    assert not any(
        "npm test" in command[-1]
        for command in commands
    )
    assert any(
        command[:3] == ["docker", "rm", "--force"]
        for command in commands
    )
    assert commands[-1][:3] == [
        "docker",
        "network",
        "rm",
    ]


def test_explicit_internet_test_mode_does_not_disable_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "internet-repository"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=RepositoryTestNetworkMode.INTERNET,
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

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is True
    assert "--network" not in commands[1]


def test_repository_background_command_runs_inside_test_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "background-server-repository"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=RepositoryTestNetworkMode.NONE,
    )
    strategy = RepositoryTestStrategy(
        ecosystem=strategy.ecosystem,
        runtime_version=strategy.runtime_version,
        project_root=strategy.project_root,
        docker_image=strategy.docker_image,
        setup_commands=strategy.setup_commands,
        background_commands=(("npm", "run", "dev:test"),),
        pre_test_commands=(),
        test_commands=strategy.test_commands,
        environment_variables=strategy.environment_variables,
        test_network_mode=strategy.test_network_mode,
        services=strategy.services,
        evidence=strategy.evidence,
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

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is True
    assert all(command[0] == "docker" for command in commands)
    assert "npm run dev:test" in commands[1][-1]
    assert "npm run dev:test" in commands[1][-1].split(
        "npm test",
        1,
    )[0]
    assert "&" in commands[1][-1]


def test_background_pre_test_and_test_commands_execute_in_phase_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "command-phase-repository"
    repository.mkdir()
    base = make_service_strategy(
        network_mode=RepositoryTestNetworkMode.NONE,
    )
    strategy = RepositoryTestStrategy(
        ecosystem=base.ecosystem,
        runtime_version=base.runtime_version,
        project_root=base.project_root,
        docker_image=base.docker_image,
        setup_commands=base.setup_commands,
        background_commands=(
            ("npm", "run", "server:test"),
            ("node", "tests/fixture-server.js"),
        ),
        pre_test_commands=(
            ("npm", "run", "migrate:test"),
            ("npm", "run", "fixtures:test"),
        ),
        test_commands=(
            ("npm", "run", "test:unit"),
            ("npm", "run", "test:integration"),
        ),
        environment_variables=base.environment_variables,
        test_network_mode=base.test_network_mode,
        services=base.services,
        evidence=base.evidence,
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

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )
    shell_command = commands[1][-1]

    assert result.passed is True
    ordered_fragments = (
        "npm run server:test",
        "node tests/fixture-server.js",
        "npm run migrate:test",
        "npm run fixtures:test",
        "npm run test:unit",
        "npm run test:integration",
    )
    positions = tuple(
        shell_command.index(fragment)
        for fragment in ordered_fragments
    )
    assert positions == tuple(sorted(positions))
    assert (
        "npm run server:test "
        ">/tmp/contrigent-background-1.log 2>&1 &"
        in shell_command
    )
    assert "npm run migrate:test && npm run fixtures:test" in (
        shell_command
    )
    assert "npm run test:unit && npm run test:integration" in (
        shell_command
    )


def test_foreground_pre_test_failure_is_environment_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "pre-test-failure-repository"
    repository.mkdir()
    base = make_service_strategy(
        network_mode=RepositoryTestNetworkMode.NONE,
    )
    strategy = RepositoryTestStrategy(
        ecosystem=base.ecosystem,
        runtime_version=base.runtime_version,
        project_root=base.project_root,
        docker_image=base.docker_image,
        setup_commands=base.setup_commands,
        background_commands=(),
        pre_test_commands=(("npm", "run", "migrate:test"),),
        test_commands=base.test_commands,
        environment_variables=base.environment_variables,
        test_network_mode=base.test_network_mode,
        services=base.services,
        evidence=base.evidence,
    )
    calls = 0

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            command,
            (
                repository_test_runner
                .PRE_TEST_FAILURE_EXIT_CODE
                if calls == 2
                else 0
            ),
            stdout="",
            stderr=(
                "migration failed"
                if calls == 2
                else ""
            ),
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is False
    assert result.stage == "dependency_setup"
    assert "migration failed" in result.stderr


def test_actual_test_command_failure_remains_test_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "test-command-failure-repository"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=RepositoryTestNetworkMode.NONE,
    )
    calls = 0

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            command,
            1 if calls == 2 else 0,
            stdout="1 failed" if calls == 2 else "ready",
            stderr="",
        )

    monkeypatch.setattr(
        repository_test_runner.subprocess,
        "run",
        fake_run,
    )

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is False
    assert result.stage == "tests"
    assert "1 failed" in result.stdout


def test_test_timeout_cleans_service_container_and_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository-test-timeout"
    repository.mkdir()
    strategy = make_service_strategy(
        network_mode=(
            RepositoryTestNetworkMode.SERVICES_ONLY
        ),
        services=(
            RepositoryService(
                name="dependency",
                image="example/dependency:1",
                network_alias="dependency",
            ),
        ),
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)

        if command[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="true\n",
                stderr="",
            )

        if (
            command[:2] == ["docker", "run"]
            and "--detach" not in command
            and "npm test" in command[-1]
        ):
            marker_name = command[-1].split(
                "touch /test-environment/",
                1,
            )[1].split(" ", 1)[0]
            environment_mount = next(
                command[index + 1]
                for index, token in enumerate(command)
                if (
                    token == "--mount"
                    and "dst=/test-environment"
                    in command[index + 1]
                )
            )
            environment_source = next(
                part.removeprefix("src=")
                for part in environment_mount.split(",")
                if part.startswith("src=")
            )
            (Path(environment_source) / marker_name).touch()
            raise subprocess.TimeoutExpired(
                command,
                timeout=300,
                output="running",
                stderr="timed out",
            )

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

    result = (
        repository_test_runner
        .execute_repository_test_strategy(
            repository,
            strategy,
        )
    )

    assert result.passed is False
    assert result.stage == "tests"
    assert result.timed_out is True
    assert any(
        command[:3] == ["docker", "rm", "--force"]
        for command in commands
    )
    assert commands[-1][:3] == [
        "docker",
        "network",
        "rm",
    ]
