from datetime import datetime, timezone
from uuid import UUID

from contrigent_api.agents.issue_analyzer.output_schema import IssueAnalysis
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

class RunNotFoundError(Exception):
    """Raised when a requested run does not exist."""


class InvalidRunTransitionError(Exception):
    """Raised when a run is moved to an invalid state."""


_runs: dict[UUID, Run] = {}


def create_run(
    project_name: str,
    project_source: ProjectSource = ProjectSource.SAMPLE,
) -> Run:
    run = Run(
        project_name=project_name,
        project_source=project_source,
        status=RunStatus.ANALYZING,
    )

    _runs[run.id] = run

    return run


def get_run(run_id: UUID) -> Run:
    run = _runs.get(run_id)

    if run is None:
        raise RunNotFoundError(str(run_id))

    return run


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
def start_review(
    run_id: UUID,
) -> Run:
    run = get_run(run_id)

    if run.status != RunStatus.WORKERS_COMPLETED:
        raise InvalidRunTransitionError(
            "Review cannot start before worker work is completed."
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