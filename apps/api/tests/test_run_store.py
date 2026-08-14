import pytest

from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    ImplementationStep,
    IssueAnalysis,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
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
    start_revision_worker_work,
    complete_review,
    start_review,
    approve_final_changes,
    start_applying_changes,
    complete_applying_changes,
    start_repository_tests,
    complete_repository_tests,
    start_commit,
    complete_commit,
    start_push,
    complete_push,
    start_draft_pr,
    complete_draft_pr,
)

from contrigent_api.models.project_context import (
    ProjectSource,
)

from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
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


def test_review_starts_after_workers_complete() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    attach_analysis(
        run.id,
        make_analysis(),
    )

    approve_plan(run.id)
    start_worker_work(run.id)

    complete_worker_work(
        run.id,
        {},
        [],
    )

    updated_run = start_review(
        run.id
    )

    assert (
        updated_run.status
        == RunStatus.RUNNING_REVIEWER
    )


def test_review_moves_run_to_final_approval() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    attach_analysis(
        run.id,
        make_analysis(),
    )

    approve_plan(run.id)
    start_worker_work(run.id)

    complete_worker_work(
        run.id,
        {},
        [],
    )

    start_review(run.id)

    reviewer_result = ReviewerResult(
        recommendation="approve",
        summary="The proposed solution addresses the issue.",
        findings=[],
        files_reviewed=["src/users.py"],
    )

    reviewed_run = complete_review(
        run.id,
        reviewer_result,
    )

    assert (
        reviewed_run.status
        == RunStatus.AWAITING_FINAL_APPROVAL
    )

    assert (
        reviewed_run.reviewer_result
        == reviewer_result
    )


def test_final_approval_happens_after_review() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    attach_analysis(
        run.id,
        make_analysis(),
    )

    approve_plan(run.id)
    start_worker_work(run.id)

    complete_worker_work(
        run.id,
        {},
        [],
    )

    start_review(run.id)

    reviewer_result = ReviewerResult(
        recommendation="approve",
        summary="The proposed solution addresses the issue.",
        findings=[],
        files_reviewed=["src/users.py"],
    )

    complete_review(
        run.id,
        reviewer_result,
    )

    approved_run = approve_final_changes(
        run.id
    )

    assert (
        approved_run.status
        == RunStatus.FINAL_APPROVED
    )

    assert approved_run.final_approved is True
    assert approved_run.final_approved_at is not None

def test_final_approval_is_rejected_before_review() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    with pytest.raises(
        InvalidRunTransitionError,
        match="only allowed after review",
    ):
        approve_final_changes(
            run.id
        )

def test_changes_are_applied_after_final_approval() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    attach_analysis(
        run.id,
        make_analysis(),
    )

    approve_plan(run.id)
    start_worker_work(run.id)

    complete_worker_work(
        run.id,
        {},
        [],
    )

    start_review(run.id)

    reviewer_result = ReviewerResult(
        recommendation="approve",
        summary="The proposed solution addresses the issue.",
        findings=[],
        files_reviewed=["src/users.py"],
    )

    complete_review(
        run.id,
        reviewer_result,
    )

    approve_final_changes(run.id)

    start_applying_changes(
        run.id
    )

    updated_run = complete_applying_changes(
        run.id,
        original_branch="main",
        run_branch="contrigent/test-run",
        applied_files=[
            "src/users.py"
        ],
    )

    assert (
        updated_run.status
        == RunStatus.CHANGES_APPLIED
    )

    assert (
        updated_run.changes_applied
        is True
    )

    assert (
        updated_run.original_branch
        == "main"
    )

    assert (
        updated_run.run_branch
        == "contrigent/test-run"
    )

    assert (
        updated_run.applied_files
        == ["src/users.py"]
    )
    testing_run = start_repository_tests(
    run.id
    )

    assert (
        testing_run.status
        == RunStatus.RUNNING_TESTS
    )

    test_result = RepositoryTestResult(
        passed=True,
        stage="tests",
        command=[
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
        ],
        exit_code=0,
        duration_seconds=0.02,
        stdout="10 passed",
        stderr="",
    )

    tested_run = complete_repository_tests(
        run.id,
        test_result,
    )

    assert (
        tested_run.status
        == RunStatus.TESTS_PASSED
    )

    assert (
        tested_run.repository_tests_completed
        is True
    )

    assert (
        tested_run.repository_tests_passed
        is True
    )

    assert (
        tested_run.repository_test_result
        == test_result
    )

def test_successful_publish_lifecycle() -> None:
    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
    )

    run.status = RunStatus.TESTS_PASSED

    start_commit(
        run.id
    )

    complete_commit(
        run.id,
        commit_sha="a" * 40,
        commit_message="Fix issue #1",
    )

    start_push(
        run.id
    )

    complete_push(
        run.id
    )

    start_draft_pr(
        run.id
    )

    completed_run = complete_draft_pr(
        run.id,
        pr_number=12,
        pr_url=(
            "https://github.com/example/demo/pull/12"
        ),
    )

    assert (
        completed_run.status
        == RunStatus.COMPLETED
    )

    assert completed_run.commit_created is True
    assert completed_run.branch_pushed is True
    assert completed_run.draft_pr_created is True
    assert completed_run.draft_pr_number == 12


def test_changes_required_review_can_start_revision_workers() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    original_analysis = make_analysis()

    revised_analysis = make_analysis().model_copy(
        update={
            "summary": "Revise the proposed solution."
        }
    )

    attach_analysis(
        run.id,
        original_analysis,
    )

    approve_plan(run.id)
    start_worker_work(run.id)

    complete_worker_work(
        run.id,
        {},
        [],
    )

    start_review(run.id)

    reviewer_result = ReviewerResult(
        recommendation="changes_required",
        summary="A revision is required.",
        findings=[],
        files_reviewed=["src/users.py"],
    )

    revised_run = start_revision_worker_work(
        run.id,
        revised_analysis,
        reviewer_result,
    )

    assert (
        revised_run.status
        == RunStatus.RUNNING_WORKERS
    )

    assert revised_run.analysis == revised_analysis
    assert revised_run.reviewer_result == reviewer_result
    assert revised_run.worker_work_completed is False


def test_approved_review_cannot_start_revision_workers() -> None:
    run = create_run(
        "python-missing-display-name"
    )

    analysis = make_analysis()

    attach_analysis(
        run.id,
        analysis,
    )

    approve_plan(run.id)
    start_worker_work(run.id)

    complete_worker_work(
        run.id,
        {},
        [],
    )

    start_review(run.id)

    reviewer_result = ReviewerResult(
        recommendation="approve",
        summary="The solution is approved.",
        findings=[],
        files_reviewed=["src/users.py"],
    )

    with pytest.raises(
        InvalidRunTransitionError,
        match="changes_required",
    ):
        start_revision_worker_work(
            run.id,
            analysis,
            reviewer_result,
        )