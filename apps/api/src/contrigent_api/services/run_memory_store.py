from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    IssueAnalysis,
)
from contrigent_api.models.run_record import Run, RunStatus
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)


from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)

from contrigent_api.models.project_context import (
    ProjectSource,
)

if TYPE_CHECKING:
    from contrigent_api.services.repository_environment_verifier import (
        VerifiedRepositoryTestRecipe,
    )

class RunNotFoundError(Exception):
    """Raised when a requested run does not exist."""


class InvalidRunTransitionError(Exception):
    """Raised when a run is moved to an invalid state."""


_runs: dict[UUID, Run] = {}
_verified_repository_test_recipes: dict[
    UUID,
    VerifiedRepositoryTestRecipe,
] = {}
_agent_invocation_counts: dict[
    UUID,
    dict[str, int],
] = {}


def create_run(
    project_name: str,
    project_source: ProjectSource = ProjectSource.SAMPLE,
    github_issue_url: str | None = None,
    github_repository_url: str | None = None,
    max_review_rounds: int = 2,
    max_testing_rounds: int = 2,
) -> Run:
    run = Run(
        project_name=project_name,
        project_source=project_source,
        github_issue_url=github_issue_url,
        github_repository_url=github_repository_url,
        max_review_rounds=max_review_rounds,
        max_testing_rounds=max_testing_rounds,
        status=RunStatus.ANALYZING,
    )

    _runs[run.id] = run

    return run


def get_run(run_id: UUID) -> Run:
    run = _runs.get(run_id)

    if run is None:
        raise RunNotFoundError(str(run_id))

    return run


def get_agent_invocation_count(
    run_id: UUID,
    agent_id: str,
) -> int:
    get_run(run_id)

    return _agent_invocation_counts.get(
        run_id,
        {},
    ).get(
        agent_id,
        0,
    )


def record_agent_invocation(
    run_id: UUID,
    agent_id: str,
) -> int:
    get_run(run_id)
    clean_agent_id = agent_id.strip()

    if not clean_agent_id:
        raise ValueError(
            "Agent ID cannot be blank."
        )

    run_counts = (
        _agent_invocation_counts.setdefault(
            run_id,
            {},
        )
    )
    invocation_number = (
        run_counts.get(clean_agent_id, 0)
        + 1
    )
    run_counts[clean_agent_id] = (
        invocation_number
    )

    return invocation_number


def store_verified_repository_test_recipe(
    run_id: UUID,
    recipe: VerifiedRepositoryTestRecipe,
) -> None:
    run = get_run(run_id)

    if run.status != RunStatus.ANALYZING:
        raise InvalidRunTransitionError(
            "Repository preflight must finish before analysis."
        )

    if not recipe.setup_verified:
        raise InvalidRunTransitionError(
            "Cannot store an unverified repository test recipe."
        )

    if (
        recipe.baseline_result.stage != "tests"
        or not recipe.baseline_result.passed
    ):
        raise InvalidRunTransitionError(
            "Cannot store a recipe without a passing baseline."
        )

    _verified_repository_test_recipes[
        run_id
    ] = recipe


def get_verified_repository_test_recipe(
    run_id: UUID,
) -> VerifiedRepositoryTestRecipe:
    get_run(run_id)

    try:
        return _verified_repository_test_recipes[
            run_id
        ]
    except KeyError as error:
        raise InvalidRunTransitionError(
            "Run has no verified repository test recipe."
        ) from error


def attach_analysis(
    run_id: UUID,
    analysis: IssueAnalysis,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.ANALYZING:
        raise InvalidRunTransitionError(
            f"Cannot attach analysis while run is '{run.status.value}'."
        )

    run.analysis = analysis
    run.status = RunStatus.AWAITING_PLAN_APPROVAL

    return run

def finish_analysis_without_worker_work(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.AWAITING_PLAN_APPROVAL:
        raise InvalidRunTransitionError(
            "Analysis can only finish early before plan approval."
        )

    if run.analysis is None:
        raise InvalidRunTransitionError(
            "Cannot finish analysis without an analysis result."
        )

    if (
        run.analysis.feasibility
        == Feasibility.FEASIBLE
    ):
        if run.analysis.worker_assignments:
            raise InvalidRunTransitionError(
                "A feasible run with assigned workers "
                "must continue through plan approval."
            )

        run.completed_at = datetime.now(
            timezone.utc
        )
        run.status = RunStatus.COMPLETED

        return run

    run.status = RunStatus.FAILED

    return run

def approve_plan(run_id: UUID) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.AWAITING_PLAN_APPROVAL:
        raise InvalidRunTransitionError(
            f"Cannot approve plan while run is '{run.status.value}'."
        )

    if run.analysis is None:
        raise InvalidRunTransitionError(
            "Cannot approve a run without an analysis."
        )

    run.plan_approved = True
    run.plan_approved_at = datetime.now(timezone.utc)
    run.status = RunStatus.PLAN_APPROVED

    return run


def clear_runs() -> None:
    """Clear the in-memory store. Used by automated tests."""
    _runs.clear()
    _verified_repository_test_recipes.clear()
    _agent_invocation_counts.clear()



def start_worker_work(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.PLAN_APPROVED:
        raise InvalidRunTransitionError(
            "Workers cannot run before plan approval."
        )

    run.status = RunStatus.RUNNING_WORKERS

    return run

def start_test_revision_worker_work(
    run_id: UUID,
    revised_analysis: IssueAnalysis,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.WORKERS_COMPLETED:
        raise InvalidRunTransitionError(
            "Test remediation can only start "
            "after worker work is completed."
        )

    if (
        run.candidate_test_result is None
        or run.candidate_test_result.passed
        or run.candidate_test_result.stage != "tests"
    ):
        raise InvalidRunTransitionError(
            "Test remediation requires a failed "
            "candidate test result."
        )

    if (
        run.testing_rounds_completed
        >= run.max_testing_rounds
    ):
        raise InvalidRunTransitionError(
            "No candidate testing rounds remain."
        )

    run.analysis = revised_analysis
    # Keep the failed test result available as
    # remediation evidence until the next candidate
    # is actually tested. record_candidate_test_result()
    # will replace it with the next testing result.

    run.worker_work_completed = False
    run.status = RunStatus.RUNNING_WORKERS

    return run


def start_revision_worker_work(
    run_id: UUID,
    revised_analysis: IssueAnalysis,
    reviewer_result: ReviewerResult,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.RUNNING_REVIEWER:
        raise InvalidRunTransitionError(
            "Revision workers can only start after a review."
        )

    if reviewer_result.recommendation != "changes_required":
        raise InvalidRunTransitionError(
            "Revision workers require a changes_required review."
        )

    if (
        run.review_rounds_completed + 1
        >= run.max_review_rounds
    ):
        raise InvalidRunTransitionError(
            "No review rounds remain for another "
            "automatic revision."
        )

    run.review_rounds_completed += 1

    run.analysis = revised_analysis
    run.reviewer_result = reviewer_result

    # Reviewer remediation creates a new candidate,
    # so the previous Docker result is stale.
    run.candidate_test_result = None

    run.worker_work_completed = False
    run.status = RunStatus.RUNNING_WORKERS

    return run

def complete_worker_work(
    run_id: UUID,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.RUNNING_WORKERS:
        raise InvalidRunTransitionError(
            "Worker execution is not currently running."
        )

    run.worker_results = worker_results
    run.proposed_files = proposed_files
    run.worker_work_completed = True
    run.status = RunStatus.WORKERS_COMPLETED

    return run

def record_candidate_test_result(
    run_id: UUID,
    test_result: RepositoryTestResult,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.WORKERS_COMPLETED:
        raise InvalidRunTransitionError(
            "Candidate tests can only be recorded "
            "after worker work is completed."
        )

    if (
        test_result.stage == "tests"
        and run.testing_rounds_completed
        >= run.max_testing_rounds
    ):
        raise InvalidRunTransitionError(
            "No candidate testing rounds remain."
        )

    if test_result.stage == "tests":
        run.testing_rounds_completed += 1

    run.candidate_test_result = test_result

    return run


def start_review(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.WORKERS_COMPLETED:
        raise InvalidRunTransitionError(
            "Review cannot start before worker work is completed."
        )

    if (
        run.project_source == ProjectSource.GITHUB
        and (
            run.candidate_test_result is None
            or not run.candidate_test_result.passed
        )
    ):
        raise InvalidRunTransitionError(
            "GitHub proposals must pass candidate "
            "Docker tests before review."
        )

    run.status = RunStatus.RUNNING_REVIEWER

    return run


def complete_review(
    run_id: UUID,
    reviewer_result: ReviewerResult,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.RUNNING_REVIEWER:
        raise InvalidRunTransitionError(
            "Review is not currently running."
        )

    if (
        run.review_rounds_completed
        >= run.max_review_rounds
    ):
        raise InvalidRunTransitionError(
            "No review rounds remain."
        )

    run.review_rounds_completed += 1
    run.reviewer_result = reviewer_result
    run.status = RunStatus.AWAITING_FINAL_APPROVAL

    return run

def fail_run(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    run.status = RunStatus.FAILED

    return run



def approve_final_changes(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.AWAITING_FINAL_APPROVAL:
        raise InvalidRunTransitionError(
            "Final approval is only allowed after review."
        )

    run.final_approved = True
    run.final_approved_at = datetime.now(
        timezone.utc
    )
    run.status = RunStatus.FINAL_APPROVED

    return run


def start_applying_changes(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.FINAL_APPROVED:
        raise InvalidRunTransitionError(
            "Approved changes can only be applied "
            "after final approval."
        )

    run.status = RunStatus.APPLYING_CHANGES

    return run


def complete_applying_changes(
    run_id: UUID,
    original_branch: str,
    run_branch: str,
    applied_files: list[str],
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.APPLYING_CHANGES:
        raise InvalidRunTransitionError(
            "Changes can only be completed while "
            "the run is applying changes."
        )

    run.changes_applied = True
    run.changes_applied_at = datetime.now(
        timezone.utc
    )

    run.original_branch = original_branch
    run.run_branch = run_branch
    run.applied_files = applied_files

    run.status = RunStatus.CHANGES_APPLIED

    return run

def start_repository_tests(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.CHANGES_APPLIED:
        raise InvalidRunTransitionError(
            "Repository tests can only run "
            "after approved changes are applied."
        )

    run.status = RunStatus.RUNNING_TESTS

    return run


def complete_repository_tests(
    run_id: UUID,
    test_result: RepositoryTestResult,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.RUNNING_TESTS:
        raise InvalidRunTransitionError(
            "Repository tests are not currently running."
        )

    run.repository_tests_completed = True
    run.repository_tests_passed = (
        test_result.passed
    )

    run.repository_test_result = (
        test_result
    )

    run.repository_tests_completed_at = (
        datetime.now(
            timezone.utc
        )
    )

    if test_result.passed:
        run.status = RunStatus.TESTS_PASSED
    else:
        run.status = RunStatus.TESTS_FAILED

    return run


def start_commit(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.TESTS_PASSED:
        raise InvalidRunTransitionError(
            "A commit can only be created "
            "after repository tests pass."
        )

    run.status = RunStatus.COMMITTING

    return run


def complete_commit(
    run_id: UUID,
    commit_sha: str,
    commit_message: str,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.COMMITTING:
        raise InvalidRunTransitionError(
            "A commit is not currently being created."
        )

    run.commit_created = True
    run.commit_sha = commit_sha
    run.commit_message = commit_message
    run.committed_at = datetime.now(
        timezone.utc
    )

    run.status = RunStatus.COMMITTED

    return run


def start_push(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.COMMITTED:
        raise InvalidRunTransitionError(
            "A branch can only be pushed "
            "after its commit is created."
        )

    run.status = RunStatus.PUSHING

    return run


def complete_push(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.PUSHING:
        raise InvalidRunTransitionError(
            "A branch push is not currently running."
        )

    run.branch_pushed = True
    run.branch_pushed_at = datetime.now(
        timezone.utc
    )

    run.status = RunStatus.PUSHED

    return run


def start_draft_pr(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.PUSHED:
        raise InvalidRunTransitionError(
            "A draft pull request can only be created "
            "after the branch is pushed."
        )

    run.status = RunStatus.CREATING_DRAFT_PR

    return run


def complete_draft_pr(
    run_id: UUID,
    pr_number: int,
    pr_url: str,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.CREATING_DRAFT_PR:
        raise InvalidRunTransitionError(
            "A draft pull request is not currently "
            "being created."
        )

    run.draft_pr_created = True
    run.draft_pr_number = pr_number
    run.draft_pr_url = pr_url
    run.draft_pr_created_at = datetime.now(
        timezone.utc
    )

    run.completed_at = datetime.now(
        timezone.utc
    )

    run.status = RunStatus.COMPLETED

    return run
