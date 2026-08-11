from pathlib import Path
from uuid import uuid4
import subprocess

import pytest

from contrigent_api.services.repository_git_manager import (
    RepositoryGitError,
    create_run_branch,
    get_current_branch,
    rollback_run_branch,
)


def create_test_git_repository(
    tmp_path: Path,
) -> Path:
    repository = (
        tmp_path / "repository"
    )

    repository.mkdir()

    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "contrigent-test@example.com",
        ],
        cwd=repository,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "Contrigent Test",
        ],
        cwd=repository,
        check=True,
    )

    (
        repository / "example.py"
    ).write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=repository,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "Initial test repository",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    return repository


def test_create_run_branch(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    run_id = uuid4()

    original_branch, run_branch = (
        create_run_branch(
            repository,
            run_id,
        )
    )

    assert original_branch == "main"

    assert run_branch == (
        f"contrigent/{run_id}"
    )

    assert (
        get_current_branch(repository)
        == run_branch
    )


def test_dirty_repository_is_rejected(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    (
        repository / "example.py"
    ).write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RepositoryGitError,
        match="uncommitted changes",
    ):
        create_run_branch(
            repository,
            uuid4(),
        )


def test_run_branch_can_be_rolled_back(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    original_branch, run_branch = (
        create_run_branch(
            repository,
            uuid4(),
        )
    )

    (
        repository / "example.py"
    ).write_text(
        "changed = True\n",
        encoding="utf-8",
    )

    rollback_run_branch(
        repository,
        original_branch,
        run_branch,
    )

    assert (
        get_current_branch(repository)
        == "main"
    )

    assert (
        repository
        / "example.py"
    ).read_text(
        encoding="utf-8"
    ) == "value = 1\n"