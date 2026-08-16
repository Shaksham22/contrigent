from pathlib import Path
import hashlib
import re
import shlex
import subprocess
import tempfile
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass

from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
)
from contrigent_api.services.approved_file_applier import (
    apply_approved_files,
)

from contrigent_api.services.docker_runtime_manager import (
    DockerRuntimeSession,
    start_docker_runtime_if_needed,
    stop_docker_runtime_if_started,
)


MAX_OUTPUT_CHARACTERS = 20_000
DEFAULT_TEST_PYTHON_VERSION = "3.12"

PYTHON_VERSION_PATTERN = re.compile(
    r"\bPython\s+(3\.\d+)\b",
    re.IGNORECASE,
)
PYTHON_FILE_VERSION_PATTERN = re.compile(
    r"^\s*(3\.\d+)(?:\.\d+)?\s*$"
)
REQUIRES_PYTHON_EXACT_PATTERN = re.compile(
    r"==\s*(3\.\d+)"
)
REQUIRES_PYTHON_LOWER_PATTERN = re.compile(
    r">=\s*(3\.\d+)"
)
REQUIRES_PYTHON_UPPER_PATTERN = re.compile(
    r"<\s*(3\.\d+)"
)
DOCKER_IMAGE = (
    "ghcr.io/astral-sh/uv:"
    "python3.12-bookworm-slim"
)
ProgressCallback = Callable[
    [int, str],
    None,
]

DEPENDENCY_SETUP_TIMEOUT_SECONDS = 300
TEST_TIMEOUT_SECONDS = 300

SUPPORTED_TEST_RUNNERS = (
    "nox",
    "tox",
    "pytest",
)
TEST_DEPENDENCY_NAMES = (
    "test",
    "testing",
    "dev",
)
CONTRIBUTING_FILE_NAMES = (
    "CONTRIBUTING.md",
    "CONTRIBUTING.rst",
    "CONTRIBUTING.txt",
    "contributing.md",
)
UNSAFE_COMMAND_CHARACTERS = (
    "&&",
    "||",
    ";",
    "|",
    ">",
    "<",
    "`",
    "$",
)
WORKFLOW_RUN_PATTERN = re.compile(
    r"^\s*(?:-\s*)?run\s*:\s*(.*?)\s*$"
)
WORKFLOW_KEY_PATTERN = re.compile(
    r"^([A-Za-z0-9_.-]+)\s*:\s*$"
)

REPOSITORY_SNAPSHOT_IGNORED_FOLDERS = {
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

PROTECTED_GENERATED_FILE_NAMES = {
    "Pipfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "uv.lock",
    "yarn.lock",
}

PROTECTED_NEW_FILE_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class RepositoryCommandSelection:
    dependency_setup_commands: tuple[
        tuple[str, ...],
        ...,
    ]
    test_command: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryTestStrategy:
    python_version: str
    dependency_setup_commands: tuple[str, ...]
    test_command: str
    evidence: tuple[str, ...]
    test_virtual_env: str | None = None


class RepositoryTestRunnerError(RuntimeError):
    pass


def trim_command_output(
    output: str,
) -> str:
    if len(output) <= MAX_OUTPUT_CHARACTERS:
        return output

    return (
        "[earlier output truncated]\n"
        + output[-MAX_OUTPUT_CHARACTERS:]
    )


def convert_timeout_output(
    output: str | bytes | None,
) -> str:
    if output is None:
        return ""

    if isinstance(output, bytes):
        return output.decode(
            "utf-8",
            errors="replace",
        )

    return output


def run_docker_command(
    command: list[str],
    timeout_seconds: int,
) -> tuple[
    int | None,
    str,
    str,
    bool,
]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        return (
            result.returncode,
            trim_command_output(
                result.stdout
            ),
            trim_command_output(
                result.stderr
            ),
            False,
        )

    except FileNotFoundError as error:
        raise RepositoryTestRunnerError(
            "Docker command was not found."
        ) from error

    except subprocess.TimeoutExpired as error:
        stdout = trim_command_output(
            convert_timeout_output(
                error.stdout
            )
        )

        stderr = trim_command_output(
            convert_timeout_output(
                error.stderr
            )
        )

        return (
            None,
            stdout,
            stderr,
            True,
        )


def build_docker_command(
    repository_path: Path,
    test_environment_path: Path,
    inner_command: list[str],
    *,
    disable_network: bool,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "1g",
        "--cpus",
        "1.0",
        "--pids-limit",
        "256",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=512m",
        "--env",
        "HOME=/tmp",
        "--env",
        (
            "UV_CACHE_DIR="
            "/test-environment/cache"
        ),
        "--env",
        (
            "UV_PYTHON_INSTALL_DIR="
            "/test-environment/python"
        ),
        "--env",
        (
            "POETRY_CACHE_DIR="
            "/test-environment/poetry-cache"
        ),
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--mount",
        build_bind_mount(
            repository_path,
            "/workspace",
            read_only=True,
        ),
        "--mount",
        build_bind_mount(
            test_environment_path,
            "/test-environment",
            read_only=False,
        ),
        "--workdir",
        "/workspace",
    ]

    if disable_network:
        command.extend(
            [
                "--network",
                "none",
            ]
        )

    command.extend(
        [
            DOCKER_IMAGE,
            *inner_command,
        ]
    )

    return command

def report_progress(
    progress_callback: ProgressCallback | None,
    percentage: int,
    message: str,
) -> None:
    if progress_callback is None:
        return

    progress_callback(
        percentage,
        message,
    )

def read_pyproject_data(
    repository_path: Path,
) -> dict:
    pyproject_path = (
        repository_path / "pyproject.toml"
    )

    if not pyproject_path.is_file():
        return {}

    try:
        with pyproject_path.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise RepositoryTestRunnerError(
            "Repository pyproject.toml is invalid."
        ) from error


def version_tuple(
    version: str,
) -> tuple[int, int]:
    major, minor = version.split(".", 1)
    return int(major), int(minor)


def select_test_python_version(
    repository_path: Path,
    issue_text: str | None = None,
) -> str:
    python_version, _evidence = (
        select_test_python_version_with_evidence(
            repository_path,
            issue_text,
        )
    )

    return python_version


def select_test_python_version_with_evidence(
    repository_path: Path,
    issue_text: str | None = None,
) -> tuple[str, str]:
    python_version_path = (
        repository_path / ".python-version"
    )

    if python_version_path.is_file():
        configured_versions = (
            python_version_path.read_text(
                encoding="utf-8"
            )
            .splitlines()
        )

        if configured_versions:
            match = PYTHON_FILE_VERSION_PATTERN.match(
                configured_versions[0].strip()
            )

            if match is not None:
                return (
                    match.group(1),
                    ".python-version",
                )

    pyproject_data = read_pyproject_data(
        repository_path
    )
    project = pyproject_data.get(
        "project",
        {},
    )

    if isinstance(project, dict):
        requires_python = project.get(
            "requires-python"
        )

        if isinstance(requires_python, str):
            exact_match = (
                REQUIRES_PYTHON_EXACT_PATTERN.search(
                    requires_python
                )
            )

            if exact_match is not None:
                return (
                    exact_match.group(1),
                    "pyproject.toml requires-python",
                )

            lower_match = (
                REQUIRES_PYTHON_LOWER_PATTERN.search(
                    requires_python
                )
            )
            upper_match = (
                REQUIRES_PYTHON_UPPER_PATTERN.search(
                    requires_python
                )
            )

            default_tuple = version_tuple(
                DEFAULT_TEST_PYTHON_VERSION
            )

            if lower_match is not None:
                lower_version = (
                    lower_match.group(1)
                )
                lower_tuple = version_tuple(
                    lower_version
                )

                if lower_tuple > default_tuple:
                    return (
                        lower_version,
                        "pyproject.toml requires-python",
                    )

                if upper_match is not None:
                    upper_tuple = version_tuple(
                        upper_match.group(1)
                    )

                    if default_tuple >= upper_tuple:
                        return (
                            lower_version,
                            (
                                "pyproject.toml "
                                "requires-python"
                            ),
                        )

                return (
                    DEFAULT_TEST_PYTHON_VERSION,
                    "pyproject.toml requires-python",
                )

    if issue_text:
        match = PYTHON_VERSION_PATTERN.search(
            issue_text
        )

        if match is not None:
            return (
                match.group(1),
                "issue text",
            )

    return (
        DEFAULT_TEST_PYTHON_VERSION,
        "Contrigent default",
    )


def tokenize_safe_command(
    candidate: str,
) -> list[str] | None:
    candidate = candidate.strip()

    if candidate.startswith("run:"):
        candidate = candidate[4:].strip()

    if (
        len(candidate) >= 2
        and candidate[0] == candidate[-1]
        and candidate[0] in {"'", '"'}
    ):
        candidate = candidate[1:-1].strip()

    if not candidate:
        return None

    if any(
        character in candidate
        for character in UNSAFE_COMMAND_CHARACTERS
    ):
        return None

    try:
        tokens = shlex.split(candidate)
    except ValueError:
        return None

    if not tokens:
        return None

    return tokens


def unwrap_supported_test_command(
    tokens: list[str] | tuple[str, ...],
) -> list[str]:
    unwrapped = list(tokens)

    if (
        len(unwrapped) >= 3
        and unwrapped[0] in {"uv", "poetry"}
        and unwrapped[1] == "run"
        and not unwrapped[2].startswith("-")
    ):
        unwrapped = unwrapped[2:]

    if (
        len(unwrapped) >= 2
        and unwrapped[0] == "tox"
        and unwrapped[1] == "run"
    ):
        unwrapped = [
            "tox",
            *unwrapped[2:],
        ]

    return unwrapped


def normalize_supported_test_command(
    candidate: str,
) -> list[str] | None:
    tokens = tokenize_safe_command(
        candidate
    )

    if tokens is None:
        return None

    unwrapped = unwrap_supported_test_command(
        tokens
    )

    if unwrapped[0] in SUPPORTED_TEST_RUNNERS:
        return tokens

    if (
        len(unwrapped) >= 3
        and unwrapped[0] in {"python", "python3"}
        and unwrapped[1] == "-m"
        and unwrapped[2] in SUPPORTED_TEST_RUNNERS
    ):
        return tokens

    return None


def normalize_supported_setup_command(
    candidate: str,
) -> list[str] | None:
    tokens = tokenize_safe_command(
        candidate
    )

    if tokens is None:
        return None

    supported_prefixes = (
        ("uv", "sync"),
        ("uv", "pip", "install"),
        ("uv", "venv"),
        ("uv", "python", "install"),
        ("uv", "lock"),
        ("uvx", "poetry", "install"),
        ("uvx", "poetry", "lock"),
        ("poetry", "install"),
        ("poetry", "lock"),
        ("python", "-m", "pip", "install"),
        ("python3", "-m", "pip", "install"),
        ("pip", "install"),
        ("pip3", "install"),
    )

    if any(
        tuple(tokens[:len(prefix)]) == prefix
        for prefix in supported_prefixes
    ):
        return tokens

    if (
        tokens[0] == "nox"
        and "--install-only" in tokens[1:]
    ):
        return tokens

    if (
        tokens[0] == "tox"
        and "--notest" in tokens[1:]
    ):
        return tokens

    return None


def setup_command_installs_dependencies(
    tokens: list[str],
) -> bool:
    dependency_install_prefixes = (
        ("uv", "sync"),
        ("uv", "pip", "install"),
        ("uvx", "poetry", "install"),
        ("poetry", "install"),
        ("python", "-m", "pip", "install"),
        ("python3", "-m", "pip", "install"),
        ("pip", "install"),
        ("pip3", "install"),
    )

    return any(
        tuple(tokens[:len(prefix)]) == prefix
        for prefix in dependency_install_prefixes
    )


def extract_documented_command_candidates(
    text: str,
) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []

    for line_number, line in enumerate(
        text.splitlines(),
        start=1,
    ):
        inline_candidates = re.findall(
            r"`([^`\n]+)`",
            line,
        )

        candidates.extend(
            (candidate, line_number)
            for candidate in inline_candidates
        )
        candidates.append(
            (line.strip(), line_number)
        )

    return candidates


def extract_workflow_command_groups(
    text: str,
) -> list[
    tuple[str, list[tuple[str, int]]]
]:
    lines = text.splitlines()
    groups: dict[
        str,
        list[tuple[str, int]],
    ] = {}
    jobs_indent: int | None = None
    current_group = "workflow"
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indentation = (
            len(line) - len(line.lstrip())
        )

        if stripped == "jobs:":
            jobs_indent = indentation
            current_group = "workflow"
            index += 1
            continue

        if jobs_indent is not None:
            if (
                stripped
                and indentation <= jobs_indent
                and stripped != "jobs:"
            ):
                jobs_indent = None
                current_group = "workflow"
            elif indentation == jobs_indent + 2:
                key_match = WORKFLOW_KEY_PATTERN.match(
                    stripped
                )

                if key_match is not None:
                    current_group = key_match.group(1)

        run_match = WORKFLOW_RUN_PATTERN.match(
            line
        )

        if run_match is None:
            index += 1
            continue

        run_value = run_match.group(1).strip()
        group_candidates = groups.setdefault(
            current_group,
            [],
        )

        if run_value not in {"|", ">", "|-", ">-"}:
            group_candidates.append(
                (run_value, index + 1)
            )
            index += 1
            continue

        block_indentation = indentation
        index += 1

        while index < len(lines):
            block_line = lines[index]
            block_stripped = block_line.strip()
            current_indentation = (
                len(block_line)
                - len(block_line.lstrip())
            )

            if (
                block_stripped
                and current_indentation
                <= block_indentation
            ):
                break

            if block_stripped:
                group_candidates.append(
                    (block_stripped, index + 1)
                )

            index += 1

    return list(groups.items())


def select_commands_from_candidates(
    candidates: list[tuple[str, int]],
    evidence_name: str,
) -> RepositoryCommandSelection | None:
    setup_commands: list[tuple[str, ...]] = []
    setup_evidence: list[str] = []
    dependency_install_seen = False
    first_test: RepositoryCommandSelection | None = None

    for candidate, line_number in candidates:
        setup_command = (
            normalize_supported_setup_command(
                candidate
            )
        )

        if setup_command is not None:
            if setup_command_installs_dependencies(
                setup_command
            ):
                dependency_install_seen = True

            setup_commands.append(
                tuple(setup_command)
            )
            setup_evidence.append(
                (
                    f"{evidence_name}:{line_number} "
                    "setup: "
                    f"{shlex.join(setup_command)}"
                )
            )
            continue

        test_command = (
            normalize_supported_test_command(
                candidate
            )
        )

        if test_command is None:
            continue

        selection = RepositoryCommandSelection(
            dependency_setup_commands=(
                tuple(setup_commands)
                if dependency_install_seen
                else ()
            ),
            test_command=tuple(test_command),
            evidence=(
                *(
                    setup_evidence
                    if dependency_install_seen
                    else []
                ),
                (
                    f"{evidence_name}:{line_number} "
                    "tests: "
                    f"{shlex.join(test_command)}"
                ),
            ),
        )

        if dependency_install_seen:
            return selection

        if first_test is None:
            first_test = selection

    return first_test


def detect_workflow_command_selection(
    repository_path: Path,
) -> RepositoryCommandSelection | None:
    workflows_path = (
        repository_path
        / ".github"
        / "workflows"
    )
    first_test_only: (
        RepositoryCommandSelection | None
    ) = None

    if workflows_path.is_dir():
        workflow_paths = sorted(
            [
                *workflows_path.glob("*.yml"),
                *workflows_path.glob("*.yaml"),
            ]
        )

        for workflow_path in workflow_paths:
            command_groups = (
                extract_workflow_command_groups(
                workflow_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )
            )

            relative_path = workflow_path.relative_to(
                repository_path
            )

            for group_name, candidates in command_groups:
                selection = select_commands_from_candidates(
                    candidates,
                    f"{relative_path} [{group_name}]",
                )

                if selection is None:
                    continue

                if selection.dependency_setup_commands:
                    return selection

                if first_test_only is None:
                    first_test_only = selection

    return first_test_only


def detect_contributing_command_selection(
    repository_path: Path,
) -> RepositoryCommandSelection | None:
    for file_name in CONTRIBUTING_FILE_NAMES:
        contributing_path = (
            repository_path / file_name
        )

        if not contributing_path.is_file():
            continue

        candidates = (
            extract_documented_command_candidates(
                contributing_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )
        )
        selection = select_commands_from_candidates(
            candidates,
            file_name,
        )

        if selection is not None:
            return selection

    return None


def test_command_specificity(
    test_command: tuple[str, ...],
) -> int:
    return len(
        unwrap_supported_test_command(
            test_command
        )
    )


def detect_evidenced_command_selection(
    repository_path: Path,
) -> RepositoryCommandSelection | None:
    workflow_selection = (
        detect_workflow_command_selection(
            repository_path
        )
    )

    if (
        workflow_selection is not None
        and workflow_selection
        .dependency_setup_commands
    ):
        return workflow_selection

    contributing_selection = (
        detect_contributing_command_selection(
            repository_path
        )
    )

    if contributing_selection is None:
        return workflow_selection

    if workflow_selection is None:
        return contributing_selection

    if contributing_selection.dependency_setup_commands:
        return contributing_selection

    if (
        get_test_runner(
            workflow_selection.test_command
        )
        == get_test_runner(
            contributing_selection.test_command
        )
        and test_command_specificity(
            workflow_selection.test_command
        )
        > test_command_specificity(
            contributing_selection.test_command
        )
    ):
        return workflow_selection

    return contributing_selection


def detect_native_command_selection(
    repository_path: Path,
    pyproject_data: dict,
) -> RepositoryCommandSelection:

    if (
        repository_path / "noxfile.py"
    ).is_file():
        return RepositoryCommandSelection(
            dependency_setup_commands=(),
            test_command=("nox",),
            evidence=("noxfile.py",),
        )

    tool = pyproject_data.get(
        "tool",
        {},
    )

    if (
        (repository_path / "tox.ini").is_file()
        or (
            isinstance(tool, dict)
            and isinstance(
                tool.get("tox"),
                dict,
            )
        )
    ):
        evidence = (
            "tox.ini"
            if (repository_path / "tox.ini").is_file()
            else "pyproject.toml [tool.tox]"
        )
        return RepositoryCommandSelection(
            dependency_setup_commands=(),
            test_command=("tox",),
            evidence=(evidence,),
        )

    if (
        (repository_path / "pytest.ini").is_file()
        or (repository_path / "tests").is_dir()
        or (
            isinstance(tool, dict)
            and isinstance(
                tool.get("pytest"),
                dict,
            )
        )
    ):
        if (repository_path / "pytest.ini").is_file():
            evidence = "pytest.ini"
        elif (repository_path / "tests").is_dir():
            evidence = "tests/"
        else:
            evidence = (
                "pyproject.toml "
                "[tool.pytest.ini_options]"
            )

        return RepositoryCommandSelection(
            dependency_setup_commands=(),
            test_command=(
                "pytest",
                "-v",
                "-p",
                "no:cacheprovider",
            ),
            evidence=(evidence,),
        )

    raise RepositoryTestRunnerError(
        "Automatic repository testing could not "
        "identify a supported repository-native "
        "test command."
    )


def detect_repository_test_command(
    repository_path: Path,
    pyproject_data: dict,
) -> list[str]:
    selection = (
        detect_evidenced_command_selection(
            repository_path
        )
        or detect_native_command_selection(
            repository_path,
            pyproject_data,
        )
    )

    return list(selection.test_command)


def get_test_runner(
    test_command: list[str] | tuple[str, ...],
) -> str:
    unwrapped = unwrap_supported_test_command(
        test_command
    )

    if unwrapped[0] in SUPPORTED_TEST_RUNNERS:
        return unwrapped[0]

    if (
        len(unwrapped) >= 3
        and unwrapped[0] in {"python", "python3"}
        and unwrapped[1] == "-m"
        and unwrapped[2] in SUPPORTED_TEST_RUNNERS
    ):
        return unwrapped[2]

    raise RepositoryTestRunnerError(
        "Unsupported repository test command."
    )


def detect_dependency_manager(
    repository_path: Path,
    pyproject_data: dict,
) -> str:
    tool = pyproject_data.get(
        "tool",
        {},
    )

    if (
        (repository_path / "poetry.lock").is_file()
        or (
            isinstance(tool, dict)
            and isinstance(
                tool.get("poetry"),
                dict,
            )
        )
    ):
        return "poetry"

    if (
        (repository_path / "uv.lock").is_file()
        or "dependency-groups" in pyproject_data
        or (
            isinstance(tool, dict)
            and isinstance(
                tool.get("uv"),
                dict,
            )
        )
    ):
        return "uv"

    return "generic"


def find_dependency_target(
    pyproject_data: dict,
    dependency_manager: str,
) -> tuple[str, str] | None:
    if dependency_manager == "poetry":
        tool = pyproject_data.get(
            "tool",
            {},
        )
        poetry = (
            tool.get("poetry", {})
            if isinstance(tool, dict)
            else {}
        )
        poetry_groups = (
            poetry.get("group", {})
            if isinstance(poetry, dict)
            else {}
        )

        if isinstance(poetry_groups, dict):
            for name in TEST_DEPENDENCY_NAMES:
                if name in poetry_groups:
                    return "group", name

    dependency_groups = pyproject_data.get(
        "dependency-groups",
        {},
    )

    if isinstance(dependency_groups, dict):
        for name in TEST_DEPENDENCY_NAMES:
            if name in dependency_groups:
                return "group", name

    project = pyproject_data.get(
        "project",
        {},
    )
    optional_dependencies = (
        project.get(
            "optional-dependencies",
            {},
        )
        if isinstance(project, dict)
        else {}
    )

    if isinstance(optional_dependencies, dict):
        for name in TEST_DEPENDENCY_NAMES:
            if name in optional_dependencies:
                return "extra", name

    return None


def build_pytest_dependency_setup(
    repository_path: Path,
    pyproject_data: dict,
    python_version: str,
) -> tuple[str, str, str]:
    dependency_manager = (
        detect_dependency_manager(
            repository_path,
            pyproject_data,
        )
    )
    dependency_target = find_dependency_target(
        pyproject_data,
        dependency_manager,
    )

    if dependency_manager == "poetry":
        install_options = ""

        if dependency_target is not None:
            target_kind, target_name = (
                dependency_target
            )

            if target_kind == "group":
                install_options = (
                    f" --with {shlex.quote(target_name)}"
                )
            else:
                install_options = (
                    f" --extras {shlex.quote(target_name)}"
                )

        dependency_setup = (
            "export "
            "POETRY_VIRTUALENVS_IN_PROJECT=true && "
            f"uv python install {python_version} && "
            "PYTHON_BIN=\"$(uv python find "
            f"{python_version})\" && "
            "uvx poetry env use \"$PYTHON_BIN\" && "
            "uvx poetry lock && "
            "uvx poetry install"
            f"{install_options} "
            "--no-interaction --no-ansi"
        )
        test_virtual_env = (
            "/test-environment/workspace/.venv"
        )
        test_python = (
            f"{test_virtual_env}/bin/python"
        )

        return (
            dependency_setup,
            test_virtual_env,
            test_python,
        )

    if dependency_manager == "uv":
        install_options = ""

        if dependency_target is not None:
            target_kind, target_name = (
                dependency_target
            )
            option = (
                "--group"
                if target_kind == "group"
                else "--extra"
            )
            install_options = (
                f" {option} {shlex.quote(target_name)}"
            )

        dependency_setup = (
            f"uv python install {python_version} && "
            f"uv sync --python {python_version}"
            f"{install_options}"
        )
        test_virtual_env = (
            "/test-environment/workspace/.venv"
        )
        test_python = (
            f"{test_virtual_env}/bin/python"
        )

        return (
            dependency_setup,
            test_virtual_env,
            test_python,
        )

    test_virtual_env = (
        "/test-environment/venv"
    )
    test_python = (
        f"{test_virtual_env}/bin/python"
    )
    install_arguments = [
        "uv",
        "pip",
        "install",
        "--python",
        test_python,
    ]

    dependency_target = find_dependency_target(
        pyproject_data,
        dependency_manager,
    )

    if (
        (repository_path / "pyproject.toml").is_file()
        or (repository_path / "setup.py").is_file()
        or (repository_path / "setup.cfg").is_file()
    ):
        if (
            dependency_target is not None
            and dependency_target[0] == "extra"
        ):
            install_arguments.extend(
                [
                    "-e",
                    f".[{dependency_target[1]}]",
                ]
            )
        else:
            install_arguments.extend(
                [
                    "-e",
                    ".",
                ]
            )

    requirements_path = None

    for file_name in (
        "requirements-test.txt",
        "requirements-testing.txt",
        "requirements-dev.txt",
        "requirements.txt",
    ):
        candidate_path = (
            repository_path / file_name
        )

        if candidate_path.is_file():
            requirements_path = file_name
            break

    if requirements_path is not None:
        install_arguments.extend(
            [
                "-r",
                requirements_path,
            ]
        )

    install_arguments.append("pytest")

    dependency_setup = (
        f"uv python install {python_version} && "
        f"uv venv --python {python_version} "
        f"{test_virtual_env} && "
        + shlex.join(install_arguments)
    )

    return (
        dependency_setup,
        test_virtual_env,
        test_python,
    )


def build_native_runner_commands(
    test_runner: str,
    test_command: list[str],
    python_version: str,
) -> tuple[str, str, str, str]:
    runner_virtual_env = (
        "/test-environment/runner-venv"
    )
    runner_executable = (
        f"{runner_virtual_env}/bin/{test_runner}"
    )
    unwrapped_command = (
        unwrap_supported_test_command(
            test_command
        )
    )

    if (
        len(unwrapped_command) >= 3
        and unwrapped_command[0]
        in {"python", "python3"}
        and unwrapped_command[1] == "-m"
    ):
        runner_arguments = unwrapped_command[3:]
    else:
        runner_arguments = unwrapped_command[1:]

    bootstrap = (
        f"uv python install {python_version} && "
        f"uv venv --python {python_version} "
        f"{runner_virtual_env} && "
        "uv pip install --python "
        f"{runner_virtual_env}/bin/python "
        f"{test_runner}"
    )

    if test_runner == "nox":
        setup_tokens = [
            runner_executable,
            "--install-only",
            *runner_arguments,
        ]
        test_tokens = [
            runner_executable,
            "--reuse-existing-virtualenvs",
            "--no-install",
            *runner_arguments,
        ]
    else:
        setup_tokens = [
            runner_executable,
            "--notest",
            *runner_arguments,
        ]
        test_tokens = [
            runner_executable,
            "--skip-env-install",
            *runner_arguments,
        ]

    return (
        bootstrap + " && " + shlex.join(setup_tokens),
        shlex.join(test_tokens),
        runner_virtual_env,
        f"{runner_virtual_env}/bin/python",
    )


def materialize_evidenced_setup_commands(
    setup_commands: tuple[tuple[str, ...], ...],
    python_version: str,
    test_runner: str,
) -> tuple[list[str], str | None]:
    workspace_environment = (
        "/test-environment/workspace/.venv"
    )
    isolated_environment = (
        "/test-environment/repository-venv"
    )
    persistent_environment = isolated_environment

    for setup_command in setup_commands:
        tokens = list(setup_command)

        if (
            tokens[:2] == ["uv", "sync"]
            or tokens[:2] == ["poetry", "install"]
            or tokens[:3]
            == ["uvx", "poetry", "install"]
        ):
            persistent_environment = (
                workspace_environment
            )
            break

    persistent_python = (
        f"{persistent_environment}/bin/python"
    )
    materialized_commands = [
        (
            "uv python install "
            f"{shlex.quote(python_version)}"
        )
    ]

    if persistent_environment == isolated_environment:
        materialized_commands.append(
            shlex.join(
                [
                    "uv",
                    "venv",
                    "--python",
                    python_version,
                    persistent_environment,
                ]
            )
        )

    poetry_environment_selected = False

    for setup_command in setup_commands:
        tokens = list(setup_command)

        if (
            tokens[:3]
            == ["uv", "python", "install"]
            or tokens[:2] == ["uv", "venv"]
        ):
            continue

        if tokens[:2] == ["uv", "sync"]:
            sync_arguments: list[str] = []
            skip_next = False

            for token in tokens[2:]:
                if skip_next:
                    skip_next = False
                    continue

                if token in {"--python", "-p"}:
                    skip_next = True
                    continue

                if (
                    token.startswith("--python=")
                    or token.startswith("-p=")
                ):
                    continue

                sync_arguments.append(token)

            sync_command = shlex.join(
                [
                    "uv",
                    "sync",
                    "--python",
                    python_version,
                    *sync_arguments,
                ]
            )

            if (
                persistent_environment
                != workspace_environment
            ):
                sync_command = (
                    "UV_PROJECT_ENVIRONMENT="
                    f"{shlex.quote(persistent_environment)} "
                    f"{sync_command}"
                )

            materialized_commands.append(
                sync_command
            )
            continue

        if tokens[:3] == ["uv", "pip", "install"]:
            install_arguments = [
                token
                for token in tokens[3:]
                if token not in {"--system"}
            ]
            normalized_arguments: list[str] = []
            skip_next = False

            for token in install_arguments:
                if skip_next:
                    skip_next = False
                    continue

                if token in {"--python", "-p"}:
                    skip_next = True
                    continue

                if (
                    token.startswith("--python=")
                    or token.startswith("-p=")
                ):
                    continue

                normalized_arguments.append(token)

            materialized_commands.append(
                shlex.join(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        persistent_python,
                        *normalized_arguments,
                    ]
                )
            )
            continue

        pip_arguments: list[str] | None = None

        if tokens[:2] in (
            ["pip", "install"],
            ["pip3", "install"],
        ):
            pip_arguments = tokens[2:]
        elif tokens[:4] in (
            ["python", "-m", "pip", "install"],
            ["python3", "-m", "pip", "install"],
        ):
            pip_arguments = tokens[4:]

        if pip_arguments is not None:
            materialized_commands.append(
                shlex.join(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        persistent_python,
                        *pip_arguments,
                    ]
                )
            )
            continue

        if (
            tokens[:2] == ["poetry", "install"]
            or tokens[:3]
            == ["uvx", "poetry", "install"]
        ):
            if not poetry_environment_selected:
                materialized_commands.append(
                    (
                        "PYTHON_BIN=\"$(uv python find "
                        f"{shlex.quote(python_version)})\" && "
                        "POETRY_VIRTUALENVS_IN_PROJECT=true "
                        "uvx poetry env use \"$PYTHON_BIN\""
                    )
                )
                poetry_environment_selected = True

            materialized_commands.append(
                "POETRY_VIRTUALENVS_IN_PROJECT=true "
                + shlex.join(tokens)
            )
            continue

        materialized_commands.append(
            shlex.join(tokens)
        )

    return (
        materialized_commands,
        (
            f"{persistent_environment}"
            f"/bin/{test_runner}"
        ),
    )


def build_repository_owned_native_commands(
    test_runner: str,
    test_command: list[str],
    runner_executable: str | None = None,
) -> tuple[str, str]:
    unwrapped_command = (
        unwrap_supported_test_command(
            test_command
        )
    )

    if (
        len(unwrapped_command) >= 3
        and unwrapped_command[0]
        in {"python", "python3"}
        and unwrapped_command[1] == "-m"
    ):
        runner_arguments = unwrapped_command[3:]
    else:
        runner_arguments = unwrapped_command[1:]

    command_prefix: list[str] = []
    runner_token = test_runner

    if runner_executable is not None:
        runner_token = runner_executable
    elif (
        len(test_command) >= 3
        and test_command[0] in {"uv", "poetry"}
        and test_command[1] == "run"
    ):
        command_prefix = list(test_command[:2])
    elif (
        len(test_command) >= 3
        and test_command[0] in {"python", "python3"}
        and test_command[1] == "-m"
    ):
        command_prefix = list(test_command[:2])

    if test_runner == "nox":
        setup_tokens = [
            *command_prefix,
            runner_token,
            "--install-only",
            *runner_arguments,
        ]
        test_tokens = [
            *command_prefix,
            runner_token,
            "--reuse-existing-virtualenvs",
            "--no-install",
            *runner_arguments,
        ]
    else:
        setup_tokens = [
            *command_prefix,
            runner_token,
            "--notest",
            *runner_arguments,
        ]
        test_tokens = [
            *command_prefix,
            runner_token,
            "--skip-env-install",
            *runner_arguments,
        ]

    return (
        shlex.join(setup_tokens),
        shlex.join(test_tokens),
    )


def build_persistent_test_command(
    test_command: list[str],
    runner_executable: str,
) -> str:
    unwrapped_command = (
        unwrap_supported_test_command(
            test_command
        )
    )

    if (
        len(unwrapped_command) >= 3
        and unwrapped_command[0]
        in {"python", "python3"}
        and unwrapped_command[1] == "-m"
    ):
        runner_arguments = unwrapped_command[3:]
    else:
        runner_arguments = unwrapped_command[1:]

    if get_test_runner(test_command) == "pytest":
        environment_path = runner_executable.rsplit(
            "/",
            2,
        )[0]
        return shlex.join(
            [
                f"{environment_path}/bin/python",
                "-m",
                "pytest",
                *runner_arguments,
            ]
        )

    return shlex.join(
        [
            runner_executable,
            *runner_arguments,
        ]
    )


def build_pytest_test_command(
    test_command: list[str],
    test_python: str,
) -> str:
    unwrapped_command = (
        unwrap_supported_test_command(
            test_command
        )
    )

    if unwrapped_command[0] == "pytest":
        runner_arguments = unwrapped_command[1:]
    else:
        runner_arguments = unwrapped_command[3:]

    effective_command = [
        test_python,
        "-m",
        "pytest",
        *runner_arguments,
    ]

    return shlex.join(
        effective_command
    )


def build_test_runner_readiness_command(
    test_command: str,
) -> str:
    command_tokens = shlex.split(
        test_command
    )

    if (
        len(command_tokens) >= 3
        and command_tokens[1] == "-m"
        and command_tokens[2]
        in SUPPORTED_TEST_RUNNERS
    ):
        return shlex.join(
            [
                command_tokens[0],
                "-m",
                command_tokens[2],
                "--version",
            ]
        )

    runner_executable = command_tokens[0]
    runner_name = Path(
        runner_executable
    ).name

    if runner_name in SUPPORTED_TEST_RUNNERS:
        return shlex.join(
            [
                runner_executable,
                "--version",
            ]
        )

    raise RepositoryTestRunnerError(
        "Unsupported repository test runner "
        "readiness check."
    )


def build_test_environment_command(
    test_virtual_env: str | None,
) -> str:
    if test_virtual_env is None:
        return ""

    return (
        "export VIRTUAL_ENV="
        f'"{test_virtual_env}" && '
        'export PATH="$VIRTUAL_ENV/bin:$PATH" && '
    )


def repository_snapshot_ignores_path(
    relative_path: Path,
) -> bool:
    return any(
        part in REPOSITORY_SNAPSHOT_IGNORED_FOLDERS
        or part.endswith(".egg-info")
        for part in relative_path.parts
    )


def hash_file_contents(
    file_path: Path,
) -> str:
    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        while chunk := file.read(
            1024 * 1024
        ):
            digest.update(chunk)

    return digest.hexdigest()


def snapshot_repository_files(
    repository_path: Path,
) -> dict[str, str]:
    repository_root = repository_path.resolve()
    snapshot: dict[str, str] = {}

    for file_path in sorted(
        repository_root.rglob("*")
    ):
        if (
            not file_path.is_file()
            or file_path.is_symlink()
        ):
            continue

        relative_path = file_path.relative_to(
            repository_root
        )

        if repository_snapshot_ignores_path(
            relative_path
        ):
            continue

        snapshot[
            relative_path.as_posix()
        ] = hash_file_contents(
            file_path
        )

    return snapshot


def is_protected_new_repository_file(
    relative_path: str,
) -> bool:
    path = Path(relative_path)

    return (
        path.name in PROTECTED_GENERATED_FILE_NAMES
        or path.name.startswith("requirements")
        or path.suffix.lower()
        in PROTECTED_NEW_FILE_SUFFIXES
    )


def find_repository_setup_mutations(
    before: dict[str, str],
    repository_path: Path,
) -> list[str]:
    after = snapshot_repository_files(
        repository_path
    )
    mutations = {
        path
        for path, digest in before.items()
        if after.get(path) != digest
    }

    mutations.update(
        path
        for path in after.keys() - before.keys()
        if is_protected_new_repository_file(
            path
        )
    )

    return sorted(mutations)


def describe_dependency_setup_evidence(
    repository_path: Path,
    pyproject_data: dict,
) -> str:
    dependency_manager = detect_dependency_manager(
        repository_path,
        pyproject_data,
    )

    if dependency_manager == "poetry":
        if (
            repository_path / "poetry.lock"
        ).is_file():
            return "poetry.lock and pyproject.toml"

        return "pyproject.toml [tool.poetry]"

    if dependency_manager == "uv":
        if (
            repository_path / "uv.lock"
        ).is_file():
            return "uv.lock and pyproject.toml"

        return "pyproject.toml uv dependency configuration"

    for file_name in (
        "requirements-test.txt",
        "requirements-testing.txt",
        "requirements-dev.txt",
        "requirements.txt",
    ):
        if (
            repository_path / file_name
        ).is_file():
            return file_name

    return "Python packaging metadata"


def build_repository_test_strategy(
    repository_path: Path,
    issue_text: str | None = None,
) -> RepositoryTestStrategy:
    pyproject_data = read_pyproject_data(
        repository_path
    )
    command_selection = (
        detect_evidenced_command_selection(
            repository_path
        )
        or detect_native_command_selection(
            repository_path,
            pyproject_data,
        )
    )
    python_version, python_evidence = (
        select_test_python_version_with_evidence(
            repository_path,
            issue_text,
        )
    )
    test_command_tokens = list(
        command_selection.test_command
    )
    test_runner = get_test_runner(
        test_command_tokens
    )
    evidence = (
        f"Python {python_version}: {python_evidence}",
        *command_selection.evidence,
    )

    if command_selection.dependency_setup_commands:
        (
            dependency_setup_commands,
            persistent_runner,
        ) = materialize_evidenced_setup_commands(
            command_selection.dependency_setup_commands,
            python_version,
            test_runner,
        )
        native_test_command = shlex.join(
            command_selection.test_command
        )

        if test_runner in {"nox", "tox"}:
            (
                native_environment_setup,
                native_test_command,
            ) = build_repository_owned_native_commands(
                test_runner,
                test_command_tokens,
                persistent_runner,
            )
            dependency_setup_commands.append(
                native_environment_setup
            )
        elif persistent_runner is not None:
            native_test_command = (
                build_persistent_test_command(
                    test_command_tokens,
                    persistent_runner,
                )
            )

        return RepositoryTestStrategy(
            python_version=python_version,
            dependency_setup_commands=tuple(
                dependency_setup_commands
            ),
            test_command=native_test_command,
            evidence=evidence,
        )

    setup_evidence = (
        describe_dependency_setup_evidence(
            repository_path,
            pyproject_data,
        )
    )

    if test_runner in {"nox", "tox"}:
        (
            dependency_setup,
            native_test_command,
            _runner_virtual_env,
            _runner_python,
        ) = build_native_runner_commands(
            test_runner,
            test_command_tokens,
            python_version,
        )

        return RepositoryTestStrategy(
            python_version=python_version,
            dependency_setup_commands=(
                dependency_setup,
            ),
            test_command=native_test_command,
            evidence=(
                *evidence,
                (
                    "Generated isolated "
                    f"{test_runner} runner environment"
                ),
            ),
        )

    (
        dependency_setup,
        test_virtual_env,
        test_python,
    ) = build_pytest_dependency_setup(
        repository_path,
        pyproject_data,
        python_version,
    )

    return RepositoryTestStrategy(
        python_version=python_version,
        dependency_setup_commands=(
            dependency_setup,
        ),
        test_command=build_pytest_test_command(
            test_command_tokens,
            test_python,
        ),
        evidence=(
            *evidence,
            f"Dependency setup: {setup_evidence}",
        ),
        test_virtual_env=test_virtual_env,
    )

def run_repository_tests(
    repository_path: Path,
    progress_callback: ProgressCallback | None = None,
    proposed_files: list[FileReplacement] | None = None,
    issue_text: str | None = None,
) -> RepositoryTestResult:
    repository_path = repository_path.resolve()

    if not repository_path.is_dir():
        raise RepositoryTestRunnerError(
            "Repository folder does not exist."
        )

    strategy = build_repository_test_strategy(
        repository_path,
        issue_text,
    )

    return execute_repository_test_strategy(
        repository_path,
        strategy,
        progress_callback=progress_callback,
        proposed_files=proposed_files,
    )


def execute_repository_test_strategy(
    repository_path: Path,
    strategy: RepositoryTestStrategy,
    progress_callback: ProgressCallback | None = None,
    proposed_files: list[FileReplacement] | None = None,
    *,
    protect_repository_files: bool = False,
) -> RepositoryTestResult:
    report_progress(
    progress_callback,
    5,
    "Checking Docker",)
    repository_path = (
        repository_path.resolve()
    )

    if not repository_path.is_dir():
        raise RepositoryTestRunnerError(
            "Repository folder does not exist."
        )

    if protect_repository_files and proposed_files:
        raise RepositoryTestRunnerError(
            "Protected repository verification cannot "
            "apply candidate files."
        )

    repository_snapshot = (
        snapshot_repository_files(
            repository_path
        )
        if protect_repository_files
        else None
    )
    dependency_setup = " && ".join(
        strategy.dependency_setup_commands
    )
    native_test_command = strategy.test_command
    test_environment_command = (
        build_test_environment_command(
            strategy.test_virtual_env
        )
    )
    runner_readiness_command = (
        build_test_runner_readiness_command(
            native_test_command
        )
    )
    docker_session: DockerRuntimeSession = (
        start_docker_runtime_if_needed()
        )
    report_progress(
    progress_callback,
    15,
    "Docker ready",
)
    try:
        report_progress(
            progress_callback,
            25,
            "Preparing test environment",
        )
        started_at = time.monotonic()

        with tempfile.TemporaryDirectory(
            prefix="contrigent-test-environment-"
        ) as temporary_folder:
            test_environment_path = Path(
                temporary_folder
            )

            # Docker Desktop must be able to write
            # the temporary Linux virtual environment.
            test_environment_path.chmod(
                0o777
            )
            candidate_overlay_command = ""

            if proposed_files:
                candidate_overrides_path = (
                    test_environment_path
                    / "candidate-overrides"
                )

                apply_approved_files(
                    candidate_overrides_path,
                    proposed_files,
                )

                candidate_overlay_command = (
                    "cp -a "
                    "/test-environment/candidate-overrides/. "
                    "/test-environment/workspace/ && "
                )
            dependency_command = [
                "sh",
                "-lc",
                (
                    "rm -rf /test-environment/workspace && "
                    "mkdir -p /test-environment/workspace && "
                    "cp -a /workspace/. "
                    "/test-environment/workspace/ && "
                    f"{candidate_overlay_command}"
                    "cd /test-environment/workspace && "
                    f"{dependency_setup} && "
                    f"{test_environment_command}"
                    f"{runner_readiness_command}"
                ),
            ]

            dependency_docker_command = (
                build_docker_command(
                    repository_path,
                    test_environment_path,
                    dependency_command,
                    disable_network=False,
                )
            )

            (
                dependency_exit_code,
                dependency_stdout,
                dependency_stderr,
                dependency_timed_out,
            ) = run_docker_command(
                dependency_docker_command,
                DEPENDENCY_SETUP_TIMEOUT_SECONDS,
            )

            if (
                dependency_timed_out
                or dependency_exit_code != 0
            ):
                report_progress(
                    progress_callback,
                    95,
                    "Dependency setup failed",
                )
                return RepositoryTestResult(
                    passed=False,
                    stage="dependency_setup",
                    command=dependency_command,
                    exit_code=dependency_exit_code,
                    timed_out=dependency_timed_out,
                    duration_seconds=round(
                        time.monotonic()
                        - started_at,
                        3,
                    ),
                    stdout=dependency_stdout,
                    stderr=dependency_stderr,
                )

            if repository_snapshot is not None:
                repository_mutations = (
                    find_repository_setup_mutations(
                        repository_snapshot,
                        test_environment_path
                        / "workspace",
                    )
                )

                if repository_mutations:
                    mutation_details = ", ".join(
                        repository_mutations
                    )
                    report_progress(
                        progress_callback,
                        95,
                        "Dependency setup modified repository files",
                    )
                    return RepositoryTestResult(
                        passed=False,
                        stage="dependency_setup",
                        command=dependency_command,
                        exit_code=1,
                        duration_seconds=round(
                            time.monotonic()
                            - started_at,
                            3,
                        ),
                        stdout=dependency_stdout,
                        stderr=trim_command_output(
                            (
                                dependency_stderr
                                + "\nRepository setup modified "
                                "protected repository files: "
                                + mutation_details
                            ).strip()
                        ),
                    )

            report_progress(
                progress_callback,
                50,
                "Dependencies ready",
            )

            report_progress(
                progress_callback,
                60,
                "Running repository tests",
            )

            test_command = [
                "sh",
                "-lc",
                (
                    "cd /test-environment/workspace && "
                    f"{test_environment_command}"
                    f"{native_test_command}"
                ),
            ]

            test_docker_command = (
                build_docker_command(
                    repository_path,
                    test_environment_path,
                    test_command,
                    disable_network=True,
                )
            )

            (
                test_exit_code,
                test_stdout,
                test_stderr,
                test_timed_out,
            ) = run_docker_command(
                test_docker_command,
                TEST_TIMEOUT_SECONDS,
            )
            report_progress(
                progress_callback,
                90,
                "Tests finished",
            )

            passed = (
                not test_timed_out
                and test_exit_code == 0
            )
            report_progress(
                progress_callback,
                95,
                (
                    "Processing test results"
                    if passed
                    else "Processing test failure"
                ),
            )

            return RepositoryTestResult(
                passed=passed,
                stage="tests",
                command=test_command,
                exit_code=test_exit_code,
                timed_out=test_timed_out,
                duration_seconds=round(
                    time.monotonic()
                    - started_at,
                    3,
                ),
                stdout=test_stdout,
                stderr=test_stderr,
            )
    finally:
        try:
            stop_docker_runtime_if_started(
                docker_session
            )
        except Exception:
            pass


def build_bind_mount(
    host_path: Path,
    container_path: str,
    *,
    read_only: bool,
) -> str:
    resolved_path = str(
        host_path.resolve()
    )

    if "," in resolved_path:
        raise RepositoryTestRunnerError(
            "Docker test paths cannot contain commas."
        )

    mount = (
        f"type=bind,"
        f"src={resolved_path},"
        f"dst={container_path}"
    )

    if read_only:
        mount += ",readonly"

    return mount
