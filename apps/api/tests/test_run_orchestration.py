from pathlib import Path
from types import SimpleNamespace

import pytest

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    ImplementationStep,
    IssueAnalysis,
    WorkerAssignment,
)
from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.models.run_record import (
    RunStatus,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.routes import (
    run_routes,
)
from contrigent_api.services.run_memory_store import (
    approve_plan,
    attach_analysis,
    clear_runs,
    complete_review,
    complete_worker_work,
    create_run,
    get_verified_repository_test_recipe as get_stored_recipe,
    record_candidate_test_result,
    start_review,
    start_worker_work,
)
from contrigent_api.services.repository_environment_verifier import (
    RepositoryEnvironmentVerificationError,
    VerifiedRepositoryTestRecipe,
)
from contrigent_api.services.repository_test_runner import (
    RepositoryTestStrategy,
)


def make_verified_recipe() -> VerifiedRepositoryTestRecipe:
    return VerifiedRepositoryTestRecipe(
        strategy=RepositoryTestStrategy(
            python_version="3.12",
            dependency_setup_commands=(
                "uv sync --group test",
            ),
            test_command="pytest",
            evidence=("pyproject.toml",),
        ),
        baseline_result=RepositoryTestResult(
            passed=True,
            stage="tests",
            command=["pytest"],
            exit_code=0,
            duration_seconds=0.1,
            stdout="2 passed",
            stderr="",
        ),
        repository_revision="a" * 40,
        verification_source="deterministic",
        setup_verified=True,
        discovery_attempts=0,
    )


@pytest.fixture(autouse=True)
def reset_run_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_runs()

    recipe = make_verified_recipe()

    monkeypatch.setattr(
        run_routes,
        "get_verified_repository_test_recipe",
        lambda _run_id: recipe,
    )
    monkeypatch.setattr(
        run_routes,
        "verify_repository_revision",
        lambda *_args: None,
    )


def make_analysis(
    summary: str,
) -> IssueAnalysis:
    return IssueAnalysis(
        summary=summary,
        acceptance_criteria=[
            "Fix the reported behavior."
        ],
        ambiguities=[],
        repository_instructions=[],
        likely_files=[
            "src/example.py",
            "tests/test_example.py",
        ],
        risks=[],
        feasibility=Feasibility.FEASIBLE,
        worker_assignments=[],
        implementation_plan=[
            ImplementationStep(
                order=1,
                description=summary,
            )
        ],
    )


def make_project(
    repository_path: Path,
) -> ProjectContext:
    return ProjectContext(
        project_name="example",
        project_source=(
            ProjectSource.GITHUB
        ),
        repository_path=repository_path,
        issue="Fix issue #1.",
        readme="Example repository.",
        contributing="Run tests.",
        files={
            "src/example.py": (
                "VALUE = 1\n"
            ),
            "tests/test_example.py": (
                "def test_value(): pass\n"
            ),
        },
    )


def make_test_result(
    passed: bool,
) -> RepositoryTestResult:
    return RepositoryTestResult(
        passed=passed,
        stage="tests",
        command=[
            "pytest"
        ],
        exit_code=(
            0 if passed else 1
        ),
        duration_seconds=0.1,
        stdout=(
            "2 passed"
            if passed
            else "1 failed, 1 passed"
        ),
        stderr="",
    )


def make_dependency_setup_failure() -> RepositoryTestResult:
    return RepositoryTestResult(
        passed=False,
        stage="dependency_setup",
        command=[
            "uv",
            "sync",
        ],
        exit_code=1,
        duration_seconds=0.1,
        stdout="",
        stderr="Dependency setup failed.",
    )


def make_worker_result(
    summary: str,
) -> tuple[
    dict[str, WorkerResult],
    list[FileReplacement],
]:
    replacement = FileReplacement(
        file_path="src/example.py",
        reason=summary,
        replacement_content=(
            f"# {summary}\n"
            "VALUE = 2\n"
        ),
    )

    return (
        {
            "python_solver": WorkerResult(
                summary=summary,
                findings=[],
                files_to_replace=[
                    replacement
                ],
            )
        },
        [
            replacement
        ],
    )


@pytest.mark.asyncio
async def test_repository_preflight_completes_before_manager_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    recipe = make_verified_recipe()
    call_order: list[str] = []

    monkeypatch.setattr(
        run_routes,
        "get_or_download_github_project",
        lambda *_args: SimpleNamespace(
            project_name="example"
        ),
    )
    monkeypatch.setattr(
        run_routes,
        "load_downloaded_github_project",
        lambda *_args: project,
    )
    monkeypatch.setattr(
        run_routes,
        "create_run_branch",
        lambda *_args, **_kwargs: (
            "main",
            "contrigent/test-run",
        ),
    )

    async def fake_verify_environment(
        *_args,
        **_kwargs,
    ) -> VerifiedRepositoryTestRecipe:
        call_order.append("preflight")
        return recipe

    async def fake_analyze_project(
        *_args,
        **_kwargs,
    ):
        call_order.append("manager")
        return make_analysis("Verified plan."), None

    monkeypatch.setattr(
        run_routes,
        "verify_repository_environment",
        fake_verify_environment,
    )
    monkeypatch.setattr(
        run_routes,
        "analyze_project",
        fake_analyze_project,
    )

    result = await run_routes.start_run(
        run_routes.CreateRunRequest(
            github_issue_url=(
                "https://github.com/example/demo/issues/1"
            ),
            github_repository_url=(
                "https://github.com/example/demo"
            ),
        )
    )

    assert call_order == ["preflight", "manager"]
    assert get_stored_recipe(result.id) is recipe


@pytest.mark.asyncio
async def test_baseline_failure_stops_before_manager_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    manager_calls = 0
    rollback_calls = 0

    monkeypatch.setattr(
        run_routes,
        "get_or_download_github_project",
        lambda *_args: SimpleNamespace(
            project_name="example"
        ),
    )
    monkeypatch.setattr(
        run_routes,
        "load_downloaded_github_project",
        lambda *_args: project,
    )
    monkeypatch.setattr(
        run_routes,
        "create_run_branch",
        lambda *_args, **_kwargs: (
            "main",
            "contrigent/test-run",
        ),
    )

    async def fake_verify_environment(
        *_args,
        **_kwargs,
    ) -> VerifiedRepositoryTestRecipe:
        raise RepositoryEnvironmentVerificationError(
            "Untouched repository baseline tests failed.",
            make_test_result(False),
        )

    async def fake_analyze_project(
        *_args,
        **_kwargs,
    ):
        nonlocal manager_calls
        manager_calls += 1
        return make_analysis("Must not run."), None

    def fake_rollback(*_args, **_kwargs) -> None:
        nonlocal rollback_calls
        rollback_calls += 1

    monkeypatch.setattr(
        run_routes,
        "verify_repository_environment",
        fake_verify_environment,
    )
    monkeypatch.setattr(
        run_routes,
        "analyze_project",
        fake_analyze_project,
    )
    monkeypatch.setattr(
        run_routes,
        "rollback_run_branch",
        fake_rollback,
    )

    with pytest.raises(
        RepositoryEnvironmentVerificationError,
        match="baseline tests failed",
    ):
        await run_routes.start_run(
            run_routes.CreateRunRequest(
                github_issue_url=(
                    "https://github.com/example/demo/issues/1"
                ),
                github_repository_url=(
                    "https://github.com/example/demo"
                ),
            )
        )

    assert manager_calls == 0
    assert rollback_calls == 1


@pytest.mark.asyncio
async def test_failed_candidate_tests_return_to_manager_and_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(
        tmp_path
    )

    initial_analysis = make_analysis(
        "Initial plan."
    )
    revised_analysis = make_analysis(
        "Fix the Docker failure."
    )

    revised_analysis.worker_assignments = [
        WorkerAssignment(
            order=1,
            worker_id="python_solver",
            task=(
                "Correct the candidate based "
                "on the Docker failure."
            ),
            files=["src/example.py"],
            depends_on=[],
        )
    ]

    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
        max_review_rounds=1,
        max_testing_rounds=2,
    )

    attach_analysis(
        run.id,
        initial_analysis,
    )

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )

    worker_calls = 0

    async def fake_run_assigned_workers(
        *_args,
        **_kwargs,
    ):
        nonlocal worker_calls
        worker_calls += 1

        return make_worker_result(
            f"worker attempt {worker_calls}"
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )

    test_results = iter(
        [
            make_test_result(
                False
            ),
            make_test_result(
                True
            ),
        ]
    )

    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: next(
            test_results
        ),
    )

    test_replans = 0

    async def fake_replan_after_test_failure(
        *_args,
        **_kwargs,
    ):
        nonlocal test_replans
        test_replans += 1

        return (
            revised_analysis,
            None,
        )

    monkeypatch.setattr(
        run_routes,
        "replan_after_test_failure",
        fake_replan_after_test_failure,
    )

    reviewer_calls = 0

    async def fake_run_reviewer(
        *_args,
        **_kwargs,
    ) -> ReviewerResult:
        nonlocal reviewer_calls
        reviewer_calls += 1

        return ReviewerResult(
            recommendation="approve",
            summary="Approved.",
            findings=[],
            files_reviewed=[
                "src/example.py"
            ],
        )

    monkeypatch.setattr(
        run_routes,
        "run_reviewer",
        fake_run_reviewer,
    )

    progress_events = []

    result = (
        await run_routes.run_approved_plan(
            run.id,
            progress_callback=(
                progress_events.append
            ),
        )
    )
    progress_kinds = [
        event.kind
        for event
        in progress_events
    ]

    assert (
        "testing_started"
        in progress_kinds
    )

    assert (
        "testing_failed"
        in progress_kinds
    )

    assert (
        "manager_revision_started"
        in progress_kinds
    )

    assert (
        "manager_revision_completed"
        in progress_kinds
    )

    assert (
        "testing_passed"
        in progress_kinds
    )

    assert (
        "review_approved"
        in progress_kinds
    )

    assert (
        result.status
        == RunStatus.AWAITING_FINAL_APPROVAL
    )

    assert (
        result.testing_rounds_completed
        == 2
    )

    assert (
        result.review_rounds_completed
        == 1
    )

    assert (
        result.candidate_test_result
        is not None
    )

    assert (
        result.candidate_test_result.passed
        is True
    )

    assert worker_calls == 2
    assert test_replans == 1
    assert reviewer_calls == 1


@pytest.mark.asyncio
async def test_testing_remediation_receives_current_candidate_failure_and_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    initial_analysis = make_analysis(
        "Add regression coverage."
    )
    revised_task = (
        "Repair the invalid test using the exact "
        "candidate traceback and callable contract."
    )
    revised_analysis = make_analysis(
        "Repair the invalid regression test."
    )
    revised_analysis.worker_assignments = [
        WorkerAssignment(
            order=1,
            worker_id="testing_specialist",
            task=revised_task,
            files=["tests/test_example.py"],
            depends_on=[],
        )
    ]
    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
        max_review_rounds=1,
        max_testing_rounds=2,
    )
    attach_analysis(run.id, initial_analysis)
    current_test_content = (
        "def test_behavior():\n"
        "    raise TypeError('invalid test double')\n"
    )
    corrected_test_content = (
        "def test_behavior():\n"
        "    assert True\n"
    )
    latest_failure = RepositoryTestResult(
        passed=False,
        stage="tests",
        command=["pytest"],
        exit_code=1,
        duration_seconds=0.1,
        stdout=(
            "FAILED tests/test_example.py::test_behavior"
        ),
        stderr=(
            "TypeError: invalid synchronous test double"
        ),
    )
    worker_calls = 0
    remediation_handoff: dict[str, object] = {}

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )

    async def fake_run_assigned_workers(
        candidate_project: ProjectContext,
        analysis: IssueAnalysis,
        candidate_test_result: (
            RepositoryTestResult | None
        ) = None,
        **_kwargs,
    ):
        nonlocal worker_calls
        worker_calls += 1

        if worker_calls == 1:
            replacement = FileReplacement(
                file_path="tests/test_example.py",
                reason="Initial regression test.",
                replacement_content=current_test_content,
            )
        else:
            remediation_handoff.update(
                {
                    "project": candidate_project,
                    "analysis": analysis,
                    "test_result": candidate_test_result,
                }
            )
            replacement = FileReplacement(
                file_path="tests/test_example.py",
                reason="Repair invalid test double.",
                replacement_content=corrected_test_content,
            )

        return (
            {
                "testing_specialist": WorkerResult(
                    summary="Updated regression coverage.",
                    findings=[],
                    files_to_replace=[replacement],
                )
            },
            [replacement],
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )
    test_results = iter(
        [
            latest_failure,
            make_test_result(True),
        ]
    )
    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: next(test_results),
    )

    async def fake_replan_after_test_failure(
        *_args,
        **_kwargs,
    ):
        return revised_analysis, None

    monkeypatch.setattr(
        run_routes,
        "replan_after_test_failure",
        fake_replan_after_test_failure,
    )

    async def fake_run_reviewer(
        *_args,
        **_kwargs,
    ) -> ReviewerResult:
        return ReviewerResult(
            recommendation="approve",
            summary="Approved.",
            findings=[],
            files_reviewed=["tests/test_example.py"],
        )

    monkeypatch.setattr(
        run_routes,
        "run_reviewer",
        fake_run_reviewer,
    )

    result = await run_routes.run_approved_plan(
        run.id
    )

    remediation_project = remediation_handoff["project"]
    remediation_analysis = remediation_handoff["analysis"]

    assert isinstance(remediation_project, ProjectContext)
    assert isinstance(remediation_analysis, IssueAnalysis)
    assert (
        remediation_project.files["tests/test_example.py"]
        == current_test_content
    )
    assert remediation_handoff["test_result"] is latest_failure
    assert (
        remediation_analysis.worker_assignments[0].task
        == revised_task
    )
    assert result.status == RunStatus.AWAITING_FINAL_APPROVAL


@pytest.mark.asyncio
async def test_dependency_setup_failure_does_not_consume_test_round_or_replan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(
        tmp_path
    )
    analysis = make_analysis(
        "Initial plan."
    )

    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
        max_review_rounds=1,
        max_testing_rounds=2,
    )

    attach_analysis(
        run.id,
        analysis,
    )

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )

    worker_calls = 0

    async def fake_run_assigned_workers(
        *_args,
        **_kwargs,
    ):
        nonlocal worker_calls
        worker_calls += 1
        return make_worker_result(
            "initial candidate"
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )

    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: (
            make_dependency_setup_failure()
        ),
    )

    replan_calls = 0

    async def fake_replan_after_test_failure(
        *_args,
        **_kwargs,
    ):
        nonlocal replan_calls
        replan_calls += 1
        return analysis, None

    monkeypatch.setattr(
        run_routes,
        "replan_after_test_failure",
        fake_replan_after_test_failure,
    )

    progress_events = []

    result = (
        await run_routes.run_approved_plan(
            run.id,
            progress_callback=(
                progress_events.append
            ),
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.testing_rounds_completed == 0
    assert result.candidate_test_result is not None
    assert (
        result.candidate_test_result.stage
        == "dependency_setup"
    )
    assert worker_calls == 1
    assert replan_calls == 0

    progress_messages = [
        event.message
        for event in progress_events
    ]

    assert (
        "Repository dependency setup failed "
        "before candidate tests"
        in progress_messages
    )
    assert (
        "Candidate tests were not run"
        in progress_messages
    )


@pytest.mark.asyncio
async def test_failed_candidate_without_remediation_is_not_retested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(
        tmp_path
    )

    initial_analysis = make_analysis(
        "Initial plan."
    )

    unresolved_analysis = IssueAnalysis(
        summary=(
            "Solution not found: "
            "no supported remediation."
        ),
        acceptance_criteria=[
            "Fix the reported behavior."
        ],
        ambiguities=[
            "No supported correction identified."
        ],
        repository_instructions=[],
        likely_files=[
            "src/example.py",
            "tests/test_example.py",
        ],
        risks=[],
        feasibility=(
            Feasibility.NEEDS_CLARIFICATION
        ),
        worker_assignments=[],
        implementation_plan=[],
    )

    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/"
            "example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/"
            "example/demo"
        ),
        max_review_rounds=1,
        max_testing_rounds=2,
    )

    attach_analysis(
        run.id,
        initial_analysis,
    )

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )

    worker_calls = 0

    async def fake_run_assigned_workers(
        *_args,
        **_kwargs,
    ):
        nonlocal worker_calls
        worker_calls += 1

        return make_worker_result(
            "initial candidate"
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )

    test_calls = 0

    def fake_execute_repository_test_strategy(
        *_args,
        **_kwargs,
    ) -> RepositoryTestResult:
        nonlocal test_calls
        test_calls += 1

        return make_test_result(
            False
        )

    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        fake_execute_repository_test_strategy,
    )

    async def fake_replan_after_test_failure(
        *_args,
        **_kwargs,
    ):
        return (
            unresolved_analysis,
            None,
        )

    monkeypatch.setattr(
        run_routes,
        "replan_after_test_failure",
        fake_replan_after_test_failure,
    )

    progress_events = []

    result = (
        await run_routes.run_approved_plan(
            run.id,
            progress_callback=(
                progress_events.append
            ),
        )
    )

    assert (
        result.status
        == RunStatus.FAILED
    )

    assert test_calls == 1

    assert worker_calls == 1

    assert (
        result.testing_rounds_completed
        == 1
    )

    assert (
        result.candidate_test_result
        is not None
    )

    assert (
        result.candidate_test_result.passed
        is False
    )

    progress_messages = [
        event.message
        for event
        in progress_events
    ]

    assert (
        "No supported test remediation was found"
        in progress_messages
    )

@pytest.mark.asyncio
async def test_reviewer_rejection_replans_retests_and_reviews_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(
        tmp_path
    )

    initial_analysis = make_analysis(
        "Initial plan."
    )

    revised_analysis = make_analysis(
        "Address reviewer feedback."
    )

    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
        max_review_rounds=2,
        max_testing_rounds=2,
    )

    attach_analysis(
        run.id,
        initial_analysis,
    )

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )

    worker_calls = 0

    async def fake_run_assigned_workers(
        *_args,
        **_kwargs,
    ):
        nonlocal worker_calls
        worker_calls += 1

        return make_worker_result(
            f"worker attempt {worker_calls}"
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )

    test_calls = 0

    def fake_execute_repository_test_strategy(
        *_args,
        **_kwargs,
    ) -> RepositoryTestResult:
        nonlocal test_calls
        test_calls += 1

        return make_test_result(
            True
        )

    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        fake_execute_repository_test_strategy,
    )

    review_results = iter(
        [
            ReviewerResult(
                recommendation=(
                    "changes_required"
                ),
                summary=(
                    "Revise the implementation."
                ),
                findings=[],
                files_reviewed=[
                    "src/example.py"
                ],
            ),
            ReviewerResult(
                recommendation="approve",
                summary=(
                    "Approved after revision."
                ),
                findings=[],
                files_reviewed=[
                    "src/example.py"
                ],
            ),
        ]
    )

    reviewer_calls = 0

    async def fake_run_reviewer(
        *_args,
        **_kwargs,
    ) -> ReviewerResult:
        nonlocal reviewer_calls
        reviewer_calls += 1

        return next(
            review_results
        )

    monkeypatch.setattr(
        run_routes,
        "run_reviewer",
        fake_run_reviewer,
    )

    review_replans = 0

    async def fake_replan_after_review(
        *_args,
        **_kwargs,
    ):
        nonlocal review_replans
        review_replans += 1

        return (
            revised_analysis,
            None,
        )

    monkeypatch.setattr(
        run_routes,
        "replan_after_review",
        fake_replan_after_review,
    )

    result = (
        await run_routes.approve_run_plan(
            run.id
        )
    )

    assert (
        result.status
        == RunStatus.AWAITING_FINAL_APPROVAL
    )

    assert (
        result.testing_rounds_completed
        == 2
    )

    assert (
        result.review_rounds_completed
        == 2
    )

    assert (
        result.reviewer_result
        is not None
    )

    assert (
        result.reviewer_result.recommendation
        == "approve"
    )

    assert worker_calls == 2
    assert test_calls == 2
    assert reviewer_calls == 2
    assert review_replans == 1


@pytest.mark.asyncio
async def test_review_limit_stops_automatic_rework(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(
        tmp_path
    )

    analysis = make_analysis(
        "Initial plan."
    )

    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
        max_review_rounds=1,
        max_testing_rounds=2,
    )

    attach_analysis(
        run.id,
        analysis,
    )

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )

    async def fake_run_assigned_workers(
        *_args,
        **_kwargs,
    ):
        return make_worker_result(
            "initial candidate"
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )

    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: (
            make_test_result(
                True
            )
        ),
    )

    async def fake_run_reviewer(
        *_args,
        **_kwargs,
    ) -> ReviewerResult:
        return ReviewerResult(
            recommendation=(
                "changes_required"
            ),
            summary=(
                "Still needs work."
            ),
            findings=[],
            files_reviewed=[
                "src/example.py"
            ],
        )

    monkeypatch.setattr(
        run_routes,
        "run_reviewer",
        fake_run_reviewer,
    )

    result = (
        await run_routes.approve_run_plan(
            run.id
        )
    )

    assert (
        result.status
        == RunStatus.AWAITING_FINAL_APPROVAL
    )

    assert (
        result.review_rounds_completed
        == 1
    )

    assert (
        result.reviewer_result
        is not None
    )

    assert (
        result.reviewer_result.recommendation
        == "changes_required"
    )


@pytest.mark.asyncio
async def test_testing_limit_stops_before_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(
        tmp_path
    )

    analysis = make_analysis(
        "Initial plan."
    )

    run = create_run(
        "example",
        ProjectSource.GITHUB,
        github_issue_url=(
            "https://github.com/example/demo/issues/1"
        ),
        github_repository_url=(
            "https://github.com/example/demo"
        ),
        max_review_rounds=2,
        max_testing_rounds=1,
    )

    attach_analysis(
        run.id,
        analysis,
    )

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )

    async def fake_run_assigned_workers(
        *_args,
        **_kwargs,
    ):
        return make_worker_result(
            "initial candidate"
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )

    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: (
            make_test_result(
                False
            )
        ),
    )

    result = (
        await run_routes.approve_run_plan(
            run.id
        )
    )

    assert (
        result.status
        == RunStatus.FAILED
    )

    assert (
        result.testing_rounds_completed
        == 1
    )

    assert (
        result.candidate_test_result
        is not None
    )

    assert (
        result.candidate_test_result.passed
        is False
    )

    assert (
        result.review_rounds_completed
        == 0
    )


@pytest.mark.asyncio
async def test_candidate_testing_replays_stored_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    recipe = make_verified_recipe()
    analysis = make_analysis("Implement the fix.")
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
    attach_analysis(run.id, analysis)
    replayed_strategies: list[
        RepositoryTestStrategy
    ] = []

    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )
    monkeypatch.setattr(
        run_routes,
        "get_verified_repository_test_recipe",
        lambda _run_id: recipe,
    )

    async def fake_run_assigned_workers(
        *_args,
        **_kwargs,
    ):
        return make_worker_result("candidate")

    def fake_execute(
        _repository_path: Path,
        strategy: RepositoryTestStrategy,
        **_kwargs,
    ) -> RepositoryTestResult:
        replayed_strategies.append(strategy)
        return make_test_result(True)

    async def fake_run_reviewer(
        *_args,
        **_kwargs,
    ) -> ReviewerResult:
        return ReviewerResult(
            recommendation="approve",
            summary="Approved.",
            findings=[],
            files_reviewed=["src/example.py"],
        )

    monkeypatch.setattr(
        run_routes,
        "run_assigned_workers",
        fake_run_assigned_workers,
    )
    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        fake_execute,
    )
    monkeypatch.setattr(
        run_routes,
        "run_reviewer",
        fake_run_reviewer,
    )

    result = await run_routes.run_approved_plan(
        run.id
    )

    assert result.status == RunStatus.AWAITING_FINAL_APPROVAL
    assert replayed_strategies == [recipe.strategy]


def test_final_testing_replays_stored_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    recipe = make_verified_recipe()
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
    run.original_branch = "main"
    run.run_branch = "contrigent/test-run"
    attach_analysis(run.id, make_analysis("Implement the fix."))
    approve_plan(run.id)
    start_worker_work(run.id)
    complete_worker_work(
        run.id,
        *make_worker_result("candidate"),
    )
    record_candidate_test_result(
        run.id,
        make_test_result(True),
    )
    start_review(run.id)
    complete_review(
        run.id,
        ReviewerResult(
            recommendation="approve",
            summary="Approved.",
            findings=[],
            files_reviewed=["src/example.py"],
        ),
    )
    replayed_strategies: list[
        RepositoryTestStrategy
    ] = []

    monkeypatch.setattr(
        run_routes,
        "get_github_token",
        lambda: "token",
    )
    monkeypatch.setattr(
        run_routes,
        "load_project",
        lambda *_args: project,
    )
    monkeypatch.setattr(
        run_routes,
        "get_verified_repository_test_recipe",
        lambda _run_id: recipe,
    )
    monkeypatch.setattr(
        run_routes,
        "ensure_expected_run_branch",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        run_routes,
        "apply_approved_files",
        lambda *_args: [],
    )

    def fake_execute(
        _repository_path: Path,
        strategy: RepositoryTestStrategy,
        **_kwargs,
    ) -> RepositoryTestResult:
        replayed_strategies.append(strategy)
        return make_test_result(False)

    monkeypatch.setattr(
        run_routes,
        "execute_repository_test_strategy",
        fake_execute,
    )

    result = run_routes.approve_run_final_changes(
        run.id
    )

    assert result.status == RunStatus.TESTS_FAILED
    assert replayed_strategies == [recipe.strategy]
