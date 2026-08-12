from pathlib import Path
import subprocess
import tempfile
import time

from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.services.docker_runtime_manager import (
    DockerRuntimeSession,
    start_docker_runtime_if_needed,
    stop_docker_runtime_if_started,
)

DOCKER_IMAGE = (
    "ghcr.io/astral-sh/uv:"
    "python3.12-bookworm-slim"
)

DEPENDENCY_SETUP_TIMEOUT_SECONDS = 300
TEST_TIMEOUT_SECONDS = 300

MAX_OUTPUT_CHARACTERS = 20_000


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
            "UV_PROJECT_ENVIRONMENT="
            "/test-environment/venv"
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


def run_repository_tests(
    repository_path: Path,
) -> RepositoryTestResult:
    repository_path = (
        repository_path.resolve()
    )

    if not repository_path.is_dir():
        raise RepositoryTestRunnerError(
            "Repository folder does not exist."
        )

    if not (
        repository_path
        / "pyproject.toml"
    ).is_file():
        raise RepositoryTestRunnerError(
            "Automatic repository testing "
            "currently supports Python projects "
            "with pyproject.toml."
        )

    if not (
        repository_path
        / "uv.lock"
    ).is_file():
        raise RepositoryTestRunnerError(
            "Automatic repository testing "
            "currently requires uv.lock so "
            "dependency setup cannot modify "
            "the repository."
        )
    docker_session: DockerRuntimeSession = (
        start_docker_runtime_if_needed()
        )
    try:
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

            dependency_command = [
                "uv",
                "sync",
                "--locked",
                "--all-groups",
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

            test_command = [
                "uv",
                "run",
                "--offline",
                "--no-sync",
                "python",
                "-m",
                "pytest",
                "-v",
                "-p",
                "no:cacheprovider",
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

            passed = (
                not test_timed_out
                and test_exit_code == 0
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