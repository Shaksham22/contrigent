from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import shlex
from typing import Literal
from uuid import UUID

from agents import Runner

from contrigent_api.agents.repository_setup_specialist.agent import (
    AGENT_ID as REPOSITORY_SETUP_SPECIALIST_AGENT_ID,
    repository_setup_specialist,
)
from contrigent_api.agents.repository_setup_specialist.output_schema import (
    RepositorySetupProposal,
)
from contrigent_api.models.project_context import (
    ProjectContext,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.services.repository_context_builder import (
    build_repository_context,
)
from contrigent_api.services.agent_model_config import (
    configure_agent_for_run_invocation,
)
from contrigent_api.services.repository_git_manager import (
    run_git_command,
)
from contrigent_api.services.repository_test_runner import (
    DOCKER_IMAGE,
    RepositoryCommandSelection,
    RepositoryTestRunnerError,
    RepositoryTestStrategy,
    build_persistent_test_command,
    build_repository_owned_native_commands,
    build_repository_test_strategy,
    execute_repository_test_strategy,
    get_test_runner,
    materialize_evidenced_setup_commands,
    normalize_supported_setup_command,
    normalize_supported_test_command,
    setup_command_installs_dependencies,
)
from contrigent_api.services.run_progress import (
    RunProgressCallback,
    build_test_failure_details,
    report_run_progress,
)


MAX_SETUP_DISCOVERY_ATTEMPTS = 2
PYTHON_VERSION_PATTERN = re.compile(
    r"^3\.\d+$"
)
UNSAFE_TOKEN_FRAGMENTS = (
    "&&",
    "||",
    ";",
    "|",
    ">",
    "<",
    "`",
    "$",
    "\n",
    "\r",
)
LOCK_GENERATION_PREFIXES = (
    ("uv", "lock"),
    ("poetry", "lock"),
    ("uvx", "poetry", "lock"),
)
UNSAFE_INSTALL_OPTIONS = {
    "--cache-dir",
    "--config-settings",
    "--prefix",
    "--root",
    "--target",
}
SETUP_EVIDENCE_PATHS = (
    ".python-version",
    "CONTRIBUTING.md",
    "noxfile.py",
    "poetry.lock",
    "pyproject.toml",
    "pytest.ini",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements-testing.txt",
    "requirements.txt",
    "tox.ini",
    "uv.lock",
)


class RepositoryEnvironmentVerificationError(
    RuntimeError
):
    def __init__(
        self,
        message: str,
        result: RepositoryTestResult | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result


class RepositorySetupProposalError(
    ValueError
):
    pass


@dataclass(frozen=True)
class VerifiedRepositoryTestRecipe:
    strategy: RepositoryTestStrategy
    baseline_result: RepositoryTestResult
    repository_revision: str
    verification_source: Literal[
        "deterministic",
        "repository_setup_specialist",
    ]
    setup_verified: bool
    discovery_attempts: int
    docker_image: str = DOCKER_IMAGE
    setup_network_enabled: bool = True
    tests_network_disabled: bool = True


def get_repository_revision(
    repository_path: Path,
) -> str:
    return run_git_command(
        repository_path,
        "rev-parse",
        "HEAD",
    )


def verify_repository_revision(
    repository_path: Path,
    recipe: VerifiedRepositoryTestRecipe,
) -> None:
    actual_revision = get_repository_revision(
        repository_path
    )

    if actual_revision != recipe.repository_revision:
        raise RepositoryEnvironmentVerificationError(
            "Repository revision changed after preflight."
        )


def validate_command_tokens(
    tokens: list[str],
) -> None:
    if not tokens:
        raise RepositorySetupProposalError(
            "A proposed command is empty."
        )

    for token in tokens:
        if (
            not isinstance(token, str)
            or not token.strip()
            or len(token) > 300
        ):
            raise RepositorySetupProposalError(
                "A proposed command contains an invalid token."
            )

        if any(
            fragment in token
            for fragment in UNSAFE_TOKEN_FRAGMENTS
        ):
            raise RepositorySetupProposalError(
                "Shell operators and substitutions are not allowed."
            )

        if (
            token.startswith("/")
            or ".." in PurePosixPath(token).parts
        ):
            raise RepositorySetupProposalError(
                "Absolute paths and path traversal are not allowed."
            )

        option_name = token.split(
            "=",
            1,
        )[0]

        if option_name in UNSAFE_INSTALL_OPTIONS:
            raise RepositorySetupProposalError(
                "The proposed command can write outside "
                "the managed environment."
            )


def validate_repository_setup_proposal(
    proposal: RepositorySetupProposal,
) -> RepositoryTestStrategy:
    if PYTHON_VERSION_PATTERN.fullmatch(
        proposal.python_version
    ) is None:
        raise RepositorySetupProposalError(
            "The proposed Python version must be major.minor."
        )

    normalized_setup_commands: list[
        tuple[str, ...]
    ] = []
    dependency_install_seen = False

    for proposed_command in (
        proposal.dependency_setup_commands
    ):
        validate_command_tokens(
            proposed_command
        )

        if any(
            tuple(
                proposed_command[
                    :len(prefix)
                ]
            ) == prefix
            for prefix in LOCK_GENERATION_PREFIXES
        ):
            raise RepositorySetupProposalError(
                "Lock generation is not allowed during "
                "repository setup discovery."
            )

        normalized_command = (
            normalize_supported_setup_command(
                shlex.join(
                    proposed_command
                )
            )
        )

        if (
            normalized_command is None
            or normalized_command
            != proposed_command
        ):
            raise RepositorySetupProposalError(
                "The proposed setup command is not supported."
            )

        if setup_command_installs_dependencies(
            normalized_command
        ):
            dependency_install_seen = True

        normalized_setup_commands.append(
            tuple(normalized_command)
        )

    if not dependency_install_seen:
        raise RepositorySetupProposalError(
            "The proposal does not install repository dependencies."
        )

    validate_command_tokens(
        proposal.test_command
    )
    normalized_test_command = (
        normalize_supported_test_command(
            shlex.join(
                proposal.test_command
            )
        )
    )

    if (
        normalized_test_command is None
        or normalized_test_command
        != proposal.test_command
    ):
        raise RepositorySetupProposalError(
            "The proposed test command is not supported."
        )

    selection = RepositoryCommandSelection(
        dependency_setup_commands=tuple(
            normalized_setup_commands
        ),
        test_command=tuple(
            normalized_test_command
        ),
        evidence=tuple(
            proposal.evidence
        ),
    )
    test_runner = get_test_runner(
        selection.test_command
    )
    (
        setup_commands,
        persistent_runner,
    ) = materialize_evidenced_setup_commands(
        selection.dependency_setup_commands,
        proposal.python_version,
        test_runner,
    )

    if persistent_runner is None:
        raise RepositorySetupProposalError(
            "The proposal did not create a persistent "
            "test environment."
        )

    if test_runner in {"nox", "tox"}:
        (
            runner_setup,
            test_command,
        ) = build_repository_owned_native_commands(
            test_runner,
            list(selection.test_command),
            persistent_runner,
        )
        setup_commands.append(
            runner_setup
        )
    else:
        test_command = build_persistent_test_command(
            list(selection.test_command),
            persistent_runner,
        )

    return RepositoryTestStrategy(
        python_version=proposal.python_version,
        dependency_setup_commands=tuple(
            setup_commands
        ),
        test_command=test_command,
        evidence=(
            "Repository Setup Specialist fallback",
            *selection.evidence,
        ),
    )


def build_setup_specialist_input(
    project: ProjectContext,
    previous_failure: str,
    attempt: int,
) -> str:
    repository_context = build_repository_context(
        project.files,
        query_text=(
            "Python dependency setup pytest nox tox "
            "CI workflow contributing requirements "
            + previous_failure
        ),
        preferred_paths=SETUP_EVIDENCE_PATHS,
        max_context_chars=80_000,
    )

    return f"""
=== REPOSITORY SETUP DISCOVERY ===
Attempt: {attempt} of {MAX_SETUP_DISCOVERY_ATTEMPTS}

Propose one supported Python dependency setup and repository-native test recipe.
Commands must be argument lists. Do not propose source/configuration edits, lock
generation, Git commands, filesystem mutation, arbitrary scripts, or shell syntax.

=== PREVIOUS DETERMINISTIC OR DISCOVERY FAILURE ===
{previous_failure}

=== README ===
{project.readme}

=== CONTRIBUTING ===
{project.contributing}

=== BOUNDED REPOSITORY SETUP CONTEXT ===
{repository_context}
""".strip()


async def propose_repository_setup(
    project: ProjectContext,
    previous_failure: str,
    attempt: int,
    *,
    run_id: UUID,
) -> RepositorySetupProposal:
    specialist_input = build_setup_specialist_input(
        project,
        previous_failure,
        attempt,
    )
    configured_agent = (
        configure_agent_for_run_invocation(
            REPOSITORY_SETUP_SPECIALIST_AGENT_ID,
            repository_setup_specialist,
            run_id,
        )
    )
    result = await Runner.run(
        configured_agent,
        specialist_input,
        max_turns=2,
    )

    if not isinstance(
        result.final_output,
        RepositorySetupProposal,
    ):
        raise TypeError(
            "Repository Setup Specialist returned "
            "an unexpected output type."
        )

    return result.final_output


def describe_test_result(
    result: RepositoryTestResult,
) -> str:
    return "\n".join(
        build_test_failure_details(
            result,
            max_output_lines=20,
        )
    )


def report_preflight_failure(
    progress_callback: RunProgressCallback | None,
    message: str,
    result: RepositoryTestResult | None,
) -> None:
    details = (
        build_test_failure_details(result)
        if result is not None
        else ()
    )
    report_run_progress(
        progress_callback,
        "preflight_failed",
        message,
        details,
    )


async def verify_repository_environment(
    project: ProjectContext,
    progress_callback: RunProgressCallback | None = None,
    *,
    run_id: UUID,
) -> VerifiedRepositoryTestRecipe:
    repository_path = project.repository_path.resolve()
    repository_revision = get_repository_revision(
        repository_path
    )

    report_run_progress(
        progress_callback,
        "preflight_started",
        "Repository preflight",
    )
    report_run_progress(
        progress_callback,
        "preflight_detecting",
        "Detecting test environment",
    )

    deterministic_strategy: (
        RepositoryTestStrategy | None
    ) = None
    previous_failure = ""
    last_result: RepositoryTestResult | None = None

    try:
        deterministic_strategy = (
            build_repository_test_strategy(
                repository_path,
                project.issue,
            )
        )
    except RepositoryTestRunnerError as error:
        previous_failure = str(error)

    if deterministic_strategy is not None:
        report_run_progress(
            progress_callback,
            "preflight_verifying",
            "Verifying untouched repository",
        )
        last_result = execute_repository_test_strategy(
            repository_path,
            deterministic_strategy,
            protect_repository_files=True,
        )

        if last_result.stage == "tests":
            if not last_result.passed:
                message = (
                    "Untouched repository baseline tests failed."
                )
                report_preflight_failure(
                    progress_callback,
                    message,
                    last_result,
                )
                raise RepositoryEnvironmentVerificationError(
                    message,
                    last_result,
                )

            report_run_progress(
                progress_callback,
                "preflight_passed",
                "Baseline passed",
            )
            return VerifiedRepositoryTestRecipe(
                strategy=deterministic_strategy,
                baseline_result=last_result,
                repository_revision=repository_revision,
                verification_source="deterministic",
                setup_verified=True,
                discovery_attempts=0,
            )

        previous_failure = describe_test_result(
            last_result
        )

    for attempt in range(
        1,
        MAX_SETUP_DISCOVERY_ATTEMPTS + 1,
    ):
        report_run_progress(
            progress_callback,
            "preflight_discovery",
            (
                "Setup specialist attempt "
                f"{attempt}/{MAX_SETUP_DISCOVERY_ATTEMPTS}"
            ),
        )

        try:
            proposal = await propose_repository_setup(
                project,
                previous_failure,
                attempt,
                run_id=run_id,
            )
            strategy = (
                validate_repository_setup_proposal(
                    proposal
                )
            )
        except Exception as error:
            previous_failure = (
                "Setup proposal was rejected: "
                f"{error}"
            )
            continue

        report_run_progress(
            progress_callback,
            "preflight_verifying",
            "Verifying untouched repository",
        )
        last_result = execute_repository_test_strategy(
            repository_path,
            strategy,
            protect_repository_files=True,
        )

        if last_result.stage == "tests":
            if not last_result.passed:
                message = (
                    "Untouched repository baseline tests failed."
                )
                report_preflight_failure(
                    progress_callback,
                    message,
                    last_result,
                )
                raise RepositoryEnvironmentVerificationError(
                    message,
                    last_result,
                )

            report_run_progress(
                progress_callback,
                "preflight_passed",
                "Baseline passed",
            )
            return VerifiedRepositoryTestRecipe(
                strategy=strategy,
                baseline_result=last_result,
                repository_revision=repository_revision,
                verification_source=(
                    "repository_setup_specialist"
                ),
                setup_verified=True,
                discovery_attempts=attempt,
            )

        previous_failure = describe_test_result(
            last_result
        )

    message = (
        "Contrigent could not establish a reliable "
        "repository test environment."
    )
    report_preflight_failure(
        progress_callback,
        message,
        last_result,
    )
    raise RepositoryEnvironmentVerificationError(
        message,
        last_result,
    )
