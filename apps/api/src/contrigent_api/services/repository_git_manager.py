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

def split_git_paths(
    output: str,
) -> list[str]:
    return [
        path
        for path in output.split("\0")
        if path
    ]


def get_unstaged_changed_files(
    repository_path: Path,
) -> list[str]:
    tracked_output = run_git_command(
        repository_path,
        "diff",
        "--name-only",
        "-z",
    )

    untracked_output = run_git_command(
        repository_path,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )

    return sorted(
        set(
            split_git_paths(
                tracked_output
            )
            + split_git_paths(
                untracked_output
            )
        )
    )


def get_staged_files(
    repository_path: Path,
) -> list[str]:
    output = run_git_command(
        repository_path,
        "diff",
        "--cached",
        "--name-only",
        "-z",
    )

    return sorted(
        split_git_paths(
            output
        )
    )


def ensure_expected_run_branch(
    repository_path: Path,
    expected_branch: str,
) -> None:
    actual_branch = get_current_branch(
        repository_path
    )

    if actual_branch != expected_branch:
        raise RepositoryGitError(
            "Repository is on the wrong branch. "
            f"Expected '{expected_branch}', "
            f"found '{actual_branch}'."
        )


def ensure_only_approved_files_changed(
    repository_path: Path,
    approved_files: list[str],
) -> None:
    expected_files = sorted(
        set(approved_files)
    )

    actual_files = (
        get_unstaged_changed_files(
            repository_path
        )
    )

    if actual_files != expected_files:
        raise RepositoryGitError(
            "Repository changes do not exactly match "
            "the human-approved files. "
            f"Expected {expected_files}; "
            f"found {actual_files}."
        )


def create_approved_commit(
    repository_path: Path,
    expected_branch: str,
    approved_files: list[str],
    commit_message: str,
) -> str:
    verify_git_repository(
        repository_path
    )

    ensure_expected_run_branch(
        repository_path,
        expected_branch,
    )

    ensure_only_approved_files_changed(
        repository_path,
        approved_files,
    )

    if not approved_files:
        raise RepositoryGitError(
            "Cannot create a commit because "
            "there are no approved files."
        )

    try:
        run_git_command(
            repository_path,
            "add",
            "--",
            *approved_files,
        )

        staged_files = get_staged_files(
            repository_path
        )

        expected_files = sorted(
            set(approved_files)
        )

        if staged_files != expected_files:
            raise RepositoryGitError(
                "Staged files do not exactly match "
                "the approved files."
            )

        remaining_changes = (
            get_unstaged_changed_files(
                repository_path
            )
        )

        if remaining_changes:
            raise RepositoryGitError(
                "Unexpected unstaged files remain "
                f"after staging: {remaining_changes}"
            )

        run_git_command(
            repository_path,
            "commit",
            "-m",
            commit_message,
        )

    except Exception:
        run_git_command(
            repository_path,
            "reset",
        )

        raise

    return run_git_command(
        repository_path,
        "rev-parse",
        "HEAD",
    )


def normalize_github_repository_url(
    repository_url: str,
) -> str:
    normalized = (
        repository_url.strip()
        .rstrip("/")
    )

    if normalized.endswith(".git"):
        normalized = normalized[:-4]

    return normalized.casefold()


def verify_origin_repository(
    repository_path: Path,
    expected_repository_url: str,
) -> None:
    origin_url = run_git_command(
        repository_path,
        "remote",
        "get-url",
        "origin",
    )

    if (
        normalize_github_repository_url(
            origin_url
        )
        != normalize_github_repository_url(
            expected_repository_url
        )
    ):
        raise RepositoryGitError(
            "Git origin does not match the GitHub "
            "repository supplied to Contrigent."
        )


def push_run_branch(
    repository_path: Path,
    branch_name: str,
    expected_repository_url: str,
) -> None:
    verify_git_repository(
        repository_path
    )

    ensure_expected_run_branch(
        repository_path,
        branch_name,
    )

    verify_origin_repository(
        repository_path,
        expected_repository_url,
    )

    run_git_command(
        repository_path,
        "push",
        "--set-upstream",
        "origin",
        branch_name,
    )