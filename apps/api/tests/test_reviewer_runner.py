from contrigent_api.agents.independent_reviewer.output_schema import (
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
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
from contrigent_api.services.reviewer_runner import (
    build_proposed_files_section,
    build_reviewer_input,
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
        "=== PREVIOUS REVIEW CONTEXT ==="
        in reviewer_input
    )

    assert (
        "The first attempt missed a boundary case."
        in reviewer_input
    )

    assert (
        "Do not preserve a previous conclusion automatically."
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