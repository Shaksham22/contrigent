from urllib.error import HTTPError
import io
import json

import pytest

from contrigent_api.models.project_context import (
    ProjectSource,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.models.run_record import (
    Run,
    RunStatus,
)
from contrigent_api.services import (
    github_issue_commenter,
)
from contrigent_api.services.github_issue_commenter import (
    GitHubIssueCommentError,
    create_issue_comment,
)
from contrigent_api.services.issue_comment import (
    build_issue_comment,
    repository_tests_succeeded,
)


def make_run(
    *,
    tests_passed: bool,
) -> Run:
    return Run(
        project_name="example",
        project_source=ProjectSource.GITHUB,
        status=RunStatus.COMPLETED,
        repository_tests_completed=True,
        repository_tests_passed=tests_passed,
        repository_test_result=(
            RepositoryTestResult(
                passed=tests_passed,
                stage="tests",
                command=["pytest"],
                exit_code=(
                    0 if tests_passed else 1
                ),
                duration_seconds=0.1,
                stdout=(
                    "10 passed"
                    if tests_passed
                    else "1 failed"
                ),
                stderr="",
            )
        ),
    )


def test_issue_comment_is_deterministic_and_discloses_ai_use() -> None:
    comment = build_issue_comment(
        pull_request_number=42,
        pull_request_url=(
            "https://github.com/example/demo/pull/42"
        ),
        repository_tests_passed=True,
    )

    assert "draft PR #42" in comment
    assert "https://github.com/example/demo/pull/42" in comment
    assert "posted automatically by **Contrigent**" in comment
    assert "AI-assisted contributions" in comment
    assert "Feedback on the proposed change is welcome" in comment
    assert "run the repository tests" in comment


def test_unsuccessful_test_evidence_does_not_claim_tests_ran_successfully(
) -> None:
    comment = build_issue_comment(
        pull_request_number=42,
        pull_request_url=(
            "https://github.com/example/demo/pull/42"
        ),
        repository_tests_passed=False,
    )

    assert "run the repository tests" not in comment
    assert "verification evidence" not in comment
    assert (
        "The system was used to investigate the issue, prepare the "
        "proposed change, and create the draft pull request."
        in comment
    )
    assert repository_tests_succeeded(
        make_run(tests_passed=True)
    )
    assert not repository_tests_succeeded(
        make_run(tests_passed=False)
    )


def test_github_issue_comment_uses_authenticated_comments_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "id": 99,
                    "html_url": (
                        "https://github.com/example/"
                        "demo/issues/7#issuecomment-99"
                    ),
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(
            request.data.decode("utf-8")
        )
        captured["authorization"] = (
            request.headers["Authorization"]
        )
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv(
        "GITHUB_TOKEN",
        "github-secret-token",
    )
    monkeypatch.setattr(
        github_issue_commenter,
        "urlopen",
        fake_urlopen,
    )

    result = create_issue_comment(
        "https://github.com/example/demo/issues/7",
        "Deterministic comment body",
    )

    assert captured["url"] == (
        "https://api.github.com/repos/example/demo/"
        "issues/7/comments"
    )
    assert captured["payload"] == {
        "body": "Deterministic comment body"
    }
    assert captured["authorization"] == (
        "Bearer github-secret-token"
    )
    assert result.number == 99


def test_github_issue_comment_error_does_not_expose_token_or_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_urlopen(_request, timeout: int):
        nonlocal calls
        calls += 1
        assert timeout == 30
        raise HTTPError(
            url="https://api.github.com",
            code=403,
            msg="github-secret-token",
            hdrs=None,
            fp=io.BytesIO(
                b"github-secret-token"
            ),
        )

    monkeypatch.setenv(
        "GITHUB_TOKEN",
        "github-secret-token",
    )
    monkeypatch.setattr(
        github_issue_commenter,
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        GitHubIssueCommentError,
    ) as error_info:
        create_issue_comment(
            "https://github.com/example/demo/issues/7",
            "No token here",
        )

    assert calls == 1
    assert "github-secret-token" not in str(
        error_info.value
    )


def test_missing_comment_credentials_are_reported_as_safe_comment_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "GITHUB_TOKEN",
        raising=False,
    )

    with pytest.raises(
        GitHubIssueCommentError,
        match="Could not prepare",
    ):
        create_issue_comment(
            "https://github.com/example/demo/issues/7",
            "Deterministic comment",
        )
