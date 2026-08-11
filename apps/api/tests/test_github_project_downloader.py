from pathlib import Path

import pytest

from contrigent_api.services import (
    github_project_downloader,
)
from contrigent_api.services.github_project_downloader import (
    GitHubProjectDownloadError,
    build_downloaded_project_name,
    build_issue_markdown,
    download_github_project,
    parse_github_issue_url,
    parse_github_repository_url,
)


def test_parses_github_repository_url() -> None:
    owner, repository = (
        parse_github_repository_url(
            "https://github.com/example/demo.git"
        )
    )

    assert owner == "example"
    assert repository == "demo"


def test_parses_github_issue_url() -> None:
    location = parse_github_issue_url(
        "https://github.com/example/demo/issues/42"
    )

    assert location.owner == "example"
    assert location.repository == "demo"
    assert location.issue_number == 42


def test_project_name_is_clear() -> None:
    location = parse_github_issue_url(
        "https://github.com/Example/Demo/issues/42"
    )

    assert (
        build_downloaded_project_name(
            location
        )
        == "example-demo-issue-42"
    )


def test_issue_and_repository_must_match() -> None:
    with pytest.raises(
        GitHubProjectDownloadError,
        match="same repository",
    ):
        download_github_project(
            issue_url=(
                "https://github.com/example/one/issues/5"
            ),
            repository_url=(
                "https://github.com/example/two"
            ),
        )


def test_builds_issue_markdown_with_comments() -> None:
    markdown = build_issue_markdown(
        issue={
            "title": "Example bug",
            "body": "Something is broken.",
            "html_url": (
                "https://github.com/example/demo/issues/1"
            ),
            "user": {
                "login": "issue-author"
            },
        },
        comments=[
            {
                "body": "I can reproduce this.",
                "created_at": "2026-08-11T10:00:00Z",
                "user": {
                    "login": "comment-author"
                },
            }
        ],
    )

    assert "# Example bug" in markdown
    assert "Something is broken." in markdown
    assert "comment-author" in markdown
    assert "I can reproduce this." in markdown


def test_download_cleans_up_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_project_downloader,
        "DOWNLOADED_GITHUB_PROJECTS_FOLDER",
        tmp_path,
    )

    monkeypatch.setattr(
        github_project_downloader,
        "fetch_github_json",
        lambda _url: {
            "title": "Example issue",
            "body": "Example body",
            "html_url": (
                "https://github.com/example/demo/issues/1"
            ),
            "user": {
                "login": "example"
            },
        },
    )

    monkeypatch.setattr(
        github_project_downloader,
        "fetch_all_issue_comments",
        lambda *_args: [],
    )

    def fail_clone(
        repository_url: str,
        repository_folder: Path,
    ) -> None:
        raise GitHubProjectDownloadError(
            "simulated clone failure"
        )

    monkeypatch.setattr(
        github_project_downloader,
        "clone_github_repository",
        fail_clone,
    )

    with pytest.raises(
        GitHubProjectDownloadError,
        match="simulated clone failure",
    ):
        download_github_project(
            issue_url=(
                "https://github.com/example/demo/issues/1"
            ),
            repository_url=(
                "https://github.com/example/demo"
            ),
        )

    assert not (
        tmp_path
        / "example-demo-issue-1"
    ).exists()