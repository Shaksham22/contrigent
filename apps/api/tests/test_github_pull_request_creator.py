import pytest

from contrigent_api.services.github_pull_request_creator import (
    GitHubPullRequestError,
    PULL_REQUEST_ATTRIBUTION,
    create_draft_pull_request,
    get_github_token,
    get_issue_title,
)
import json

from contrigent_api.services import (
    github_pull_request_creator,
)


def test_issue_title_is_read_from_markdown() -> None:
    assert (
        get_issue_title(
            "# Example issue\n\nDescription"
        )
        == "Example issue"
    )


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


def test_fork_branch_is_used_as_pr_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GITHUB_TOKEN",
        "test-token",
    )

    captured_payload: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(
            self,
            *_args,
        ):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "number": 12,
                    "html_url": (
                        "https://github.com/"
                        "upstream/demo/pull/12"
                    ),
                }
            ).encode(
                "utf-8"
            )

    def fake_urlopen(
        request,
        timeout: int,
    ):
        captured_payload.update(
            json.loads(
                request.data.decode(
                    "utf-8"
                )
            )
        )

        return FakeResponse()

    monkeypatch.setattr(
        github_pull_request_creator,
        "urlopen",
        fake_urlopen,
    )

    body = (
        "## Summary\n\n"
        "Fix atomic reservation.\n\n"
        "## Changes\n\n"
        "- Validate the order before mutation.\n\n"
        "## Testing\n\n"
        "- 10 tests passed.\n\n"
        "Closes #1"
    )
    result = create_draft_pull_request(
        repository_url=(
            "https://github.com/"
            "upstream/demo"
        ),
        issue_url=(
            "https://github.com/"
            "upstream/demo/issues/1"
        ),
        head_owner="contributor",
        head_branch="contrigent/test-run",
        base_branch="main",
        title="Fix issue",
        body=body,
    )

    assert captured_payload["head"] == (
        "contributor:contrigent/test-run"
    )

    assert captured_payload["base"] == "main"
    assert captured_payload["draft"] is True
    assert result.number == 12
    assert result.url.endswith("/pull/12")

    published_body = captured_payload["body"]
    assert "## Summary" in published_body
    assert "## Changes" in published_body
    assert "## Testing" in published_body
    assert "Closes #1" in published_body
    assert PULL_REQUEST_ATTRIBUTION.strip() in published_body
    assert "## Review" not in published_body
    assert "Independent Reviewer" not in published_body
    assert "Manager reasoning" not in published_body
    assert "worker reasoning" not in published_body
