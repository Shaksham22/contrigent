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
    determine_project_root,
    validate_repository_setup_proposal,
    verify_repository_environment,
)
from contrigent_api.services.repository_test_runner import (
    RepositoryTestStrategy,
    RepositoryTestNetworkMode,
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
        ecosystem="python",
        runtime_version="3.12",
        project_root=".",
        docker_image=(
            "ghcr.io/astral-sh/uv:"
            "python3.12-bookworm-slim"
        ),
        setup_commands=(
            ("uv", "sync", "--python", "3.12", "--group", "test"),
        ),
        background_commands=(),
        pre_test_commands=(),
        test_commands=(("pytest", "-q"),),
        environment_variables={},
        test_network_mode=RepositoryTestNetworkMode.NONE,
        services=(),
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
        ecosystem="python",
        runtime_version="3.12",
        project_root=".",
        dependency_setup_commands=[
            [
                "uv",
                "sync",
                "--group",
                "test",
            ]
        ],
        test_commands=[
            ["pytest", "-q"],
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
        lambda *_args, **_kwargs: strategy,
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


def test_manager_assignments_select_nearest_monorepo_manifest(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'root-tools'\n",
        encoding="utf-8",
    )
    subproject = tmp_path / "sdk" / "python"
    (subproject / "src").mkdir(parents=True)
    (subproject / "tests").mkdir()
    (subproject / "pyproject.toml").write_text(
        "[project]\nname = 'sdk'\n",
        encoding="utf-8",
    )
    analysis = SimpleNamespace(
        worker_assignments=[
            SimpleNamespace(
                files=[
                    "sdk/python/src/client.py",
                    "sdk/python/tests/test_client.py",
                ]
            )
        ]
    )

    assert determine_project_root(
        tmp_path,
        analysis,
    ) == "sdk/python"


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
        lambda *_args, **_kwargs: make_strategy(),
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
        lambda *_args, **_kwargs: make_strategy(),
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
        match="passing untouched repository baseline",
    ):
        await verify_repository_environment(
            project,
            run_id=run.id,
        )

    assert specialist_calls == 2
    assert execution_calls == 3


def test_setup_proposal_allows_repository_owned_scripts() -> None:
    proposal = RepositorySetupProposal(
        ecosystem="python",
        runtime_version="3.12",
        dependency_setup_commands=[
            ["bash", "scripts/setup.sh"],
        ],
        test_commands=[["make", "test"]],
        evidence=["CONTRIBUTING.md"],
    )

    strategy = validate_repository_setup_proposal(
        proposal
    )

    assert strategy.setup_commands == (
        ("bash", "scripts/setup.sh"),
    )
    assert strategy.test_commands == (("make", "test"),)


@pytest.mark.parametrize(
    "lock_command",
    [
        ["uv", "lock"],
        ["poetry", "lock"],
        ["uvx", "poetry", "lock"],
    ],
)
def test_setup_proposal_may_generate_lockfiles(
    lock_command: list[str],
) -> None:
    proposal = RepositorySetupProposal(
        ecosystem="python",
        runtime_version="3.12",
        dependency_setup_commands=[
            lock_command,
            ["uv", "sync"],
        ],
        test_commands=[["pytest"]],
        evidence=["pyproject.toml"],
    )

    strategy = validate_repository_setup_proposal(
        proposal
    )

    assert strategy.setup_commands[0] == tuple(lock_command)


def test_setup_proposal_allows_empty_setup_and_multiple_native_tests() -> None:
    proposal = RepositorySetupProposal(
        ecosystem="node",
        runtime_version="22",
        project_root="frontend",
        dependency_setup_commands=[],
        background_commands=[
            ["npm", "run", "dev:test"],
        ],
        pre_test_commands=[
            ["npm", "run", "migrate:test"],
        ],
        test_commands=[
            ["./scripts/test.sh"],
            ["make", "test"],
            ["npm", "run", "check"],
        ],
        environment_variables={"APP_ENV": "test"},
        evidence=["CONTRIBUTING.md"],
    )

    strategy = validate_repository_setup_proposal(
        proposal
    )

    assert strategy.setup_commands == ()
    assert strategy.background_commands == (
        ("npm", "run", "dev:test"),
    )
    assert strategy.pre_test_commands == (
        ("npm", "run", "migrate:test"),
    )
    assert strategy.test_commands == (
        ("./scripts/test.sh",),
        ("make", "test"),
        ("npm", "run", "check"),
    )


def test_setup_proposal_rejects_publication_credentials() -> None:
    proposal = RepositorySetupProposal(
        ecosystem="node",
        test_commands=[["npm", "test"]],
        environment_variables={
            "GITHUB_TOKEN": "must-not-enter-sandbox",
        },
        evidence=["package.json"],
    )

    with pytest.raises(
        RepositorySetupProposalError,
        match="credentials",
    ):
        validate_repository_setup_proposal(
            proposal
        )


@pytest.mark.asyncio
async def test_deterministic_test_failure_reaches_and_recovers_via_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("baseline-failure")
    failures_seen: list[str] = []
    results = iter(
        [
            RepositoryTestResult(
                passed=False,
                stage="tests",
                command=["pytest"],
                exit_code=1,
                duration_seconds=0.1,
                stdout="connection refused on local service",
                stderr="",
            ),
            make_result(passed=True),
        ]
    )

    monkeypatch.setattr(
        repository_environment_verifier,
        "get_repository_revision",
        lambda _path: "d" * 40,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "build_repository_test_strategy",
        lambda *_args, **_kwargs: make_strategy(),
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: next(results),
    )

    async def fake_propose(
        _project,
        previous_failure: str,
        *_args,
        **_kwargs,
    ) -> RepositorySetupProposal:
        failures_seen.append(previous_failure)
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

    assert len(failures_seen) == 1
    assert "connection refused on local service" in failures_seen[0]
    assert recipe.verification_source == (
        "repository_setup_specialist"
    )
    assert recipe.discovery_attempts == 1
    assert run.testing_rounds_completed == 0


@pytest.mark.asyncio
async def test_first_specialist_test_failure_allows_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("second-specialist-attempt")
    results = iter(
        [
            make_result(
                passed=False,
                stage="dependency_setup",
            ),
            RepositoryTestResult(
                passed=False,
                stage="tests",
                command=["pytest"],
                exit_code=1,
                duration_seconds=0.1,
                stdout="service was not ready",
                stderr="",
            ),
            make_result(passed=True),
        ]
    )
    failures_seen: list[str] = []

    monkeypatch.setattr(
        repository_environment_verifier,
        "get_repository_revision",
        lambda _path: "e" * 40,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "build_repository_test_strategy",
        lambda *_args, **_kwargs: make_strategy(),
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "execute_repository_test_strategy",
        lambda *_args, **_kwargs: next(results),
    )

    async def fake_propose(
        _project,
        previous_failure: str,
        *_args,
        **_kwargs,
    ) -> RepositorySetupProposal:
        failures_seen.append(previous_failure)
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

    assert len(failures_seen) == 2
    assert "service was not ready" in failures_seen[1]
    assert recipe.discovery_attempts == 2
    assert recipe.baseline_result.passed is True


@pytest.mark.asyncio
async def test_all_test_stage_discovery_failures_report_latest_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path)
    run = create_run("bounded-test-failures")
    results = iter(
        [
            RepositoryTestResult(
                passed=False,
                stage="tests",
                command=["pytest"],
                exit_code=1,
                duration_seconds=0.1,
                stdout="deterministic failure",
                stderr="",
            ),
            RepositoryTestResult(
                passed=False,
                stage="tests",
                command=["pytest"],
                exit_code=1,
                duration_seconds=0.1,
                stdout="first specialist failure",
                stderr="",
            ),
            RepositoryTestResult(
                passed=False,
                stage="tests",
                command=["pytest"],
                exit_code=1,
                duration_seconds=0.1,
                stdout="latest specialist failure",
                stderr="",
            ),
        ]
    )
    specialist_calls = 0

    monkeypatch.setattr(
        repository_environment_verifier,
        "get_repository_revision",
        lambda _path: "f" * 40,
    )
    monkeypatch.setattr(
        repository_environment_verifier,
        "build_repository_test_strategy",
        lambda *_args, **_kwargs: make_strategy(),
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

    with pytest.raises(
        RepositoryEnvironmentVerificationError,
        match="passing untouched repository baseline",
    ) as error_info:
        await verify_repository_environment(
            project,
            run_id=run.id,
        )

    assert specialist_calls == 2
    assert error_info.value.result is not None
    assert (
        error_info.value.result.stdout
        == "latest specialist failure"
    )


def test_setup_specialist_instructions_forbid_weakening_tests() -> None:
    instructions = repository_setup_specialist.instructions

    assert "deleting tests" in instructions
    assert "tiny unrelated subset" in instructions
    assert "suppress" in instructions
    assert "|| true" in instructions
    assert "disabling tests" in instructions
