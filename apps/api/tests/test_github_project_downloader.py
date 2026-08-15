from pathlib import Path

import pytest

from contrigent_api.services import (
    github_project_downloader,
)
from contrigent_api.services.github_project_downloader import (
    GitHubProjectDownloadError,
    build_downloaded_project_name,
    build_issue_markdown,
    collect_issue_image_references,
    download_github_project,
    extract_github_issue_image_urls,
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

def test_extracts_github_images_from_markdown_and_html() -> None:
    image_urls = (
        extract_github_issue_image_urls(
            """
![failure](https://github.com/user-attachments/assets/abc123)
<img src="https://user-images.githubusercontent.com/1/example.png">
![external](https://example.com/not-github.png)
"""
        )
    )

    assert image_urls == [
        (
            "https://github.com/"
            "user-attachments/assets/abc123"
        ),
        (
            "https://user-images."
            "githubusercontent.com/"
            "1/example.png"
        ),
    ]


def test_collects_images_from_issue_and_comments() -> None:
    references = (
        collect_issue_image_references(
            issue={
                "body": (
                    "![issue]("
                    "https://github.com/"
                    "user-attachments/assets/"
                    "issue-image)"
                )
            },
            comments=[
                {
                    "body": (
                        "![comment]("
                        "https://github.com/"
                        "user-attachments/assets/"
                        "comment-image)"
                    )
                }
            ],
        )
    )

    assert references == [
        (
            "issue-description",
            (
                "https://github.com/"
                "user-attachments/assets/"
                "issue-image"
            ),
        ),
        (
            "comment-1",
            (
                "https://github.com/"
                "user-attachments/assets/"
                "comment-image"
            ),
        ),
    ]


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
    monkeypatch.setattr(
    github_project_downloader,
    "get_or_create_fork_repository_url",
    lambda _url: (
        "https://github.com/"
        "contributor/demo.git"
    ),
)

    monkeypatch.setattr(
        github_project_downloader,
        "add_upstream_remote",
        lambda *_args: None,
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


def test_existing_fork_is_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_project_downloader,
        "require_github_token",
        lambda: "test-token",
    )

    monkeypatch.setattr(
        github_project_downloader,
        "get_authenticated_github_user",
        lambda: "contributor",
    )

    monkeypatch.setattr(
        github_project_downloader,
        "get_existing_fork_url",
        lambda *_args: (
            "https://github.com/"
            "contributor/demo.git"
        ),
    )

    def unexpected_create(
        *_args,
    ) -> str:
        raise AssertionError(
            "Existing fork should be reused."
        )

    monkeypatch.setattr(
        github_project_downloader,
        "create_github_fork",
        unexpected_create,
    )

    waited_for: list[str] = []

    monkeypatch.setattr(
        github_project_downloader,
        "wait_for_github_fork",
        lambda url: waited_for.append(
            url
        ),
    )

    result = (
        github_project_downloader
        .get_or_create_fork_repository_url(
            "https://github.com/upstream/demo"
        )
    )

    assert result == (
        "https://github.com/"
        "contributor/demo.git"
    )

    assert waited_for == [
        "https://github.com/"
        "contributor/demo.git"
    ]


def test_missing_fork_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_project_downloader,
        "require_github_token",
        lambda: "test-token",
    )

    monkeypatch.setattr(
        github_project_downloader,
        "get_authenticated_github_user",
        lambda: "contributor",
    )

    monkeypatch.setattr(
        github_project_downloader,
        "get_existing_fork_url",
        lambda *_args: None,
    )

    monkeypatch.setattr(
        github_project_downloader,
        "create_github_fork",
        lambda _url: (
            "https://github.com/"
            "contributor/demo.git"
        ),
    )

    waited_for: list[str] = []

    monkeypatch.setattr(
        github_project_downloader,
        "wait_for_github_fork",
        lambda url: waited_for.append(
            url
        ),
    )

    result = (
        github_project_downloader
        .get_or_create_fork_repository_url(
            "https://github.com/upstream/demo"
        )
    )

    assert result == (
        "https://github.com/"
        "contributor/demo.git"
    )

    assert waited_for == [
        "https://github.com/"
        "contributor/demo.git"
    ]