import pytest
from types import SimpleNamespace
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
    run_worker,
    validate_replacement_path,
)
from contrigent_api.services.run_memory_store import (
    clear_runs,
    create_run,
    get_agent_invocation_count,
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


def make_worker_analysis(
    assignments: list[WorkerAssignment],
) -> IssueAnalysis:
    return IssueAnalysis(
        summary="Implement the requested behavior.",
        acceptance_criteria=[
            "The requested behavior is covered."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=[
            file_path
            for assignment in assignments
            for file_path in assignment.files
        ],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        worker_assignments=assignments,
        implementation_plan=[
            ImplementationStep(
                order=1,
                description="Implement and verify the change.",
            )
        ],
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
        ["src/users.py"],
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

    assert "=== ASSIGNED FILE OWNERSHIP ===" in worker_input
    assert "- src/users.py" in worker_input
    assert "only return\nreplacements for the assigned files" in worker_input
    assert "do not transfer file ownership" in worker_input
    assert "report that need in\nyour findings" in worker_input


def test_testing_remediation_input_contains_current_candidate_and_manager_task(
) -> None:
    original_project = load_sample_project(
        "python-missing-display-name"
    )
    current_test = FileReplacement(
        file_path="tests/test_users.py",
        reason="Initial regression coverage.",
        replacement_content=(
            "CURRENT_FAILED_TEST = "
            "'candidate overlay'\n"
        ),
    )
    current_candidate = (
        build_project_with_proposed_files(
            original_project,
            [current_test],
        )
    )
    revised_task = (
        "Repair the invalid test double using the "
        "callable contract shown in src/users.py."
    )
    revised_analysis = IssueAnalysis(
        summary="Repair the candidate regression test.",
        acceptance_criteria=[
            "The regression test must exercise the real behavior."
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
                worker_id="testing_specialist",
                task=revised_task,
                files=["tests/test_users.py"],
                depends_on=[],
            )
        ],
        implementation_plan=[
            ImplementationStep(
                order=1,
                description=revised_task,
            )
        ],
    )
    test_result = RepositoryTestResult(
        passed=False,
        stage="tests",
        command=["pytest"],
        exit_code=1,
        duration_seconds=0.1,
        stdout="FAILED tests/test_users.py::test_fallback",
        stderr="TypeError: invalid synchronous test double",
    )

    worker_input = build_worker_input(
        "testing_specialist",
        revised_task,
        ["tests/test_users.py"],
        shared_worker_results={},
        sample_project=current_candidate,
        issue_analysis=revised_analysis,
        candidate_test_result=test_result,
    )

    assert revised_task in worker_input
    assert "CURRENT_FAILED_TEST" in worker_input
    assert "display_name.upper()" in worker_input
    assert test_result.stdout in worker_input
    assert test_result.stderr in worker_input


def test_testing_specialist_requires_callable_contract_aware_mocks(
) -> None:
    testing_agent = load_worker_agent(
        "testing_specialist"
    )
    instructions = testing_agent.instructions

    assert isinstance(instructions, str)
    assert "synchronous or asynchronous" in instructions
    assert "Use `AsyncMock` only" in instructions
    assert "current failing test" in instructions
    assert "exact traceback" in instructions
    assert "pinned dependency and API versions" in instructions
    assert "behavioral assertions" in instructions
    assert "smallest correction necessary" in instructions


@pytest.mark.asyncio
async def test_workers_use_per_run_model_ladders_on_actual_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()
    first_run = create_run("first")
    second_run = create_run("second")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    analysis = IssueAnalysis(
        summary="Exercise worker model selection.",
        acceptance_criteria=["Select the configured tier."],
        ambiguities=[],
        repository_instructions=[],
        likely_files=["tests/test_users.py"],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        worker_assignments=[],
        implementation_plan=[
            ImplementationStep(
                order=1,
                description="Run the assigned worker.",
            )
        ],
    )
    invoked_agents = []

    async def fake_runner_run(
        configured_agent,
        *_args,
        **_kwargs,
    ):
        invoked_agents.append(configured_agent)
        return SimpleNamespace(
            final_output=WorkerResult(
                summary="No file changes.",
                findings=[],
                files_to_replace=[],
            )
        )

    monkeypatch.setattr(
        (
            "contrigent_api.services."
            "worker_runner.Runner.run"
        ),
        fake_runner_run,
    )

    assert get_agent_invocation_count(
        first_run.id,
        "testing_specialist",
    ) == 0

    for _ in range(3):
        await run_worker(
            "testing_specialist",
            "Repair regression coverage.",
            ["tests/test_users.py"],
            {},
            sample_project,
            analysis,
            run_id=first_run.id,
        )

    for _ in range(2):
        await run_worker(
            "python_solver",
            "Implement the fix.",
            ["src/users.py"],
            {},
            sample_project,
            analysis,
            run_id=first_run.id,
        )

    await run_worker(
        "testing_specialist",
        "Repair regression coverage.",
        ["tests/test_users.py"],
        {},
        sample_project,
        analysis,
        run_id=second_run.id,
    )

    testing_agents = invoked_agents[:3]
    python_agents = invoked_agents[3:5]
    second_run_agent = invoked_agents[5]

    assert [
        agent.model
        for agent in testing_agents
    ] == [
        "gpt-5.4-mini",
        "gpt-5.6-sol",
        "gpt-5.6-sol",
    ]
    assert (
        testing_agents[1]
        .model_settings.reasoning.effort
        == "high"
    )
    assert (
        testing_agents[2]
        .model_settings.reasoning.effort
        == "high"
    )
    assert [
        agent.model
        for agent in python_agents
    ] == [
        "gpt-5.4-mini",
        "gpt-5.4-mini",
    ]
    assert second_run_agent.model == "gpt-5.4-mini"
    assert get_agent_invocation_count(
        first_run.id,
        "testing_specialist",
    ) == 3
    assert get_agent_invocation_count(
        first_run.id,
        "python_solver",
    ) == 2
    assert get_agent_invocation_count(
        second_run.id,
        "testing_specialist",
    ) == 1

@pytest.mark.asyncio
async def test_dependent_worker_receives_completed_worker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("worker-dependencies")
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
                files=["src/users.py"],
                depends_on=[],
            ),
            WorkerAssignment(
                order=2,
                worker_id="testing_specialist",
                task="Add regression coverage.",
                files=["tests/test_users.py"],
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
        assigned_files: list[str],
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
            run_id=run.id,
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


@pytest.mark.asyncio
async def test_worker_returning_only_assigned_files_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("assigned-files-success")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    analysis = make_worker_analysis([])
    replacement = FileReplacement(
        file_path="src/users.py",
        reason="Implement the requested behavior.",
        replacement_content="updated source\n",
    )

    async def fake_runner_run(*_args, **_kwargs):
        return SimpleNamespace(
            final_output=WorkerResult(
                summary="Implemented the change.",
                findings=[],
                files_to_replace=[replacement],
            )
        )

    monkeypatch.setattr(
        (
            "contrigent_api.services."
            "worker_runner.Runner.run"
        ),
        fake_runner_run,
    )

    result = await run_worker(
        "python_solver",
        "Implement the behavior.",
        ["src/users.py"],
        {},
        sample_project,
        analysis,
        run_id=run.id,
    )

    assert result.files_to_replace == [replacement]


@pytest.mark.asyncio
async def test_worker_returning_unassigned_file_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("unassigned-file")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    analysis = make_worker_analysis([])

    async def fake_runner_run(*_args, **_kwargs):
        return SimpleNamespace(
            final_output=WorkerResult(
                summary="Changed the wrong file.",
                findings=[],
                files_to_replace=[
                    FileReplacement(
                        file_path="tests/test_users.py",
                        reason="Out-of-scope replacement.",
                        replacement_content="updated tests\n",
                    )
                ],
            )
        )

    monkeypatch.setattr(
        (
            "contrigent_api.services."
            "worker_runner.Runner.run"
        ),
        fake_runner_run,
    )

    with pytest.raises(
        ValueError,
        match=(
            "python_solver.*tests/test_users.py.*"
            "src/users.py"
        ),
    ):
        await run_worker(
            "python_solver",
            "Implement the behavior.",
            ["src/users.py"],
            {},
            sample_project,
            analysis,
            run_id=run.id,
        )


@pytest.mark.asyncio
async def test_duplicate_ownership_fails_before_worker_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("duplicate-ownership")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    analysis = make_worker_analysis(
        [
            WorkerAssignment(
                order=1,
                worker_id="python_solver",
                task="Implement the behavior.",
                files=["src/users.py"],
                depends_on=[],
            ),
            WorkerAssignment(
                order=2,
                worker_id="testing_specialist",
                task="Verify the behavior.",
                files=["src/users.py"],
                depends_on=["python_solver"],
            ),
        ]
    )
    worker_calls = 0

    async def fake_run_worker(*_args, **_kwargs):
        nonlocal worker_calls
        worker_calls += 1
        return WorkerResult(
            summary="Must not run.",
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

    with pytest.raises(
        ValueError,
        match="multiple workers",
    ):
        await run_assigned_workers(
            sample_project,
            analysis,
            run_id=run.id,
        )

    assert worker_calls == 0


@pytest.mark.asyncio
async def test_different_file_owners_run_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("different-file-owners")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    assignments = [
        WorkerAssignment(
            order=1,
            worker_id="python_solver",
            task="Implement the behavior.",
            files=["src/users.py"],
            depends_on=[],
        ),
        WorkerAssignment(
            order=2,
            worker_id="testing_specialist",
            task="Add regression coverage.",
            files=["tests/test_users.py"],
            depends_on=["python_solver"],
        ),
    ]
    analysis = make_worker_analysis(assignments)

    async def fake_run_worker(
        worker_id: str,
        _assigned_task: str,
        assigned_files: list[str],
        _shared_results: dict[str, WorkerResult],
        *_args,
        **_kwargs,
    ) -> WorkerResult:
        return WorkerResult(
            summary=f"{worker_id} completed.",
            findings=[],
            files_to_replace=[
                FileReplacement(
                    file_path=assigned_files[0],
                    reason="Assigned replacement.",
                    replacement_content=(
                        f"{worker_id} replacement\n"
                    ),
                )
            ],
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
            run_id=run.id,
        )
    )

    assert set(worker_results) == {
        "python_solver",
        "testing_specialist",
    }
    assert {
        replacement.file_path
        for replacement in proposed_files
    } == {
        "src/users.py",
        "tests/test_users.py",
    }


@pytest.mark.asyncio
async def test_dependency_result_does_not_transfer_file_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("dependency-ownership")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    assignments = [
        WorkerAssignment(
            order=1,
            worker_id="python_solver",
            task="Implement the behavior.",
            files=["src/users.py"],
            depends_on=[],
        ),
        WorkerAssignment(
            order=2,
            worker_id="testing_specialist",
            task="Add regression coverage.",
            files=["tests/test_users.py"],
            depends_on=["python_solver"],
        ),
    ]
    analysis = make_worker_analysis(assignments)
    dependency_was_shared = False

    async def fake_run_worker(
        worker_id: str,
        _assigned_task: str,
        _assigned_files: list[str],
        shared_results: dict[str, WorkerResult],
        *_args,
        **_kwargs,
    ) -> WorkerResult:
        nonlocal dependency_was_shared

        if worker_id == "python_solver":
            return WorkerResult(
                summary="Implemented source change.",
                findings=[],
                files_to_replace=[
                    FileReplacement(
                        file_path="src/users.py",
                        reason="Source change.",
                        replacement_content="source change\n",
                    )
                ],
            )

        dependency_was_shared = (
            "python_solver" in shared_results
        )
        return WorkerResult(
            summary="Tried to edit dependency-owned source.",
            findings=[],
            files_to_replace=[
                FileReplacement(
                    file_path="src/users.py",
                    reason="Unassigned dependency file.",
                    replacement_content="different source change\n",
                )
            ],
        )

    monkeypatch.setattr(
        (
            "contrigent_api.services."
            "worker_runner.run_worker"
        ),
        fake_run_worker,
    )

    with pytest.raises(
        ValueError,
        match=(
            "testing_specialist.*src/users.py.*"
            "tests/test_users.py"
        ),
    ):
        await run_assigned_workers(
            sample_project,
            analysis,
            run_id=run.id,
        )

    assert dependency_was_shared is True


@pytest.mark.asyncio
async def test_conflicting_replacement_protection_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("conflicting-replacements")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    analysis = make_worker_analysis(
        [
            WorkerAssignment(
                order=1,
                worker_id="python_solver",
                task="Implement the behavior.",
                files=["src/users.py"],
                depends_on=[],
            )
        ]
    )

    async def fake_run_worker(*_args, **_kwargs):
        return WorkerResult(
            summary="Returned conflicting contents.",
            findings=[],
            files_to_replace=[
                FileReplacement(
                    file_path="src/users.py",
                    reason="First replacement.",
                    replacement_content="first\n",
                ),
                FileReplacement(
                    file_path="src/users.py",
                    reason="Second replacement.",
                    replacement_content="second\n",
                ),
            ],
        )

    monkeypatch.setattr(
        (
            "contrigent_api.services."
            "worker_runner.run_worker"
        ),
        fake_run_worker,
    )

    with pytest.raises(
        ValueError,
        match="conflicting replacements for: src/users.py",
    ):
        await run_assigned_workers(
            sample_project,
            analysis,
            run_id=run.id,
        )


@pytest.mark.asyncio
async def test_source_worker_cannot_add_unassigned_documentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = create_run("unassigned-documentation")
    sample_project = load_sample_project(
        "python-missing-display-name"
    )
    analysis = make_worker_analysis([])

    async def fake_runner_run(*_args, **_kwargs):
        return SimpleNamespace(
            final_output=WorkerResult(
                summary="Expanded beyond assigned source.",
                findings=[],
                files_to_replace=[
                    FileReplacement(
                        file_path="README.md",
                        reason="Unassigned documentation.",
                        replacement_content="Documentation change.\n",
                    )
                ],
            )
        )

    monkeypatch.setattr(
        (
            "contrigent_api.services."
            "worker_runner.Runner.run"
        ),
        fake_runner_run,
    )

    with pytest.raises(
        ValueError,
        match=(
            "python_solver.*README.md.*src/users.py"
        ),
    ):
        await run_worker(
            "python_solver",
            "Implement the source behavior.",
            ["src/users.py"],
            {},
            sample_project,
            analysis,
            run_id=run.id,
        )
