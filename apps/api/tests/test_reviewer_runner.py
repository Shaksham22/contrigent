from pathlib import Path

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewFinding,
    ReviewerResult,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    ImplementationStep,
    IssueAnalysis,
)

from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
)
from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
from contrigent_api.services.reviewer_runner import (
    build_proposed_files_section,
    build_reviewer_input,
)
from contrigent_api.services.worker_runner import (
    merge_proposed_files,
)

def test_proposed_file_content_is_separated_from_reason_metadata() -> None:
    proposed_file = FileReplacement(
        file_path="src/example.py",
        reason="Fix the example bug.",
        replacement_content='"""Example module."""\n\nvalue = 1\n',
    )

    section = build_proposed_files_section(
        [proposed_file]
    )

    assert "CHANGE REASON METADATA:" in section
    assert "Fix the example bug." in section

    assert (
        "--- REPLACEMENT CONTENT START ---\n"
        '"""Example module."""'
    ) in section

    replacement_section = section.split(
        "--- REPLACEMENT CONTENT START ---",
        maxsplit=1,
    )[1].split(
        "--- REPLACEMENT CONTENT END ---",
        maxsplit=1,
    )[0]

    assert '"""Example module."""' in replacement_section
    assert "value = 1" in replacement_section
    assert "Fix the example bug." not in replacement_section
    assert "CHANGE REASON METADATA:" not in replacement_section
    assert (
        "The change reason above is metadata"
        in section
    )

def test_second_review_input_contains_previous_review_context() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    analysis = IssueAnalysis(
        summary="Revise the solution.",
        acceptance_criteria=[
            "Handle the missing display name."
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
                description="Revise the implementation.",
            )
        ],
    )

    previous_review = ReviewerResult(
        recommendation="changes_required",
        summary="The first attempt missed a boundary case.",
        findings=[],
        files_reviewed=["src/users.py"],
    )

    reviewer_input = build_reviewer_input(
        sample_project,
        analysis,
        worker_results={},
        proposed_files=[],
        previous_reviewer_result=previous_review,
    )

    assert (
        "=== PREVIOUS REVIEW CONTEXT — HISTORICAL ==="
        in reviewer_input
    )

    assert (
        "The first attempt missed a boundary case."
        in reviewer_input
    )

    assert (
        "Previous review findings describe an earlier candidate state."
        in reviewer_input
    )


def test_second_review_uses_latest_materialized_candidate() -> None:
    original_project = ProjectContext(
        project_name="example",
        project_source=ProjectSource.SAMPLE,
        repository_path=Path("/tmp/example"),
        issue="Correct the example behavior.",
        readme="Example repository.",
        contributing="Run the tests.",
        files={
            "src/example.py": "ORIGINAL\n",
        },
    )
    analysis = IssueAnalysis(
        summary="Correct the example behavior.",
        acceptance_criteria=[
            "The corrected behavior is implemented."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=["src/example.py"],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        worker_assignments=[],
        implementation_plan=[
            ImplementationStep(
                order=1,
                description="Correct the implementation.",
            )
        ],
    )
    old_candidate = FileReplacement(
        file_path="src/example.py",
        reason="Initial candidate.",
        replacement_content="OLD_CANDIDATE\n",
    )
    revised_candidate = FileReplacement(
        file_path="src/example.py",
        reason="Address the first review.",
        replacement_content="NEW_CANDIDATE\n",
    )
    merged_candidate = merge_proposed_files(
        original_project,
        [old_candidate],
        [revised_candidate],
    )
    previous_review = ReviewerResult(
        recommendation="changes_required",
        summary="The earlier candidate needs correction.",
        findings=[
            ReviewFinding(
                category="correctness",
                description=(
                    "OLD_CANDIDATE still contains the defect."
                ),
                severity="high",
            )
        ],
        files_reviewed=["src/example.py"],
    )

    reviewer_input = build_reviewer_input(
        original_project,
        analysis,
        worker_results={},
        proposed_files=merged_candidate,
        previous_reviewer_result=previous_review,
    )

    materialized_context = reviewer_input.split(
        "=== CURRENT MATERIALIZED CANDIDATE CONTEXT ===",
        maxsplit=1,
    )[1].split(
        "=== WORKER RESULTS ===",
        maxsplit=1,
    )[0]
    combined_proposed_files = reviewer_input.split(
        "=== COMBINED PROPOSED FILES ===",
        maxsplit=1,
    )[1].split(
        "=== CANDIDATE DOCKER TEST RESULT ===",
        maxsplit=1,
    )[0]
    historical_review = reviewer_input.split(
        "=== PREVIOUS REVIEW CONTEXT — HISTORICAL ===",
        maxsplit=1,
    )[1]

    assert "NEW_CANDIDATE" in materialized_context
    assert "OLD_CANDIDATE" not in materialized_context
    assert "NEW_CANDIDATE" in combined_proposed_files
    assert "OLD_CANDIDATE" not in combined_proposed_files
    assert "OLD_CANDIDATE" in historical_review
    assert (
        "The CURRENT MATERIALIZED CANDIDATE CONTEXT and "
        "COMBINED PROPOSED FILES are\nauthoritative."
        in reviewer_input
    )

def test_reviewer_input_contains_candidate_docker_result() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    analysis = IssueAnalysis(
        summary="Review the tested candidate.",
        acceptance_criteria=[
            "Handle the missing display name."
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
                    "Review the candidate."
                ),
            )
        ],
    )

    test_result = RepositoryTestResult(
        passed=True,
        stage="tests",
        command=[
            "pytest"
        ],
        exit_code=0,
        duration_seconds=0.1,
        stdout="21 passed",
        stderr="",
    )

    reviewer_input = build_reviewer_input(
        sample_project,
        analysis,
        worker_results={},
        proposed_files=[],
        candidate_test_result=(
            test_result
        ),
    )

    assert (
        "=== CANDIDATE DOCKER TEST RESULT ==="
        in reviewer_input
    )

    assert (
        "21 passed"
        in reviewer_input
    )
