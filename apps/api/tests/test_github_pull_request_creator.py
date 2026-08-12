import pytest

from contrigent_api.services.github_pull_request_creator import (
    GitHubPullRequestError,
    build_pull_request_body,
    get_github_token,
    get_issue_title,
)


def test_issue_title_is_read_from_markdown() -> None:
    assert (
        get_issue_title(
            "# Example issue\n\nDescription"
        )
        == "Example issue"
    )


def test_pull_request_body_links_issue() -> None:
    body = build_pull_request_body(
        issue_number=7,
        analysis_summary="Fix atomic reservation.",
        test_summary="10 tests passed",
    )

    assert "Fix atomic reservation." in body
    assert "10 tests passed" in body
    assert "Closes #7" in body


def test_missing_github_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "GITHUB_TOKEN",
        raising=False,
    )

    with pytest.raises(
        GitHubPullRequestError,
        match="GITHUB_TOKEN",
    ):
        get_github_token()