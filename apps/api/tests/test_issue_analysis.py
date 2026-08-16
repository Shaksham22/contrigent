from pathlib import Path
from types import SimpleNamespace

from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
import pytest

from contrigent_api.services import (
    issue_analysis_runner,
)

from contrigent_api.services.issue_analysis_runner import (
    build_analysis_input,
    build_revision_input,
    build_test_failure_revision_input,
    validate_worker_assignments,
    build_proposed_file_ownership_section,
    find_test_referenced_proposed_paths,
    analyze_project,
    normalize_context_request_path,
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
from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.services.run_memory_store import (
    clear_runs,
    create_run,
    get_agent_invocation_count,
)


def make_context_project(
    files: dict[str, str],
) -> ProjectContext:
    return ProjectContext(
        project_name="context-example",
        project_source=ProjectSource.SAMPLE,
        repository_path=Path("context-example"),
        issue="Correct the repository behavior.",
        readme="Example repository.",
        contributing="Run the tests.",
        files=files,
    )


def make_manager_analysis(
    *,
    summary: str = "Analyze the repository behavior.",
    feasibility: Feasibility = Feasibility.NEEDS_CLARIFICATION,
    context_request_paths: list[str] | None = None,
    context_search_terms: list[str] | None = None,
    worker_assignments: list[WorkerAssignment] | None = None,
) -> IssueAnalysis:
    return IssueAnalysis(
        summary=summary,
        acceptance_criteria=[
            "The repository behavior is corrected."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=["src/example.py"],
        risks=[],
        feasibility=feasibility,
        context_request_paths=(
            context_request_paths or []
        ),
        context_search_terms=(
            context_search_terms or []
        ),
        worker_assignments=(
            worker_assignments or []
        ),
        implementation_plan=[],
    )


def install_manager_outputs(
    monkeypatch: pytest.MonkeyPatch,
    outputs: list[IssueAnalysis],
) -> list[str]:
    output_iterator = iter(outputs)
    manager_inputs: list[str] = []

    async def fake_runner_run(
        _agent,
        runner_input,
        **_kwargs,
    ):
        manager_inputs.append(runner_input)
        return SimpleNamespace(
            final_output=next(output_iterator),
            context_wrapper=SimpleNamespace(
                usage=f"usage-{len(manager_inputs)}"
            ),
        )

    monkeypatch.setattr(
        issue_analysis_runner.Runner,
        "run",
        fake_runner_run,
    )

    return manager_inputs

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


@pytest.mark.asyncio
async def test_analysis_without_context_request_invokes_manager_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {"src/example.py": "VALUE = 1\n"}
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                summary="No changes needed: behavior is correct.",
                feasibility=Feasibility.FEASIBLE,
            )
        ],
    )

    analysis, usage = await analyze_project(
        project,
        run_id=run.id,
    )

    assert len(manager_inputs) == 1
    assert analysis.context_request_paths == []
    assert analysis.context_search_terms == []
    assert usage == "usage-1"


@pytest.mark.asyncio
async def test_exact_context_request_is_supplied_to_second_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/example.py": "VALUE = 1\n",
            "src/implementation.py": (
                "EXACT_REQUEST_CONTENT = True\n"
            ),
        }
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=[
                    "src/implementation.py"
                ]
            ),
            make_manager_analysis(
                summary="The evidence is now sufficient.",
                feasibility=Feasibility.FEASIBLE,
            ),
        ],
    )

    await analyze_project(
        project,
        run_id=run.id,
    )

    assert len(manager_inputs) == 2
    assert (
        "=== ADDITIONAL REQUESTED REPOSITORY CONTEXT ==="
        in manager_inputs[1]
    )
    assert "src/implementation.py" in manager_inputs[1]
    assert "EXACT_REQUEST_CONTENT" in manager_inputs[1]


@pytest.mark.asyncio
async def test_exact_request_retrieves_file_omitted_from_initial_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/example.py": "VALUE = 1\n",
            "src/hidden.py": "HIDDEN_IMPLEMENTATION\n",
        }
    )
    run = create_run(project.project_name)
    monkeypatch.setattr(
        issue_analysis_runner,
        "build_repository_context",
        lambda *_args, **_kwargs: (
            "INITIAL_CONTEXT_WITHOUT_HIDDEN_FILE"
        ),
    )
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=["src/hidden.py"]
            ),
            make_manager_analysis(
                summary="The hidden implementation resolved the question.",
                feasibility=Feasibility.FEASIBLE,
            ),
        ],
    )

    await analyze_project(
        project,
        run_id=run.id,
    )

    assert "HIDDEN_IMPLEMENTATION" not in manager_inputs[0]
    assert "HIDDEN_IMPLEMENTATION" in manager_inputs[1]


@pytest.mark.asyncio
async def test_search_request_supplies_matching_repository_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/example.py": "VALUE = 1\n",
            "src/engine.py": (
                "class TaskCoordinator:\n"
                "    pass\n"
            ),
            "docs/overview.md": "General documentation.\n",
        }
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_search_terms=["TaskCoordinator"]
            ),
            make_manager_analysis(
                summary="The matching implementation is sufficient.",
                feasibility=Feasibility.FEASIBLE,
            ),
        ],
    )

    await analyze_project(
        project,
        run_id=run.id,
    )

    assert len(manager_inputs) == 2
    assert "--- FILE: src/engine.py ---" in manager_inputs[1]
    assert "class TaskCoordinator" in manager_inputs[1]


@pytest.mark.asyncio
async def test_duplicate_context_requests_are_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/example.py": "class TaskCoordinator: pass\n",
        }
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=[
                    "src/example.py",
                    "./src/example.py",
                    "src/example.py",
                ],
                context_search_terms=[
                    "TaskCoordinator",
                    " taskcoordinator ",
                ],
            ),
            make_manager_analysis(
                summary="The deduplicated context is sufficient.",
                feasibility=Feasibility.FEASIBLE,
            ),
        ],
    )

    await analyze_project(
        project,
        run_id=run.id,
    )

    additional_section = manager_inputs[1].split(
        "=== ADDITIONAL REQUESTED REPOSITORY CONTEXT ===",
        maxsplit=1,
    )[1].split(
        "=== UNSATISFIED REPOSITORY CONTEXT REQUESTS ===",
        maxsplit=1,
    )[0]
    assert additional_section.count(
        "--- FILE: src/example.py ---"
    ) == 1


@pytest.mark.parametrize(
    "file_path",
    [
        "../../secret",
        "/absolute/secret",
        "src/../secret",
    ],
)
def test_unsafe_context_request_path_is_rejected(
    file_path: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="safe repository-relative paths",
    ):
        normalize_context_request_path(file_path)


@pytest.mark.asyncio
async def test_unsafe_and_missing_requests_are_reported_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/example.py": "SAFE_CONTEXT\n",
        }
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=[
                    "../../secret",
                    "src/missing.py",
                    "src/example.py",
                ]
            ),
            make_manager_analysis(
                summary="The available context was assessed.",
                feasibility=Feasibility.FEASIBLE,
            ),
        ],
    )

    await analyze_project(
        project,
        run_id=run.id,
    )

    second_input = manager_inputs[1]
    assert "SAFE_CONTEXT" in second_input
    assert "../../secret" in second_input
    assert "must be safe repository-relative paths" in second_input
    assert "src/missing.py" in second_input
    assert "not present in project.files" in second_input


@pytest.mark.asyncio
async def test_two_context_expansion_rounds_accumulate_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/first.py": "FIRST_CONTEXT\n",
            "src/second.py": "SECOND_CONTEXT\n",
        }
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=["src/first.py"]
            ),
            make_manager_analysis(
                context_request_paths=["src/second.py"]
            ),
            make_manager_analysis(
                summary="Both files establish the solution.",
                feasibility=Feasibility.FEASIBLE,
            ),
        ],
    )

    analysis, usage = await analyze_project(
        project,
        run_id=run.id,
    )

    assert len(manager_inputs) == 3
    assert "FIRST_CONTEXT" in manager_inputs[1]
    assert "FIRST_CONTEXT" in manager_inputs[2]
    assert "SECOND_CONTEXT" in manager_inputs[2]
    assert analysis.feasibility == Feasibility.FEASIBLE
    assert usage == "usage-3"
    assert get_agent_invocation_count(
        run.id,
        "issue_analyzer",
    ) == 3


@pytest.mark.asyncio
async def test_third_context_request_does_not_expand_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/first.py": "FIRST_CONTEXT\n",
            "src/second.py": "SECOND_CONTEXT\n",
            "src/third.py": "THIRD_CONTEXT\n",
        }
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=["src/first.py"]
            ),
            make_manager_analysis(
                context_request_paths=["src/second.py"]
            ),
            make_manager_analysis(
                context_request_paths=["src/third.py"]
            ),
        ],
    )

    analysis, _usage = await analyze_project(
        project,
        run_id=run.id,
    )

    assert len(manager_inputs) == 3
    final_additional_context = manager_inputs[-1].split(
        "=== ADDITIONAL REQUESTED REPOSITORY CONTEXT ===",
        maxsplit=1,
    )[1].split(
        "=== UNSATISFIED REPOSITORY CONTEXT REQUESTS ===",
        maxsplit=1,
    )[0]
    assert "THIRD_CONTEXT" not in final_additional_context
    assert analysis.feasibility == Feasibility.NEEDS_CLARIFICATION
    assert analysis.context_request_paths == []
    assert "maximum of 2" in analysis.summary


@pytest.mark.asyncio
async def test_zero_new_context_does_not_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {"src/example.py": "VALUE = 1\n"}
    )
    run = create_run(project.project_name)
    manager_inputs = install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=["src/missing.py"]
            )
        ],
    )

    analysis, _usage = await analyze_project(
        project,
        run_id=run.id,
    )

    assert len(manager_inputs) == 1
    assert analysis.feasibility == Feasibility.NEEDS_CLARIFICATION
    assert analysis.context_request_paths == []
    assert "zero new usable repository files" in analysis.summary
    assert "src/missing.py" in analysis.summary


@pytest.mark.asyncio
async def test_intermediate_context_request_is_not_final_worker_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {
            "src/example.py": "VALUE = 1\n",
            "src/evidence.py": "EVIDENCE\n",
        }
    )
    run = create_run(project.project_name)
    intermediate_assignment = WorkerAssignment(
        order=1,
        worker_id="python_solver",
        task="Must not be returned before expansion.",
        files=["src/example.py"],
        depends_on=[],
    )
    install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                context_request_paths=["src/evidence.py"],
                worker_assignments=[intermediate_assignment],
            ),
            make_manager_analysis(
                summary="No changes needed: evidence resolved the issue.",
                feasibility=Feasibility.FEASIBLE,
            ),
        ],
    )

    analysis, _usage = await analyze_project(
        project,
        run_id=run.id,
    )

    assert analysis.worker_assignments == []
    assert analysis.context_request_paths == []


@pytest.mark.asyncio
async def test_final_analysis_still_validates_worker_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    project = make_context_project(
        {"src/example.py": "VALUE = 1\n"}
    )
    run = create_run(project.project_name)
    install_manager_outputs(
        monkeypatch,
        [
            make_manager_analysis(
                feasibility=Feasibility.FEASIBLE,
                worker_assignments=[
                    WorkerAssignment(
                        order=1,
                        worker_id="unavailable_worker",
                        task="Implement the fix.",
                        files=["src/example.py"],
                        depends_on=[],
                    )
                ],
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="unavailable workers",
    ):
        await analyze_project(
            project,
            run_id=run.id,
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
                    files=["src/backend.py"],
                    depends_on=[],
                )
            ],
            workers,
        )


def test_worker_assignment_requires_explicit_files() -> None:
    schema = WorkerAssignment.model_json_schema()

    assert "files" in schema["required"]

    with pytest.raises(
        ValueError,
        match="files",
    ):
        WorkerAssignment(
            order=1,
            worker_id="python_solver",
            task="Implement the fix.",
            depends_on=[],
        )


@pytest.mark.parametrize(
    "file_path",
    [
        "",
        ".",
        "/outside.py",
        "../outside.py",
        "src/../../outside.py",
    ],
)
def test_worker_assignment_rejects_unsafe_file_paths(
    file_path: str,
) -> None:
    with pytest.raises(ValueError):
        WorkerAssignment(
            order=1,
            worker_id="python_solver",
            task="Implement the fix.",
            files=[file_path],
            depends_on=[],
        )


def test_duplicate_file_ownership_is_rejected() -> None:
    workers = [
        {
            "id": "python_solver",
            "enabled": True,
        },
        {
            "id": "testing_specialist",
            "enabled": True,
        },
    ]
    assignments = [
        WorkerAssignment(
            order=1,
            worker_id="python_solver",
            task="Implement the behavior.",
            files=["src/example.py"],
            depends_on=[],
        ),
        WorkerAssignment(
            order=2,
            worker_id="testing_specialist",
            task="Add regression coverage.",
            files=["src/example.py"],
            depends_on=["python_solver"],
        ),
    ]

    with pytest.raises(
        ValueError,
        match=(
            "src/example.py.*python_solver.*"
            "testing_specialist"
        ),
    ):
        validate_worker_assignments(
            assignments,
            workers,
        )


def test_later_cycle_can_reassign_file_ownership() -> None:
    workers = [
        {
            "id": "python_solver",
            "enabled": True,
        },
        {
            "id": "testing_specialist",
            "enabled": True,
        },
    ]
    initial_cycle = [
        WorkerAssignment(
            order=1,
            worker_id="python_solver",
            task="Create the initial candidate file.",
            files=["tests/test_example.py"],
            depends_on=[],
        )
    ]
    remediation_cycle = [
        WorkerAssignment(
            order=1,
            worker_id="testing_specialist",
            task="Repair the candidate test.",
            files=["tests/test_example.py"],
            depends_on=[],
        )
    ]

    validate_worker_assignments(
        initial_cycle,
        workers,
    )
    validate_worker_assignments(
        remediation_cycle,
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

    # Stable prompt sections.
    assert (
        "=== TEST FAILURE REMEDIATION TASK ==="
        in agent_input
    )

    assert (
        "=== AVAILABLE WORKERS ==="
        in agent_input
    )

    assert (
        "=== CURRENT MANAGER ANALYSIS AND PLAN ==="
        in agent_input
    )

    assert (
        "=== CURRENT WORKER RESULTS ==="
        in agent_input
    )

    assert (
        "=== PROPOSED FILE OWNERSHIP ==="
        in agent_input
    )

    assert (
        "=== CURRENT COMBINED PROPOSED FILES ==="
        in agent_input
    )

    assert (
        "=== ACTUAL DOCKER TEST RESULT ==="
        in agent_input
    )

    assert (
        "=== REPOSITORY CONTEXT ==="
        in agent_input
    )

    # Actual deterministic execution evidence.
    assert (
        "1 failed, 9 passed"
        in agent_input
    )

    # Stable remediation categories.
    assert (
        "candidate_implementation_defect"
        in agent_input
    )

    assert (
        "test_or_fixture_defect"
        in agent_input
    )

    assert (
        "environment_or_configuration_defect"
        in agent_input
    )

    assert (
        "original_issue_failure"
        in agent_input
    )

    assert (
        "insufficient_evidence"
        in agent_input
    )

def test_proposed_file_ownership_comes_from_worker_results() -> None:
    implementation = FileReplacement(
        file_path="src/example.py",
        reason="Fix implementation.",
        replacement_content="VALUE = 2\n",
    )

    test_file = FileReplacement(
        file_path="tests/test_example.py",
        reason="Add regression coverage.",
        replacement_content=(
            "def test_example(): pass\n"
        ),
    )

    worker_results = {
        "python_solver": WorkerResult(
            summary="Implemented fix.",
            findings=[],
            files_to_replace=[
                implementation
            ],
        ),
        "testing_specialist": WorkerResult(
            summary="Added tests.",
            findings=[],
            files_to_replace=[
                test_file
            ],
        ),
    }

    ownership = (
        build_proposed_file_ownership_section(
            worker_results,
            [
                implementation,
                test_file,
            ],
        )
    )

    assert (
        "src/example.py → python_solver"
        in ownership
    )

    assert (
        "tests/test_example.py "
        "→ testing_specialist"
        in ownership
    )

def test_test_output_detects_referenced_candidate_file() -> None:
    proposed_file = FileReplacement(
        file_path=(
            ".github/workflows/tests.yml"
        ),
        reason="Update CI configuration.",
        replacement_content="jobs: {}\n",
    )

    test_result = RepositoryTestResult(
        passed=False,
        stage="tests",
        command=["pytest"],
        exit_code=1,
        duration_seconds=0.1,
        stdout=(
            "Configuration failure in "
            "tests.yml"
        ),
        stderr="",
    )

    referenced_paths = (
        find_test_referenced_proposed_paths(
            [proposed_file],
            test_result,
        )
    )

    assert referenced_paths == [
        ".github/workflows/tests.yml"
    ]
