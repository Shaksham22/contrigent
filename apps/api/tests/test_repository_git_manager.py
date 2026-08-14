from pathlib import Path
from uuid import uuid4
import subprocess

import pytest
from contrigent_api.services import (
    repository_git_manager,
)

from contrigent_api.services.repository_git_manager import (
    RepositoryGitError,
    create_approved_commit,
    create_run_branch,
    get_current_branch,
    push_run_branch,
    rollback_run_branch,
    verify_fork_remotes,
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

def test_create_run_branch_uses_upstream_default_branch(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    upstream_repository = (
        tmp_path / "upstream.git"
    )

    subprocess.run(
        [
            "git",
            "clone",
            "--bare",
            str(repository),
            str(upstream_repository),
        ],
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "upstream",
            str(upstream_repository),
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            "git",
            "checkout",
            "-b",
            "contrigent/previous-run",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    (
        repository / "example.py"
    ).write_text(
        "value = 999\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "git",
            "add",
            "example.py",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "Previous Contrigent run",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    run_id = uuid4()

    original_branch, run_branch = (
        create_run_branch(
            repository,
            run_id,
            base_remote="upstream",
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

    assert (
        repository
        / "example.py"
    ).read_text(
        encoding="utf-8"
    ) == "value = 1\n"


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


def test_approved_files_can_be_committed(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    _, run_branch = create_run_branch(
        repository,
        uuid4(),
    )

    (
        repository / "example.py"
    ).write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    commit_sha = create_approved_commit(
        repository,
        expected_branch=run_branch,
        approved_files=[
            "example.py"
        ],
        commit_message="Fix example",
    )

    assert len(commit_sha) == 40

    assert (
        subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
            ],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )


def test_unapproved_file_blocks_commit(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    _, run_branch = create_run_branch(
        repository,
        uuid4(),
    )

    (
        repository / "example.py"
    ).write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    (
        repository / "unexpected.py"
    ).write_text(
        "unexpected = True\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RepositoryGitError,
        match="do not exactly match",
    ):
        create_approved_commit(
            repository,
            expected_branch=run_branch,
            approved_files=[
                "example.py"
            ],
            commit_message="Fix example",
        )

def test_fork_remotes_are_verified(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            (
                "https://github.com/"
                "contributor/demo.git"
            ),
        ],
        cwd=repository,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "upstream",
            (
                "https://github.com/"
                "upstream/demo.git"
            ),
        ],
        cwd=repository,
        check=True,
    )

    verify_fork_remotes(
        repository,
        expected_upstream_url=(
            "https://github.com/"
            "upstream/demo"
        ),
        expected_fork_owner=(
            "contributor"
        ),
    )


def test_wrong_fork_owner_is_rejected(
    tmp_path: Path,
) -> None:
    repository = (
        create_test_git_repository(
            tmp_path
        )
    )

    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            (
                "https://github.com/"
                "wrong-user/demo.git"
            ),
        ],
        cwd=repository,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "upstream",
            (
                "https://github.com/"
                "upstream/demo.git"
            ),
        ],
        cwd=repository,
        check=True,
    )

    with pytest.raises(
        RepositoryGitError,
        match="authenticated user's fork",
    ):
        verify_fork_remotes(
            repository,
            expected_upstream_url=(
                "https://github.com/"
                "upstream/demo"
            ),
            expected_fork_owner=(
                "contributor"
            ),
        )


def test_push_run_branch_verifies_fork_remotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    verified: dict[str, str] = {}
    git_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        repository_git_manager,
        "verify_git_repository",
        lambda repository_path: None,
    )

    monkeypatch.setattr(
        repository_git_manager,
        "ensure_expected_run_branch",
        lambda repository_path, expected_branch: None,
    )

    def fake_verify_fork_remotes(
        repository_path: Path,
        expected_upstream_url: str,
        expected_fork_owner: str,
    ) -> None:
        verified["upstream"] = expected_upstream_url
        verified["fork_owner"] = expected_fork_owner

    monkeypatch.setattr(
        repository_git_manager,
        "verify_fork_remotes",
        fake_verify_fork_remotes,
    )

    def fake_run_git_command(
        repository_path: Path,
        *arguments: str,
    ) -> str:
        git_calls.append(arguments)
        return ""

    monkeypatch.setattr(
        repository_git_manager,
        "run_git_command",
        fake_run_git_command,
    )

    repository_git_manager.push_run_branch(
        repository,
        branch_name="contrigent/test-run",
        expected_upstream_url=(
            "https://github.com/upstream/demo"
        ),
        expected_fork_owner="contributor",
    )

    assert verified == {
        "upstream": "https://github.com/upstream/demo",
        "fork_owner": "contributor",
    }

    assert git_calls == [
        (
            "push",
            "--set-upstream",
            "origin",
            "contrigent/test-run",
        )
    ]