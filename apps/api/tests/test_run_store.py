import pytest

from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    ImplementationStep,
    IssueAnalysis,
)
from contrigent_api.models.run_record import RunStatus
from contrigent_api.services.run_memory_store import (
    InvalidRunTransitionError,
    approve_plan,
    attach_analysis,
    clear_runs,
    create_run,
)


@pytest.fixture(autouse=True)
def reset_run_store() -> None:
    clear_runs()


def make_analysis() -> IssueAnalysis:
    return IssueAnalysis(
        summary="Handle a missing display name.",
        acceptance_criteria=[
            "Fall back to username when display_name is None."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=[
            "src/users.py",
            "tests/test_users.py",
        ],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        implementation_plan=[
            ImplementationStep(
                order=1,
                description="Update get_display_name.",
            )
        ],
    )


def test_new_run_starts_analyzing() -> None:
    run = create_run("python-missing-display-name")

    assert run.status == RunStatus.ANALYZING
    assert run.analysis is None
    assert run.plan_approved is False


def test_analysis_moves_run_to_awaiting_approval() -> None:
    run = create_run("python-missing-display-name")

    updated_run = attach_analysis(
        run.id,
        make_analysis(),
    )

    assert updated_run.status == RunStatus.AWAITING_PLAN_APPROVAL
    assert updated_run.analysis is not None
    assert updated_run.plan_approved is False


def test_plan_can_be_approved_after_analysis() -> None:
    run = create_run("python-missing-display-name")

    attach_analysis(
        run.id,
        make_analysis(),
    )

    approved_run = approve_plan(run.id)

    assert approved_run.status == RunStatus.PLAN_APPROVED
    assert approved_run.plan_approved is True
    assert approved_run.plan_approved_at is not None


def test_plan_cannot_be_approved_before_analysis() -> None:
    run = create_run("python-missing-display-name")

    with pytest.raises(InvalidRunTransitionError):
        approve_plan(run.id)