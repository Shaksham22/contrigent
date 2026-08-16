import pytest
from contrigent_api.services.worker_discovery import (
    discover_workers,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
from contrigent_api.services.worker_runner import (
    build_project_with_proposed_files,
    load_worker_agent,
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
    WorkerAssignment,
)

from contrigent_api.services.worker_runner import (
    build_worker_input,
    get_available_worker,
    run_assigned_workers,
)

@pytest.mark.parametrize(
    "worker_id",
    [
        worker["id"]
        for worker in discover_workers()
        if worker.get("enabled") is True
    ],
)
def test_configured_worker_is_available(
    worker_id: str,
) -> None:
    worker = get_available_worker(
        worker_id
    )

    assert worker["id"] == worker_id
    assert worker["enabled"] is True


@pytest.mark.parametrize(
    "worker",
    [
        worker
        for worker in discover_workers()
        if worker.get("enabled") is True
    ],
    ids=lambda worker: worker["id"],
)
def test_enabled_worker_agent_definition_can_be_loaded(
    worker: dict,
) -> None:
    worker_agent = load_worker_agent(
        worker["id"]
    )

    assert worker_agent.name == worker["name"]
    assert worker_agent.output_type is WorkerResult

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


@pytest.mark.parametrize(
    "file_path",
    [
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    ],
)
def test_tool_generated_dependency_file_is_rejected(
    file_path: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "tool-generated dependency file "
            "that LLM workers cannot author"
        ),
    ):
        validate_replacement_path(
            file_path
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

@pytest.mark.asyncio
async def test_dependent_worker_receives_completed_worker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    analysis = IssueAnalysis(
        summary="Implement and test the fix.",
        acceptance_criteria=[
            "Fix the reported behavior."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=[
            "src/users.py",
            "tests/test_users.py",
        ],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        worker_assignments=[
            WorkerAssignment(
                order=1,
                worker_id="python_solver",
                task="Implement the fix.",
                depends_on=[],
            ),
            WorkerAssignment(
                order=2,
                worker_id="testing_specialist",
                task="Add regression coverage.",
                depends_on=[
                    "python_solver"
                ],
            ),
        ],
        implementation_plan=[
            ImplementationStep(
                order=1,
                description=(
                    "Implement and test."
                ),
            )
        ],
    )

    received_dependencies: dict[
        str,
        dict[str, WorkerResult],
    ] = {}

    async def fake_run_worker(
        worker_id: str,
        assigned_task: str,
        shared_worker_results: dict[
            str,
            WorkerResult,
        ],
        *_args,
        **_kwargs,
    ) -> WorkerResult:
        received_dependencies[
            worker_id
        ] = dict(
            shared_worker_results
        )

        return WorkerResult(
            summary=(
                f"{worker_id} completed"
            ),
            findings=[],
            files_to_replace=[],
        )

    monkeypatch.setattr(
        (
            "contrigent_api.services."
            "worker_runner.run_worker"
        ),
        fake_run_worker,
    )

    worker_results, proposed_files = (
        await run_assigned_workers(
            sample_project,
            analysis,
        )
    )

    assert (
        set(worker_results)
        == {
            "python_solver",
            "testing_specialist",
        }
    )

    assert (
        received_dependencies[
            "python_solver"
        ]
        == {}
    )

    assert (
        set(
            received_dependencies[
                "testing_specialist"
            ]
        )
        == {
            "python_solver"
        }
    )

    assert (
        received_dependencies[
            "testing_specialist"
        ][
            "python_solver"
        ].summary
        == "python_solver completed"
    )

    assert proposed_files == []
