from pathlib import Path
from types import SimpleNamespace

import pytest

from contrigent_api.agents.repository_setup_specialist.output_schema import (
    RepositorySetupProposal,
)
from contrigent_api.agents.repository_setup_specialist.agent import (
    repository_setup_specialist,
)
from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.services import (
    repository_environment_verifier,
)
from contrigent_api.services.repository_environment_verifier import (
    RepositoryEnvironmentVerificationError,
    RepositorySetupProposalError,
    validate_repository_setup_proposal,
    verify_repository_environment,
)
from contrigent_api.services.repository_test_runner import (
    RepositoryTestStrategy,
)
from contrigent_api.services.worker_discovery import (
    discover_workers,
)
from contrigent_api.services.run_memory_store import (
    clear_runs,
    create_run,
    get_agent_invocation_count,
)
from contrigent_api.services.agent_model_config import (
    get_agent_model_config,
)


@pytest.fixture(autouse=True)
def reset_runs() -> None:
    clear_runs()


def make_project(
    repository_path: Path,
) -> ProjectContext:
    return ProjectContext(
        project_name="example",
        project_source=ProjectSource.GITHUB,
        repository_path=repository_path,
        issue="Fix the reported behavior.",
        readme="Example project.",
        contributing="Run the test suite.",
        files={
            "pyproject.toml": (
                "[project]\n"
                'name = "example"\n'
            ),
            "tests/test_example.py": (
                "def test_example(): pass\n"
            ),
        },
    )


def make_strategy() -> RepositoryTestStrategy:
    return RepositoryTestStrategy(
        python_version="3.12",
        dependency_setup_commands=(
            "uv sync --python 3.12 --group test",
        ),
        test_command=(
            "/test-environment/workspace/.venv/"
            "bin/python -m pytest -q"
        ),
        evidence=("pyproject.toml",),
    )


def make_result(
    *,
    passed: bool,
    stage: str = "tests",
) -> RepositoryTestResult:
    return RepositoryTestResult(
        passed=passed,
        stage=stage,
        command=["pytest"],
        exit_code=0 if passed else 1,
        duration_seconds=0.1,
        stdout=(
            "2 passed"
            if passed
            else "dependency setup failed"
        ),
        stderr="",
    )


def make_proposal() -> RepositorySetupProposal:
    return RepositorySetupProposal(
        python_version="3.12",
        dependency_setup_commands=[
            [
                "uv",
                "sync",
                "--group",
                "test",
            ]
        ],
        test_command=[
            "pytest",
            "-q",
        ],
        evidence=[
            "pyproject.toml dependency group test",
        ],
    )


def test_setup_specialist_is_not_an_implementation_worker() -> None:
    worker_ids = {
        worker["id"]
        for worker in discover_workers()
    }

    assert "repository_setup_specialist" not in worker_ids
    assert (
        repository_setup_specialist.output_type
        is RepositorySetupProposal
    )


@pytest.mark.asyncio
async def test_setup_specialist_uses_generic_per_run_model_ladder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("setup-specialist-ladder")
    invoked_agents = []

    async def fake_runner_run(
        configured_agent,
        *_args,
        **_kwargs,
    ):
        invoked_agents.append(configured_agent)
        return SimpleNamespace(
            final_output=make_proposal()
        )

    monkeypatch.setattr(
        repository_environment_verifier.Runner,
        "run",
        fake_runner_run,
    )

    for attempt in (1, 2):
        await (
            repository_environment_verifier
            .propose_repository_setup(
                project,
                "Dependency setup failed.",
                attempt,
                run_id=run.id,
            )
        )

    expected_models = [
        get_agent_model_config(
            "repository_setup_specialist",
            invocation_number,
        ).model
        for invocation_number in (1, 2)
    ]

    assert [
        agent.model
        for agent in invoked_agents
    ] == expected_models
    assert get_agent_invocation_count(
        run.id,
        "repository_setup_specialist",
    ) == 2


@pytest.mark.asyncio
async def test_deterministic_success_skips_setup_specialist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("deterministic-success")
    strategy = make_strategy()
    specialist_calls = 0

    monkeypatch.setattr(
        repository_environment_verifier,
        "get_repository_revision",
        lambda _path: "a" * 40,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "build_repository_test_strategy",
        lambda *_args: strategy,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: make_result(
            passed=True
        ),
    )

    async def fake_propose(
        *_args,
        **_kwargs,
    ) -> RepositorySetupProposal:
        nonlocal specialist_calls
        specialist_calls += 1
        return make_proposal()

    monkeypatch.setattr(
        repository_environment_verifier,
        "propose_repository_setup",
        fake_propose,
    )

    recipe = await verify_repository_environment(
        project,
        run_id=run.id,
    )

    assert specialist_calls == 0
    assert recipe.strategy is strategy
    assert recipe.verification_source == "deterministic"
    assert recipe.discovery_attempts == 0
    assert get_agent_invocation_count(
        run.id,
        "repository_setup_specialist",
    ) == 0


@pytest.mark.asyncio
async def test_deterministic_dependency_failure_invokes_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("deterministic-failure")
    results = iter(
        [
            make_result(
                passed=False,
                stage="dependency_setup",
            ),
            make_result(passed=True),
        ]
    )
    specialist_calls = 0

    monkeypatch.setattr(
        repository_environment_verifier,
        "get_repository_revision",
        lambda _path: "b" * 40,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "build_repository_test_strategy",
        lambda *_args: make_strategy(),
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: next(results),
    )

    async def fake_propose(
        *_args,
        **_kwargs,
    ) -> RepositorySetupProposal:
        nonlocal specialist_calls
        specialist_calls += 1
        return make_proposal()

    monkeypatch.setattr(
        repository_environment_verifier,
        "propose_repository_setup",
        fake_propose,
    )

    recipe = await verify_repository_environment(
        project,
        run_id=run.id,
    )

    assert specialist_calls == 1
    assert recipe.verification_source == (
        "repository_setup_specialist"
    )
    assert recipe.discovery_attempts == 1


@pytest.mark.asyncio
async def test_setup_discovery_stops_after_two_proposals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("bounded-discovery")
    specialist_calls = 0
    execution_calls = 0

    monkeypatch.setattr(
        repository_environment_verifier,
        "get_repository_revision",
        lambda _path: "c" * 40,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "build_repository_test_strategy",
        lambda *_args: make_strategy(),
    )

    def fake_execute(
        *_args,
        **_kwargs,
    ) -> RepositoryTestResult:
        nonlocal execution_calls
        execution_calls += 1
        return make_result(
            passed=False,
            stage="dependency_setup",
        )

    monkeypatch.setattr(
        repository_environment_verifier,
        "execute_repository_test_strategy",
        fake_execute,
    )

    async def fake_propose(
        *_args,
        **_kwargs,
    ) -> RepositorySetupProposal:
        nonlocal specialist_calls
        specialist_calls += 1
        return make_proposal()

    monkeypatch.setattr(
        repository_environment_verifier,
        "propose_repository_setup",
        fake_propose,
    )

    with pytest.raises(
        RepositoryEnvironmentVerificationError,
        match="reliable repository test environment",
    ):
        await verify_repository_environment(
            project,
            run_id=run.id,
        )

    assert specialist_calls == 2
    assert execution_calls == 3


def test_setup_proposal_cannot_mutate_repository_files() -> None:
    proposal = RepositorySetupProposal(
        python_version="3.12",
        dependency_setup_commands=[
            [
                "python",
                "-c",
                (
                    "open('pyproject.toml', "
                    "'w').write('changed')"
                ),
            ]
        ],
        test_command=["pytest"],
        evidence=["pyproject.toml"],
    )

    with pytest.raises(
        RepositorySetupProposalError,
        match="not supported",
    ):
        validate_repository_setup_proposal(
            proposal
        )


@pytest.mark.parametrize(
    "lock_command",
    [
        ["uv", "lock"],
        ["poetry", "lock"],
        ["uvx", "poetry", "lock"],
    ],
)
def test_setup_proposal_cannot_generate_lockfiles(
    lock_command: list[str],
) -> None:
    proposal = RepositorySetupProposal(
        python_version="3.12",
        dependency_setup_commands=[
            lock_command,
            ["uv", "sync"],
        ],
        test_command=["pytest"],
        evidence=["pyproject.toml"],
    )

    with pytest.raises(
        RepositorySetupProposalError,
        match="Lock generation",
    ):
        validate_repository_setup_proposal(
            proposal
        )


@pytest.mark.asyncio
async def test_failing_baseline_does_not_invoke_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("baseline-failure")
    specialist_calls = 0

    monkeypatch.setattr(
        repository_environment_verifier,
        "get_repository_revision",
        lambda _path: "d" * 40,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "build_repository_test_strategy",
        lambda *_args: make_strategy(),
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: make_result(
            passed=False,
            stage="tests",
        ),
    )

    async def fake_propose(
        *_args,
        **_kwargs,
    ) -> RepositorySetupProposal:
        nonlocal specialist_calls
        specialist_calls += 1
        return make_proposal()

    monkeypatch.setattr(
        repository_environment_verifier,
        "propose_repository_setup",
        fake_propose,
    )

    with pytest.raises(
        RepositoryEnvironmentVerificationError,
        match="baseline tests failed",
    ):
        await verify_repository_environment(
            project,
            run_id=run.id,
        )

    assert specialist_calls == 0
