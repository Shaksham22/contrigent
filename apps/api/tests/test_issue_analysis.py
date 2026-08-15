from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
import pytest

from contrigent_api.services.issue_analysis_runner import (
    build_analysis_input,
    build_revision_input,
    build_test_failure_revision_input,
    validate_worker_assignments,
)

from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    ImplementationStep,
    IssueAnalysis,
    WorkerAssignment,
)
from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewFinding,
    ReviewerResult,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)

def test_build_analysis_input_contains_repository_context() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    agent_input = build_analysis_input(
        sample_project,
        workers=[],
    )

    assert "Handle users without a display name" in agent_input
    assert "All behavioral changes must include automated tests" in agent_input
    assert "src/users.py" in agent_input
    assert "display_name.upper()" in agent_input
    assert (
        "=== REPOSITORY FILE TREE ==="
        in agent_input
    )

    assert (
        "=== SELECTED REPOSITORY FILE CONTENT ==="
        in agent_input
    )
    
def test_unavailable_required_worker_is_rejected() -> None:
    workers = [
        {
            "id": "backend_solver",
            "enabled": True,
        }
    ]

    with pytest.raises(
        ValueError,
        match="unavailable workers",
    ):
        validate_worker_assignments(
            [
                WorkerAssignment(
                    order=1,
                    worker_id="made_up_solver",
                    task="Fix the backend bug.",
                    depends_on=[],
                )
            ],
            workers,
        )

def test_build_analysis_input_contains_available_workers() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    workers = [
        {
            "id": "backend_solver",
            "name": "Backend Solver",
            "description": "Handles backend Python work.",
            "capabilities": [
                "backend",
                "python",
                "api",
            ],
            "enabled": True,
            "model": "gpt-test",
        },
        {
            "id": "disabled_solver",
            "name": "Disabled Solver",
            "description": "Should not be available.",
            "capabilities": ["testing"],
            "enabled": False,
            "model": "gpt-test",
        },
    ]

    agent_input = build_analysis_input(
        sample_project,
        workers,
    )

    assert "=== AVAILABLE WORKERS ===" in agent_input
    assert "backend_solver" in agent_input
    assert "Backend Solver" in agent_input
    assert "Handles backend Python work." in agent_input
    assert "backend, python, api" in agent_input

    assert "disabled_solver" not in agent_input

def test_build_revision_input_contains_review_and_previous_attempt() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    original_analysis = IssueAnalysis(
        summary="Fix display-name handling.",
        acceptance_criteria=[
            "Use username as fallback."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=["src/users.py"],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        worker_assignments=[],
        implementation_plan=[
            ImplementationStep(
                order=1,
                description="Update display-name logic.",
            )
        ],
    )

    worker_result = WorkerResult(
        summary="Proposed a fallback.",
        findings=[
            "The old code assumes display_name is present."
        ],
        files_to_replace=[],
    )

    proposed_file = FileReplacement(
        file_path="src/users.py",
        reason="Add the fallback.",
        replacement_content="updated source",
    )

    reviewer_result = ReviewerResult(
        recommendation="changes_required",
        summary="The fallback misses a boundary case.",
        findings=[
            ReviewFinding(
                category="correctness",
                description="Handle the empty-string case.",
                severity="medium",
            )
        ],
        files_reviewed=["src/users.py"],
    )

    agent_input = build_revision_input(
        sample_project,
        workers=[],
        original_analysis=original_analysis,
        worker_results={
            "python_solver": worker_result
        },
        proposed_files=[proposed_file],
        reviewer_result=reviewer_result,
    )

    assert "=== REVISION TASK ===" in agent_input
    assert "Proposed a fallback." in agent_input
    assert "updated source" in agent_input
    assert (
        "The fallback misses a boundary case."
        in agent_input
    )
    assert "Do not expand scope" in agent_input


def test_build_test_failure_revision_input_contains_execution_evidence() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    analysis = IssueAnalysis(
        summary="Fix display-name handling.",
        acceptance_criteria=[
            "Use username as fallback."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=[
            "src/users.py"
        ],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        worker_assignments=[],
        implementation_plan=[
            ImplementationStep(
                order=1,
                description=(
                    "Update display-name logic."
                ),
            )
        ],
    )

    test_result = RepositoryTestResult(
        passed=False,
        stage="tests",
        command=[
            "pytest"
        ],
        exit_code=1,
        duration_seconds=0.1,
        stdout="1 failed, 9 passed",
        stderr="",
    )

    agent_input = (
        build_test_failure_revision_input(
            sample_project,
            workers=[],
            current_analysis=analysis,
            worker_results={},
            proposed_files=[],
            test_result=test_result,
        )
    )

    assert (
        "=== TEST FAILURE REMEDIATION TASK ==="
        in agent_input
    )

    assert (
        "1 failed, 9 passed"
        in agent_input
    )

    assert (
        "Do not weaken or delete "
        "a valid failing test"
        in agent_input
    )

    assert (
        "Preserve valid existing and "
        "previously proposed tests"
        in agent_input
    )