import pytest
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
from contrigent_api.services.worker_runner import (
    build_project_with_proposed_files,
    merge_proposed_files,
    remove_unchanged_replacements,
    validate_replacement_path,
)

from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    ImplementationStep,
    IssueAnalysis,
)

from contrigent_api.services.worker_runner import (
    build_worker_input,
    get_available_worker,
)


def test_python_solver_is_available() -> None:
    worker = get_available_worker(
        "python_solver"
    )

    assert worker["id"] == "python_solver"
    assert worker["enabled"] is True


def test_unknown_worker_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="Worker is not available",
    ):
        get_available_worker(
            "made_up_solver"
        )


def test_unsafe_replacement_path_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="unsafe replacement path",
    ):
        validate_replacement_path(
            "../../outside.py"
        )


def test_unchanged_replacement_is_removed() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    original_content = sample_project.files[
        "tests/test_users.py"
    ]

    worker_result = WorkerResult(
        summary="No test changes needed.",
        findings=[
            "Existing tests already cover the behavior."
        ],
        files_to_replace=[
            FileReplacement(
                file_path="tests/test_users.py",
                reason="No changes required.",
                replacement_content=original_content,
            )
        ],
    )

    cleaned_result = remove_unchanged_replacements(
        worker_result,
        sample_project,
    )

    assert cleaned_result.files_to_replace == []


def test_revision_project_contains_first_proposed_changes() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    first_proposal = FileReplacement(
        file_path="src/users.py",
        reason="First implementation attempt.",
        replacement_content="first candidate source",
    )

    revision_project = build_project_with_proposed_files(
        sample_project,
        [first_proposal],
    )

    assert (
        revision_project.files["src/users.py"]
        == "first candidate source"
    )

    assert (
        sample_project.files["src/users.py"]
        != "first candidate source"
    )


def test_revised_files_override_first_attempt_and_keep_unchanged_files() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    first_files = [
        FileReplacement(
            file_path="src/users.py",
            reason="First implementation attempt.",
            replacement_content="first candidate source",
        ),
        FileReplacement(
            file_path="tests/test_users.py",
            reason="First regression test.",
            replacement_content="first candidate tests",
        ),
    ]

    revised_files = [
        FileReplacement(
            file_path="src/users.py",
            reason="Address reviewer feedback.",
            replacement_content="revised candidate source",
        )
    ]

    final_files = merge_proposed_files(
        sample_project,
        first_files,
        revised_files,
    )

    final_by_path = {
        replacement.file_path: replacement
        for replacement in final_files
    }

    assert (
        final_by_path["src/users.py"].replacement_content
        == "revised candidate source"
    )

    assert (
        final_by_path["tests/test_users.py"].replacement_content
        == "first candidate tests"
    )


def test_revision_can_remove_a_first_attempt_change() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    original_content = sample_project.files[
        "tests/test_users.py"
    ]

    first_files = [
        FileReplacement(
            file_path="tests/test_users.py",
            reason="First regression test.",
            replacement_content="unnecessary test change",
        )
    ]

    revised_files = [
        FileReplacement(
            file_path="tests/test_users.py",
            reason="Remove unnecessary first-attempt change.",
            replacement_content=original_content,
        )
    ]

    final_files = merge_proposed_files(
        sample_project,
        first_files,
        revised_files,
    )

    assert final_files == []

def test_worker_input_contains_actual_candidate_test_failure() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    analysis = IssueAnalysis(
        summary="Fix the candidate failure.",
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
                    "Fix the failure."
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
        stdout="1 failed, 20 passed",
        stderr="",
    )

    worker_input = build_worker_input(
        "python_solver",
        "Fix the failing candidate.",
        shared_worker_results={},
        sample_project=sample_project,
        issue_analysis=analysis,
        candidate_test_result=(
            test_result
        ),
    )

    assert (
        "=== CANDIDATE DOCKER TEST RESULT ==="
        in worker_input
    )

    assert (
        "1 failed, 20 passed"
        in worker_input
    )