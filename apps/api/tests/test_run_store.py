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
    complete_worker_work,
    create_run,
    start_worker_work,
)

from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
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
        worker_assignments=[],
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


def test_worker_work_starts_after_plan_approval() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    attach_analysis(
        run.id,
        make_analysis(),
    )

    approve_plan(run.id)

    updated_run = start_worker_work(
        run.id
    )

    assert (
        updated_run.status
        == RunStatus.RUNNING_WORKERS
    )


def test_worker_results_complete_run() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    attach_analysis(
        run.id,
        make_analysis(),
    )

    approve_plan(run.id)
    start_worker_work(run.id)

    worker_result = WorkerResult(
        summary="Fixed the Python bug.",
        findings=[],
        files_to_replace=[],
    )

    proposed_file = FileReplacement(
        file_path="src/users.py",
        reason="Fix missing display name.",
        replacement_content="updated file",
    )

    completed_run = complete_worker_work(
        run.id,
        {
            "python_solver": worker_result
        },
        [
            proposed_file
        ],
)

    assert (
        completed_run.status
        == RunStatus.WORKERS_COMPLETED
    )
    assert completed_run.worker_work_completed is True
    assert "python_solver" in completed_run.worker_results