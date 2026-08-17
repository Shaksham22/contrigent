from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from fnmatch import fnmatch
import re
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
from contrigent_api.agents.issue_analyzer.output_schema import (
    IssueAnalysis,
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
    RepositoryExecutionStrategy,
    RepositoryService,
    RepositoryTestRunnerError,
    RepositoryTestNetworkMode,
    build_repository_test_strategy,
    execute_repository_test_strategy,
)
from contrigent_api.services.repository_ecosystems import (
    ECOSYSTEM_REGISTRY,
    get_ecosystem_definition,
)
from contrigent_api.services.run_progress import (
    RunProgressCallback,
    build_test_failure_details,
    report_run_progress,
)


MAX_SETUP_DISCOVERY_ATTEMPTS = 2
RUNTIME_VERSION_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
ENVIRONMENT_VARIABLE_NAME_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)
NETWORK_NAME_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$"
)
FORBIDDEN_CREDENTIAL_VARIABLES = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "DOCKER_HOST",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "OPENAI_API_KEY",
    "SSH_AUTH_SOCK",
}
COMMON_SETUP_EVIDENCE_PATTERNS = (
    "CONTRIBUTING*",
    "AGENTS.md",
    "README*",
    ".github/workflows/*",
    "Makefile",
    "justfile",
    "Taskfile*",
    "scripts/*",
    "Dockerfile*",
    "compose*.yml",
    "compose*.yaml",
    "docker-compose*.yml",
    "docker-compose*.yaml",
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
class VerifiedRepositoryEnvironment:
    strategy: RepositoryExecutionStrategy
    baseline_result: RepositoryTestResult
    repository_revision: str
    verification_source: Literal[
        "deterministic",
        "repository_setup_specialist",
    ]
    setup_verified: bool
    discovery_attempts: int

    @property
    def docker_image(self) -> str:
        return self.strategy.docker_image

    @property
    def setup_network_enabled(self) -> bool:
        return True

    @property
    def tests_network_disabled(self) -> bool:
        return (
            self.strategy.test_network_mode
            == RepositoryTestNetworkMode.NONE
        )


VerifiedRepositoryTestRecipe = VerifiedRepositoryEnvironment


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
    recipe: VerifiedRepositoryEnvironment,
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
            or "\x00" in token
            or len(token) > 4_000
        ):
            raise RepositorySetupProposalError(
                "A proposed command contains an invalid token."
            )

def validate_project_root(
    project_root: str,
    repository_path: Path | None = None,
) -> str:
    clean_root = project_root.strip() or "."
    path = PurePosixPath(clean_root)

    if path.is_absolute() or ".." in path.parts:
        raise RepositorySetupProposalError(
            "The proposed project root must remain inside "
            "the repository."
        )

    normalized = path.as_posix()

    if repository_path is not None:
        repository_root = repository_path.resolve()
        candidate = (
            repository_root / normalized
        ).resolve()

        try:
            candidate.relative_to(repository_root)
        except ValueError as error:
            raise RepositorySetupProposalError(
                "The proposed project root escapes the repository."
            ) from error

        if not candidate.is_dir():
            raise RepositorySetupProposalError(
                "The proposed project root does not exist or "
                "is not a directory."
            )

    return normalized


def directory_has_registered_manifest(
    directory: Path,
) -> bool:
    return any(
        any(directory.glob(pattern))
        for definition in ECOSYSTEM_REGISTRY.values()
        for pattern in definition.evidence_paths
    )


def nearest_manifest_root_for_assignment(
    repository_path: Path,
    assigned_file_path: str,
) -> PurePosixPath | None:
    relative_path = PurePosixPath(
        assigned_file_path
    )
    candidate = relative_path.parent

    while True:
        directory = (
            repository_path / candidate.as_posix()
        )

        if directory_has_registered_manifest(directory):
            return candidate

        if candidate == PurePosixPath("."):
            return None

        candidate = candidate.parent


def determine_project_root(
    repository_path: Path,
    analysis: IssueAnalysis | None,
) -> str:
    repository_root = repository_path.resolve()

    if analysis is None:
        return "."

    assigned_paths = [
        file_path
        for assignment in analysis.worker_assignments
        for file_path in assignment.files
    ]

    if not assigned_paths:
        return "."

    manifest_roots = [
        nearest_manifest_root_for_assignment(
            repository_root,
            file_path,
        )
        for file_path in assigned_paths
    ]

    if any(root is None for root in manifest_roots):
        return "."

    concrete_roots = [
        root
        for root in manifest_roots
        if root is not None
    ]

    if len(set(concrete_roots)) == 1:
        return validate_project_root(
            concrete_roots[0].as_posix(),
            repository_root,
        )

    common_parts = list(concrete_roots[0].parts)

    for root in concrete_roots[1:]:
        shared_length = 0

        for left, right in zip(
            common_parts,
            root.parts,
            strict=False,
        ):
            if left != right:
                break
            shared_length += 1

        common_parts = common_parts[:shared_length]

        if not common_parts:
            break

    common_root = PurePosixPath(*common_parts)

    while True:
        if directory_has_registered_manifest(
            repository_root / common_root.as_posix()
        ):
            return validate_project_root(
                common_root.as_posix(),
                repository_root,
            )

        if common_root == PurePosixPath("."):
            return "."

        common_root = common_root.parent


def validate_environment_variables(
    variables: dict[str, str],
) -> dict[str, str]:
    validated: dict[str, str] = {}

    for name, value in variables.items():
        if (
            ENVIRONMENT_VARIABLE_NAME_PATTERN.fullmatch(name)
            is None
        ):
            raise RepositorySetupProposalError(
                "A proposed environment variable name is invalid."
            )

        if name.upper() in FORBIDDEN_CREDENTIAL_VARIABLES:
            raise RepositorySetupProposalError(
                "Repository execution cannot receive host or "
                "publication credentials."
            )

        if not isinstance(value, str) or "\x00" in value:
            raise RepositorySetupProposalError(
                "A proposed environment variable value is invalid."
            )

        validated[name] = value

    return validated


def validate_repository_setup_proposal(
    proposal: RepositorySetupProposal,
    repository_path: Path | None = None,
) -> RepositoryExecutionStrategy:
    try:
        ecosystem = get_ecosystem_definition(
            proposal.ecosystem
        )
    except ValueError as error:
        raise RepositorySetupProposalError(
            str(error)
        ) from error

    runtime_version = (
        proposal.runtime_version
        or ecosystem.default_runtime_version
    )

    if (
        runtime_version is not None
        and RUNTIME_VERSION_PATTERN.fullmatch(
            runtime_version
        ) is None
    ):
        raise RepositorySetupProposalError(
            "The proposed runtime version is invalid."
        )

    project_root = validate_project_root(
        proposal.project_root,
        repository_path,
    )
    all_commands = (
        *proposal.dependency_setup_commands,
        *proposal.background_commands,
        *proposal.pre_test_commands,
        *proposal.test_commands,
    )

    for command in all_commands:
        validate_command_tokens(command)

    environment_variables = (
        validate_environment_variables(
            proposal.environment_variables
        )
    )
    services: list[RepositoryService] = []

    for service in proposal.services:
        if (
            NETWORK_NAME_PATTERN.fullmatch(service.name)
            is None
            or NETWORK_NAME_PATTERN.fullmatch(
                service.network_alias
            )
            is None
        ):
            raise RepositorySetupProposalError(
                "A proposed service name or network alias is invalid."
            )

        if (
            not service.image.strip()
            or service.image.startswith("-")
            or any(character.isspace() for character in service.image)
        ):
            raise RepositorySetupProposalError(
                "A proposed service image is invalid."
            )

        if service.command:
            validate_command_tokens(service.command)

        if service.readiness_command:
            validate_command_tokens(
                service.readiness_command
            )

        services.append(
            RepositoryService(
                name=service.name,
                image=service.image,
                command=tuple(service.command),
                environment_variables=(
                    validate_environment_variables(
                        service.environment_variables
                    )
                ),
                network_alias=service.network_alias,
                readiness_command=tuple(
                    service.readiness_command
                ),
                startup_timeout_seconds=(
                    service.startup_timeout_seconds
                ),
            )
        )

    test_network_mode = RepositoryTestNetworkMode(
        proposal.test_network_mode.value
    )

    if services and test_network_mode == RepositoryTestNetworkMode.NONE:
        raise RepositorySetupProposalError(
            "Service containers require services_only or internet "
            "test networking."
        )

    return RepositoryExecutionStrategy(
        ecosystem=ecosystem.name,
        runtime_version=runtime_version,
        project_root=project_root,
        docker_image=(
            ecosystem.docker_image_for_runtime(
                runtime_version
            )
        ),
        setup_commands=tuple(
            tuple(command)
            for command
            in proposal.dependency_setup_commands
        ),
        background_commands=tuple(
            tuple(command)
            for command in proposal.background_commands
        ),
        pre_test_commands=tuple(
            tuple(command)
            for command in proposal.pre_test_commands
        ),
        test_commands=tuple(
            tuple(command)
            for command in proposal.test_commands
        ),
        environment_variables=environment_variables,
        test_network_mode=test_network_mode,
        services=tuple(services),
        evidence=(
            "Repository Setup Specialist fallback",
            *proposal.evidence,
        ),
    )


def build_setup_specialist_input(
    project: ProjectContext,
    previous_failure: str,
    attempt: int,
    project_root: str = ".",
) -> str:
    ecosystem_evidence_patterns = tuple(
        pattern
        for definition in ECOSYSTEM_REGISTRY.values()
        for pattern in definition.evidence_paths
    )
    preferred_paths = tuple(
        path
        for path in project.files
        if (
            any(
                fnmatch(path, pattern)
                or fnmatch(Path(path).name, pattern)
                for pattern in COMMON_SETUP_EVIDENCE_PATTERNS
            )
            or (
                (
                    project_root == "."
                    or path == project_root
                    or path.startswith(project_root + "/")
                )
                and any(
                    fnmatch(path, pattern)
                    or fnmatch(Path(path).name, pattern)
                    for pattern
                    in ecosystem_evidence_patterns
                )
            )
        )
    )
    repository_context = build_repository_context(
        project.files,
        query_text=(
            "repository dependency setup build test scripts "
            "CI workflow contributing package manager services "
            + previous_failure
        ),
        preferred_paths=preferred_paths,
        max_context_chars=80_000,
    )

    return f"""
=== REPOSITORY SETUP DISCOVERY ===
Attempt: {attempt} of {MAX_SETUP_DISCOVERY_ATTEMPTS}

Propose one repository-native setup and test recipe for project root:
{project_root}

Commands must be structured argument lists. Repository-owned scripts, package
manager commands, build tools, local background processes, disposable service
containers, and normal file generation inside the sandbox are allowed when the
repository evidence requires them. Do not propose source patches or publication.

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
    project_root: str = ".",
    *,
    run_id: UUID,
) -> RepositorySetupProposal:
    specialist_input = build_setup_specialist_input(
        project,
        previous_failure,
        attempt,
        project_root,
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
    analysis: IssueAnalysis | None = None,
    progress_callback: RunProgressCallback | None = None,
    *,
    run_id: UUID,
) -> VerifiedRepositoryTestRecipe:
    repository_path = project.repository_path.resolve()
    project_root = determine_project_root(
        repository_path,
        analysis,
    )
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
        RepositoryExecutionStrategy | None
    ) = None
    previous_failure = ""
    last_result: RepositoryTestResult | None = None

    try:
        deterministic_strategy = (
            build_repository_test_strategy(
                repository_path,
                project.issue,
                project_root=project_root,
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
        )

        if (
            last_result.stage == "tests"
            and last_result.passed
        ):
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
                project_root,
                run_id=run_id,
            )

            if "project_root" not in proposal.model_fields_set:
                proposal = proposal.model_copy(
                    update={
                        "project_root": project_root,
                    }
                )

            strategy = (
                validate_repository_setup_proposal(
                    proposal,
                    repository_path,
                )
            )

            if (
                project_root != "."
                and strategy.project_root != project_root
                and not strategy.project_root.startswith(
                    project_root + "/"
                )
            ):
                raise RepositorySetupProposalError(
                    "The proposed project root is unrelated to "
                    "the Manager-selected subproject."
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
        )

        if (
            last_result.stage == "tests"
            and last_result.passed
        ):
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
        "Contrigent could not establish a passing "
        "untouched repository baseline."
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
