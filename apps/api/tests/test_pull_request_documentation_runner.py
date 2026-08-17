from pathlib import Path

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)
from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.models.run_record import (
    Run,
    RunStatus,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.services.pull_request_documentation_runner import (
    build_proposed_changes_section,
    build_pull_request_documentation_input,
)


def make_replacement() -> FileReplacement:
    return FileReplacement(
        file_path="src/inventory.py",
        reason=(
            "Validate the complete order "
            "before mutation."
        ),
        replacement_content=(
            "SECRET_REPLACEMENT_CONTENT"
        ),
    )


def test_proposed_changes_contain_path_and_reason_only() -> None:
    section = build_proposed_changes_section(
        [make_replacement()]
    )

    assert "src/inventory.py" in section
    assert (
        "Validate the complete order "
        "before mutation."
        in section
    )
    assert (
        "SECRET_REPLACEMENT_CONTENT"
        not in section
    )


def test_documentation_input_excludes_internal_agent_evidence(
    tmp_path: Path,
) -> None:
    project = ProjectContext(
        project_name="example",
        project_source=ProjectSource.GITHUB,
        repository_path=tmp_path,
        issue="# Public issue\n\nFix the behavior.",
        readme="Example",
        contributing="Run tests.",
        files={},
    )
    run = Run(
        project_name="example",
        project_source=ProjectSource.GITHUB,
        status=RunStatus.CREATING_DRAFT_PR,
        run_branch="contrigent/example",
        commit_sha="a" * 40,
        proposed_files=[make_replacement()],
        worker_results={
            "python_solver": WorkerResult(
                summary="INTERNAL_WORKER_REASONING",
                findings=[
                    "INTERNAL_WORKER_FINDING"
                ],
                files_to_replace=[
                    make_replacement()
                ],
            )
        },
        reviewer_result=ReviewerResult(
            recommendation="approve",
            summary="INTERNAL_REVIEWER_SUMMARY",
            findings=[],
            files_reviewed=[
                "src/inventory.py"
            ],
        ),
        repository_test_result=(
            RepositoryTestResult(
                passed=True,
                stage="tests",
                command=["pytest"],
                exit_code=0,
                duration_seconds=0.1,
                stdout="12 passed",
                stderr="",
            )
        ),
    )

    documentation_input = (
        build_pull_request_documentation_input(
            project,
            run,
            issue_number=17,
        )
    )

    assert "=== VERIFIED PROPOSED CHANGES ===" in documentation_input
    assert "src/inventory.py" in documentation_input
    assert "COMMAND: pytest" in documentation_input
    assert "12 passed" in documentation_input
    assert "INTERNAL_WORKER_REASONING" not in documentation_input
    assert "INTERNAL_WORKER_FINDING" not in documentation_input
    assert "INTERNAL_REVIEWER_SUMMARY" not in documentation_input
    assert "INDEPENDENT REVIEW" not in documentation_input
