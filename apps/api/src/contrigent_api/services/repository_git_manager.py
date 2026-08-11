from pathlib import Path
from uuid import UUID
import subprocess


class RepositoryGitError(RuntimeError):
    pass


def run_git_command(
    repository_path: Path,
    *arguments: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            *arguments,
        ],
        cwd=repository_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Git command failed."
        )

        raise RepositoryGitError(
            message
        )

    return result.stdout.strip()


def verify_git_repository(
    repository_path: Path,
) -> None:
    if not repository_path.is_dir():
        raise RepositoryGitError(
            f"Repository folder does not exist: {repository_path}"
        )

    result = run_git_command(
        repository_path,
        "rev-parse",
        "--is-inside-work-tree",
    )

    if result != "true":
        raise RepositoryGitError(
            "Repository path is not a Git working repository."
        )


def ensure_clean_repository(
    repository_path: Path,
) -> None:
    status = run_git_command(
        repository_path,
        "status",
        "--porcelain",
    )

    if status:
        raise RepositoryGitError(
            "Repository has uncommitted changes."
        )


def get_current_branch(
    repository_path: Path,
) -> str:
    branch = run_git_command(
        repository_path,
        "branch",
        "--show-current",
    )

    if not branch:
        raise RepositoryGitError(
            "Repository is not currently on a named branch."
        )

    return branch


def create_run_branch(
    repository_path: Path,
    run_id: UUID,
) -> tuple[str, str]:
    verify_git_repository(
        repository_path
    )

    ensure_clean_repository(
        repository_path
    )

    original_branch = get_current_branch(
        repository_path
    )

    run_branch = (
        f"contrigent/{run_id}"
    )

    run_git_command(
        repository_path,
        "checkout",
        "-b",
        run_branch,
    )

    return (
        original_branch,
        run_branch,
    )


def rollback_run_branch(
    repository_path: Path,
    original_branch: str,
    run_branch: str,
) -> None:
    run_git_command(
        repository_path,
        "reset",
        "--hard",
        "HEAD",
    )

    run_git_command(
        repository_path,
        "clean",
        "-fd",
    )

    run_git_command(
        repository_path,
        "checkout",
        original_branch,
    )

    run_git_command(
        repository_path,
        "branch",
        "-D",
        run_branch,
    )