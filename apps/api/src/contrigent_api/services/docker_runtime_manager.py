from dataclasses import dataclass
import shutil
import subprocess
import time


DOCKER_START_TIMEOUT_SECONDS = 120
DOCKER_READY_CHECK_INTERVAL_SECONDS = 2


class DockerRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerRuntimeSession:
    started_by_contrigent: bool


def docker_cli_is_installed() -> bool:
    return shutil.which("docker") is not None


def run_docker_command(
    command: list[str],
    timeout_seconds: int = 15,
) -> subprocess.CompletedProcess[str]:
    if not docker_cli_is_installed():
        raise DockerRuntimeError(
            "Docker CLI is not installed or is not available on PATH."
        )

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

    except subprocess.TimeoutExpired as error:
        raise DockerRuntimeError(
            "Docker command timed out."
        ) from error


def docker_engine_is_ready() -> bool:
    if not docker_cli_is_installed():
        return False

    try:
        result = subprocess.run(
            [
                "docker",
                "info",
                "--format",
                "{{.OSType}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return False

    return result.returncode == 0


def get_docker_engine_os_type() -> str:
    result = run_docker_command(
        [
            "docker",
            "info",
            "--format",
            "{{.OSType}}",
        ]
    )

    if result.returncode != 0:
        raise DockerRuntimeError(
            result.stderr.strip()
            or "Could not inspect Docker Engine."
        )

    return result.stdout.strip().lower()


def ensure_linux_container_engine() -> None:
    os_type = get_docker_engine_os_type()

    if os_type != "linux":
        raise DockerRuntimeError(
            "Contrigent repository tests require "
            "Docker to use Linux containers. "
            f"Current Docker engine type: {os_type}"
        )


def docker_desktop_cli_is_available() -> bool:
    if not docker_cli_is_installed():
        return False

    try:
        result = subprocess.run(
            [
                "docker",
                "desktop",
                "version",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return False

    return result.returncode == 0


def wait_for_docker_engine() -> None:
    deadline = (
        time.monotonic()
        + DOCKER_START_TIMEOUT_SECONDS
    )

    while time.monotonic() < deadline:
        if docker_engine_is_ready():
            return

        time.sleep(
            DOCKER_READY_CHECK_INTERVAL_SECONDS
        )

    raise DockerRuntimeError(
        "Docker did not become ready within "
        f"{DOCKER_START_TIMEOUT_SECONDS} seconds."
    )


def start_docker_runtime_if_needed(
) -> DockerRuntimeSession:
    if not docker_cli_is_installed():
        raise DockerRuntimeError(
            "Docker is not installed."
        )

    if docker_engine_is_ready():
        ensure_linux_container_engine()

        return DockerRuntimeSession(
            started_by_contrigent=False
        )

    if not docker_desktop_cli_is_available():
        raise DockerRuntimeError(
            "Docker is installed but its daemon "
            "is not running, and Docker Desktop "
            "cannot be started automatically. "
            "Start Docker and try again."
        )

    result = run_docker_command(
        [
            "docker",
            "desktop",
            "start",
            "--detach",
            "--timeout",
            "30",
        ],
        timeout_seconds=40,
    )

    if result.returncode != 0:
        raise DockerRuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Docker Desktop could not be started."
        )

    try:
        wait_for_docker_engine()
        ensure_linux_container_engine()

    except Exception:
        subprocess.run(
            [
                "docker",
                "desktop",
                "stop",
                "--detach",
                "--timeout",
                "30",
            ],
            capture_output=True,
            text=True,
        )

        raise

    return DockerRuntimeSession(
        started_by_contrigent=True
    )


def stop_docker_runtime_if_started(
    session: DockerRuntimeSession,
) -> None:
    if not session.started_by_contrigent:
        return

    result = run_docker_command(
        [
            "docker",
            "desktop",
            "stop",
            "--detach",
            "--timeout",
            "30",
        ],
        timeout_seconds=40,
    )

    if result.returncode != 0:
        raise DockerRuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Docker Desktop could not be stopped."
        )