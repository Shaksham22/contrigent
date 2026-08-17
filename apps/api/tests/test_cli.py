import pytest

from contrigent_api.cli.main import (
    handle_issue_comment_publication,
)
from contrigent_api.cli.prompts import (
    ask_for_approval,
    ask_for_issue_comment_decision,
    ask_for_round_limit,
)
from contrigent_api.cli.display import (
    show_execution_result,
    show_run_progress,
)
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
from contrigent_api.services.github_issue_commenter import (
    GitHubIssueCommentError,
)
from contrigent_api.services.run_progress import (
    RunProgressEvent,
)


def make_completed_github_run(
    *,
    draft_pr_created: bool = True,
) -> Run:
    return Run(
        project_name="example",
        project_source=ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/7"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
        status=RunStatus.COMPLETED,
        repository_tests_completed=True,
        repository_tests_passed=True,
        repository_test_result=(
            RepositoryTestResult(
                passed=True,
                stage="tests",
                command=["pytest"],
                exit_code=0,
                duration_seconds=0.1,
                stdout="10 passed",
                stderr="",
            )
        ),
        changes_applied=True,
        commit_created=True,
        branch_pushed=True,
        draft_pr_created=draft_pr_created,
        draft_pr_number=(
            42 if draft_pr_created else None
        ),
        draft_pr_url=(
            "https://github.com/example/demo/pull/42"
            if draft_pr_created
            else None
        ),
    )

def test_approval_accepts_yes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "y",
    )

    approved = ask_for_approval(
        "Proceed?",
        lambda: None,
    )

    assert approved is True


def test_approval_accepts_no(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "n",
    )

    approved = ask_for_approval(
        "Proceed?",
        lambda: None,
    )

    assert approved is False


def test_details_can_be_shown_before_approval(
    monkeypatch,
) -> None:
    answers = iter(
        [
            "d",
            "y",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: next(
            answers
        ),
    )

    details_shown: list[bool] = []

    approved = ask_for_approval(
        "Proceed?",
        lambda: details_shown.append(
            True
        ),
    )

    assert approved is True
    assert details_shown == [
        True
    ]


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("y", True),
        ("Y", True),
        ("n", False),
        ("N", False),
    ],
)
def test_issue_comment_explicit_choice_is_immediate(
    choice: str,
    expected: bool,
) -> None:
    timed_calls = 0
    fallback_calls = 0

    def timed_input(
        _prompt: str,
        timeout_seconds: float,
    ) -> str:
        nonlocal timed_calls
        timed_calls += 1
        assert timeout_seconds == 5.0
        return choice

    def fallback_input(_prompt: str) -> str:
        nonlocal fallback_calls
        fallback_calls += 1
        return "n"

    result = ask_for_issue_comment_decision(
        lambda: None,
        timed_input_reader=timed_input,
        input_reader=fallback_input,
    )

    assert result is expected
    assert timed_calls == 1
    assert fallback_calls == 0


def test_issue_comment_timeout_defaults_to_post() -> None:
    result = ask_for_issue_comment_decision(
        lambda: None,
        timed_input_reader=(
            lambda _prompt, _timeout: None
        ),
        input_reader=(
            lambda _prompt: pytest.fail(
                "Timeout must not request more input."
            )
        ),
    )

    assert result is True


@pytest.mark.parametrize(
    ("final_choice", "expected"),
    [
        ("y", True),
        ("n", False),
    ],
)
def test_issue_comment_details_cancel_timeout_permanently(
    final_choice: str,
    expected: bool,
) -> None:
    timed_calls = 0
    details_calls = 0

    def timed_input(
        _prompt: str,
        _timeout: float,
    ) -> str:
        nonlocal timed_calls
        timed_calls += 1
        return "d"

    def show_details() -> None:
        nonlocal details_calls
        details_calls += 1

    result = ask_for_issue_comment_decision(
        show_details,
        timed_input_reader=timed_input,
        input_reader=(
            lambda _prompt: final_choice
        ),
    )

    assert result is expected
    assert timed_calls == 1
    assert details_calls == 1


def test_invalid_issue_comment_input_cancels_implicit_approval() -> None:
    timed_calls = 0
    fallback_answers = iter([
        "still-invalid",
        "n",
    ])

    def timed_input(
        _prompt: str,
        _timeout: float,
    ) -> str:
        nonlocal timed_calls
        timed_calls += 1
        return "maybe"

    result = ask_for_issue_comment_decision(
        lambda: None,
        timed_input_reader=timed_input,
        input_reader=(
            lambda _prompt: next(
                fallback_answers
            )
        ),
    )

    assert result is False
    assert timed_calls == 1


def test_comment_preview_is_printed_before_timeout_starts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = make_completed_github_run()
    output_at_timeout: list[str] = []

    def decision_prompt(_show_details) -> bool:
        output_at_timeout.append(
            capsys.readouterr().out
        )
        return False

    result = handle_issue_comment_publication(
        run,
        decision_prompt=decision_prompt,
        comment_creator=(
            lambda _issue, _body: None
        ),
    )

    assert result == "skipped"
    assert "✓ Draft pull request created" in output_at_timeout[0]
    assert "Issue comment" in output_at_timeout[0]
    assert "draft PR #42" in output_at_timeout[0]
    assert "AI-assisted contributions" in output_at_timeout[0]


def test_issue_comment_details_show_complete_publication_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = make_completed_github_run()
    posted_comments: list[str] = []

    def decision_prompt(show_details) -> bool:
        return ask_for_issue_comment_decision(
            show_details,
            timed_input_reader=(
                lambda _prompt, _timeout: "d"
            ),
            input_reader=(
                lambda _prompt: "y"
            ),
        )

    result = handle_issue_comment_publication(
        run,
        decision_prompt=decision_prompt,
        comment_creator=(
            lambda _issue, body: (
                posted_comments.append(body)
            )
        ),
    )
    output = capsys.readouterr().out

    assert result == "posted"
    assert "Issue URL: https://github.com/example/demo/issues/7" in output
    assert "Issue number: 7" in output
    assert "Draft PR URL: https://github.com/example/demo/pull/42" in output
    assert "PR number: 42" in output
    assert "Complete issue comment:" in output
    assert len(posted_comments) == 1


def test_issue_comment_is_posted_at_most_once() -> None:
    run = make_completed_github_run()
    calls: list[tuple[str, str]] = []

    result = handle_issue_comment_publication(
        run,
        decision_prompt=(
            lambda _show_details: True
        ),
        comment_creator=(
            lambda issue_url, body: calls.append(
                (issue_url, body)
            )
        ),
    )

    assert result == "posted"
    assert len(calls) == 1


def test_issue_comment_failure_preserves_completed_contribution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = make_completed_github_run()
    calls = 0

    def fail_comment(
        _issue_url: str,
        _body: str,
    ) -> None:
        nonlocal calls
        calls += 1
        raise GitHubIssueCommentError(
            "GitHub rejected issue comment creation with HTTP 403."
        )

    result = handle_issue_comment_publication(
        run,
        decision_prompt=(
            lambda _show_details: True
        ),
        comment_creator=fail_comment,
    )
    output = capsys.readouterr().out

    assert result == "failed"
    assert calls == 1
    assert run.status == RunStatus.COMPLETED
    assert run.draft_pr_created is True
    assert "could not be posted" in output
    assert run.draft_pr_url in output
    assert "HTTP 403" in output


def test_unexpected_comment_failure_is_safe_and_non_fatal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = make_completed_github_run()

    def fail_comment(
        _issue_url: str,
        _body: str,
    ) -> None:
        raise RuntimeError(
            "github-secret-token"
        )

    result = handle_issue_comment_publication(
        run,
        decision_prompt=(
            lambda _show_details: True
        ),
        comment_creator=fail_comment,
    )
    output = capsys.readouterr().out

    assert result == "failed"
    assert run.status == RunStatus.COMPLETED
    assert "unexpected error" in output
    assert "github-secret-token" not in output


def test_no_successful_pr_means_no_comment_prompt() -> None:
    run = make_completed_github_run(
        draft_pr_created=False
    )

    result = handle_issue_comment_publication(
        run,
        decision_prompt=(
            lambda _show_details: pytest.fail(
                "A comment decision must not be requested."
            )
        ),
        comment_creator=(
            lambda _issue, _body: pytest.fail(
                "A comment must not be posted."
            )
        ),
    )

    assert result == "not_offered"


def test_skipped_comment_keeps_normal_completion_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = make_completed_github_run()
    result = handle_issue_comment_publication(
        run,
        decision_prompt=(
            lambda _show_details: False
        ),
        comment_creator=(
            lambda _issue, _body: pytest.fail(
                "A skipped comment must not be posted."
            )
        ),
    )
    show_execution_result(
        run,
        include_draft_pr_confirmation=(
            result == "not_offered"
        ),
    )
    output = capsys.readouterr().out

    assert "○ Issue comment skipped" in output
    assert "Contrigent completed the issue." in output
    assert output.count(
        "✓ Draft pull request created"
    ) == 1


def test_round_limit_uses_default(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "",
    )

    assert (
        ask_for_round_limit(
            "Maximum testing rounds",
        )
        == 2
    )


def test_round_limit_accepts_value(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "3",
    )

    assert (
        ask_for_round_limit(
            "Maximum review rounds",
        )
        == 3
    )


def test_round_limit_rejects_invalid_value(
    monkeypatch,
) -> None:
    answers = iter(
        [
            "0",
            "11",
            "three",
            "4",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: next(
            answers
        ),
    )

    assert (
        ask_for_round_limit(
            "Maximum review rounds",
        )
        == 4
    )

def test_run_progress_displays_failure_details(
    capsys,
) -> None:
    show_run_progress(
        RunProgressEvent(
            kind="testing_failed",
            message=(
                "Candidate tests failed"
            ),
            details=(
                "Stage: tests",
                "Exit code: 2",
                (
                    "ERROR collecting "
                    "tests/test_example.py"
                ),
            ),
        )
    )

    output = (
        capsys.readouterr().out
    )

    assert (
        "Candidate tests failed"
        in output
    )

    assert (
        "Exit code: 2"
        in output
    )

    assert (
        "ERROR collecting"
        in output
    )


def test_repository_preflight_progress_is_displayed(
    capsys,
) -> None:
    messages = (
        ("preflight_started", "Repository preflight"),
        (
            "preflight_detecting",
            "Detecting test environment",
        ),
        (
            "preflight_verifying",
            "Verifying untouched repository",
        ),
        (
            "preflight_discovery",
            "Setup specialist attempt 1/2",
        ),
        ("preflight_passed", "Baseline passed"),
        ("analysis_started", "Starting issue analysis"),
    )

    for kind, message in messages:
        show_run_progress(
            RunProgressEvent(
                kind=kind,
                message=message,
            )
        )

    output = capsys.readouterr().out

    for _kind, message in messages:
        assert message in output
