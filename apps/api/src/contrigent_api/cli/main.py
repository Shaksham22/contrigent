from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import Literal
from contrigent_api.cli.config import (
    add_token_interactively,
    ensure_required_tokens,
    load_environment,
)

from urllib.parse import urlparse

load_environment()

from fastapi import HTTPException

from contrigent_api.cli.display import (
    show_cancelled,
    show_error,
    show_execution_result,
    show_execution_started,
    show_draft_pull_request_created,
    show_header,
    show_implementation_started,
    show_issue_comment_details,
    show_issue_comment_failure,
    show_issue_comment_posted,
    show_issue_comment_preview,
    show_issue_comment_skipped,
    show_run_progress,
    show_no_changes_needed,
    show_plan,
    show_plan_details,
    show_solution,
    show_solution_details,
    show_solution_not_found,
    show_starting_analysis,
    show_unapproved_solution,
    show_worker_failure,
)
from contrigent_api.cli.prompts import (
    ask_for_approval,
    ask_for_issue_comment_decision,
    ask_for_round_limit,
)
from contrigent_api.models.project_context import (
    ProjectSource,
)
from contrigent_api.models.run_record import (
    Run,
    RunStatus,
)
from contrigent_api.routes.run_routes import (
    CreateRunRequest,
    approve_run_final_changes,
    run_approved_plan,
    start_run,
)
from contrigent_api.services.project_reader import (
    load_project,
)
from contrigent_api.services.github_issue_commenter import (
    GitHubIssueCommentError,
    create_issue_comment,
)
from contrigent_api.services.github_project_downloader import (
    parse_github_issue_url,
)
from contrigent_api.services.issue_comment import (
    build_issue_comment,
    repository_tests_succeeded,
)
from contrigent_api.services.repository_git_manager import (
    rollback_run_branch,
)
from contrigent_api.services.run_memory_store import (
    fail_run,
)


def main() -> None:
    arguments = sys.argv[1:]

    if arguments:
        if arguments == [
            "token",
            "add",
        ]:
            add_token_interactively()
            return

        print(
            "Usage:"
        )
        print(
            "  contrigent"
        )
        print(
            "  contrigent token add"
        )

        raise SystemExit(2)

    show_header()

    if not ensure_required_tokens():
        print()
        print(
            "Contrigent cannot run "
            "without the required "
            "credentials."
        )

        return

    print(
        "Repository"
    )
    print(
        "----------"
    )
    print()
    print(
        "Paste the GitHub repository that "
        "contains the project you want "
        "Contrigent to work on."
    )
    print()
    print(
        "Example:"
    )
    print(
        "https://github.com/owner/project"
    )
    print()

    repository_url = _read_validated_value(
        "GitHub repository URL:",
        _is_github_repository_url,
        (
            "That does not look like a valid "
            "GitHub repository URL.\n\n"
            "Expected format:\n"
            "https://github.com/owner/project"
        ),
    )

    print(
    "Issue"
    )
    print(
        "-----"
    )
    print()
    print(
        "Paste the GitHub issue that you "
        "want Contrigent to investigate "
        "and attempt to solve."
    )
    print()
    print(
        "Contrigent will read the issue "
        "description, comments, attached "
        "images, and repository code before "
        "deciding whether a reliable "
        "solution can be produced."
    )
    print()
    print(
        "Example:"
    )
    print(
        "https://github.com/owner/project/issues/123"
    )
    print()

    issue_url = _read_validated_value(
        "GitHub issue URL:",
        _is_github_issue_url,
        (
            "That does not look like a valid "
            "GitHub issue URL.\n\n"
            "Expected format:\n"
            "https://github.com/owner/project/issues/123"
        ),
    )



    print(
        "Automatic retry limits"
    )
    print(
        "----------------------"
    )
    print()
    print(
        "Contrigent may automatically revise "
        "a proposed solution when tests fail "
        "or the Independent Reviewer requests "
        "changes."
    )
    print()
    print(
        "These values control the maximum "
        "number of attempts Contrigent may "
        "make before stopping."
    )
    print()
    print(
        "A successful result stops early, so "
        "setting 3 does not force all 3 rounds."
    )
    print()
    print(
        "Press Enter to use the default of 2."
    )
    print()

    max_testing_rounds = (
        ask_for_round_limit(
            "Maximum testing rounds",
        )
    )

    max_review_rounds = (
        ask_for_round_limit(
            "Maximum review rounds",
        )
    )

    print()

    print()

    show_starting_analysis()

    try:
        run = asyncio.run(
            start_run(
                CreateRunRequest(
                    github_repository_url=(
                        repository_url
                    ),
                    github_issue_url=(
                        issue_url
                    ),
                    max_testing_rounds=(
                        max_testing_rounds
                    ),
                    max_review_rounds=(
                        max_review_rounds
                    ),
                ),
                progress_callback=(
                    show_run_progress
                ),
            )
        )

        if (
            run.status
            == RunStatus.COMPLETED
            and not run.plan_approved
        ):
            show_no_changes_needed(
                run
            )

            _rollback_unpublished_run(
                run
            )

            return

        if (
            run.status
            == RunStatus.FAILED
            and not run.plan_approved
        ):
            show_solution_not_found(
                run
            )

            _rollback_unpublished_run(
                run
            )

            return

        if (
            run.status
            != RunStatus.AWAITING_PLAN_APPROVAL
        ):
            raise RuntimeError(
                "Analysis finished in an "
                "unexpected state: "
                f"{run.status.value}"
            )

        show_plan(
            run
        )

        plan_approved = ask_for_approval(
            "Proceed with this plan?",
            lambda: show_plan_details(
                run
            ),
            approve_label="Approve",
        )

        if not plan_approved:
            _cancel_unpublished_run(
                run
            )

            show_cancelled()

            return

        show_implementation_started()
        run = asyncio.run(
            run_approved_plan(
                run.id,
                progress_callback=(
                    show_run_progress
                ),
            )
        )

        if (
            run.status
            == RunStatus.FAILED
        ):
            show_worker_failure(
                run
            )

            _rollback_unpublished_run(
                run
            )

            return

        if (
            run.reviewer_result
            is None
        ):
            raise RuntimeError(
                "Worker execution completed "
                "without a Reviewer result."
            )

        if (
            run.reviewer_result
            .recommendation
            != "approve"
        ):
            show_unapproved_solution(
                run
            )

            _cancel_unpublished_run(
                run
            )

            return

        if (
            run.status
            != RunStatus.AWAITING_FINAL_APPROVAL
        ):
            raise RuntimeError(
                "Reviewed solution finished "
                "in an unexpected state: "
                f"{run.status.value}"
            )

        show_solution(
            run
        )

        final_approved = (
            ask_for_approval(
                (
                    "Execute this "
                    "solution?"
                ),
                lambda: (
                    show_solution_details(
                        run
                    )
                ),
                approve_label="Execute",
            )
        )

        if not final_approved:
            _cancel_unpublished_run(
                run
            )

            show_cancelled()

            return

        show_execution_started()

        run = (
            approve_run_final_changes(
                run.id
            )
        )

        issue_comment_result = (
            handle_issue_comment_publication(
                run
            )
        )

        show_execution_result(
            run,
            include_draft_pr_confirmation=(
                issue_comment_result
                == "not_offered"
            ),
        )

    except HTTPException as error:
        show_error(
            str(error.detail)
        )

        raise SystemExit(1) from error

    except KeyboardInterrupt:
        print()
        print()
        print(
            "Contrigent cancelled."
        )

        raise SystemExit(130)

    except Exception as error:
        show_error(
            str(error)
        )

        raise SystemExit(1) from error


IssueCommentPublicationResult = Literal[
    "not_offered",
    "posted",
    "skipped",
    "failed",
]


def handle_issue_comment_publication(
    run: Run,
    *,
    decision_prompt: (
        Callable[..., bool] | None
    ) = None,
    comment_creator: Callable[
        [str, str],
        object,
    ] | None = None,
) -> IssueCommentPublicationResult:
    if (
        not run.draft_pr_created
        or run.draft_pr_number is None
        or run.draft_pr_url is None
        or run.github_issue_url is None
    ):
        return "not_offered"

    issue = parse_github_issue_url(
        run.github_issue_url
    )
    comment = build_issue_comment(
        pull_request_number=(
            run.draft_pr_number
        ),
        pull_request_url=run.draft_pr_url,
        repository_tests_passed=(
            repository_tests_succeeded(
                run
            )
        ),
    )
    ask_for_decision = (
        decision_prompt
        or ask_for_issue_comment_decision
    )
    post_comment = (
        comment_creator
        or create_issue_comment
    )

    show_draft_pull_request_created()
    show_issue_comment_preview(
        issue.issue_number,
        comment,
    )

    should_post = ask_for_decision(
        lambda: show_issue_comment_details(
            issue_url=run.github_issue_url,
            issue_number=issue.issue_number,
            pull_request_url=run.draft_pr_url,
            pull_request_number=(
                run.draft_pr_number
            ),
            comment=comment,
        )
    )

    if not should_post:
        show_issue_comment_skipped()
        return "skipped"

    try:
        post_comment(
            run.github_issue_url,
            comment,
        )
    except GitHubIssueCommentError as error:
        show_issue_comment_failure(
            run.draft_pr_url,
            str(error),
        )
        return "failed"
    except Exception:
        show_issue_comment_failure(
            run.draft_pr_url,
            (
                "An unexpected error occurred while posting "
                "the GitHub issue comment."
            ),
        )
        return "failed"

    show_issue_comment_posted()
    return "posted"

def _read_validated_value(
    prompt: str,
    validator,
    error_message: str,
) -> str:
    while True:
        value = input(
            f"{prompt}\n> "
        ).strip()

        if not value:
            print(
                "A value is required."
            )
            print()
            continue

        if not validator(value):
            print(
                error_message
            )
            print()
            continue

        print()
        return value

def _is_github_repository_url(
    value: str,
) -> bool:
    parsed = urlparse(value)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        return False

    if parsed.netloc.lower() != "github.com":
        return False

    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    return len(parts) == 2


def _is_github_issue_url(
    value: str,
) -> bool:
    parsed = urlparse(value)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        return False

    if parsed.netloc.lower() != "github.com":
        return False

    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    if len(parts) != 4:
        return False

    if parts[2] != "issues":
        return False

    return parts[3].isdigit()

def _read_required_value(
    prompt: str,
) -> str:
    while True:
        value = input(
            f"{prompt}\n> "
        ).strip()

        if value:
            print()
            return value

        print(
            "A value is required."
        )
        print()


def _rollback_unpublished_run(
    run: Run,
) -> None:
    if (
        run.project_source
        != ProjectSource.GITHUB
    ):
        return

    if (
        run.original_branch is None
        or run.run_branch is None
    ):
        return

    project = load_project(
        run.project_name,
        run.project_source,
    )

    rollback_run_branch(
        project.repository_path,
        run.original_branch,
        run.run_branch,
    )


def _cancel_unpublished_run(
    run: Run,
) -> None:
    _rollback_unpublished_run(
        run
    )

    fail_run(
        run.id
    )


if __name__ == "__main__":
    main()
