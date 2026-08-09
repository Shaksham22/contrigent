from datetime import datetime, timezone
from uuid import UUID

from contrigent_api.agents.issue_analyzer.output_schema import IssueAnalysis
from contrigent_api.models.run_record import Run, RunStatus


class RunNotFoundError(Exception):
    """Raised when a requested run does not exist."""


class InvalidRunTransitionError(Exception):
    """Raised when a run is moved to an invalid state."""


_runs: dict[UUID, Run] = {}


def create_run(sample_project_name: str) -> Run:
    run = Run(
        sample_project_name=sample_project_name,
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