import importlib
from pathlib import PurePosixPath
from contrigent_api.services.repository_context_builder import (
    build_repository_context,
)

from agents import Runner

from contrigent_api.agents.issue_analyzer.output_schema import (
    IssueAnalysis,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.models.project_context import (
    ProjectContext,
)

from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)

from contrigent_api.services.worker_discovery import (
    discover_workers,
)
from contrigent_api.services.issue_image_input_builder import (
    build_input_with_issue_images,
)


def get_available_worker(
    worker_id: str,
) -> dict:
    available_workers = {
        worker["id"]: worker
        for worker in discover_workers()
        if worker.get("enabled") is True
    }

    if worker_id not in available_workers:
        raise ValueError(
            f"Worker is not available: {worker_id}"
        )

    return available_workers[worker_id]


def load_worker_agent(
    worker_id: str,
):
    get_available_worker(worker_id)

    module_name = (
        "contrigent_api.agents.workers."
        f"{worker_id}.agent"
    )

    module = importlib.import_module(
        module_name
    )

    worker_agent = getattr(
        module,
        "agent",
        None,
    )

    if worker_agent is None:
        raise ValueError(
            f"Worker has no agent definition: {worker_id}"
        )

    return worker_agent


def validate_replacement_path(
    file_path: str,
) -> str:
    clean_path = file_path.strip()

    if not clean_path:
        raise ValueError(
            "Worker returned a blank replacement file path."
        )

    path = PurePosixPath(clean_path)

    if path.is_absolute() or ".." in path.parts:
        raise ValueError(
            f"Worker returned an unsafe replacement path: {file_path}"
        )

    return path.as_posix()


def remove_unchanged_replacements(
    worker_result: WorkerResult,
    sample_project: ProjectContext,
) -> WorkerResult:
    changed_files = []

    for replacement in worker_result.files_to_replace:
        safe_path = validate_replacement_path(
            replacement.file_path
        )

        original_content = sample_project.files.get(
            safe_path
        )

        if (
            original_content is not None
            and original_content
            == replacement.replacement_content
        ):
            continue

        changed_files.append(
            FileReplacement(
                file_path=safe_path,
                reason=replacement.reason,
                replacement_content=(
                    replacement.replacement_content
                ),
            )
        )

    return WorkerResult(
        summary=worker_result.summary,
        findings=worker_result.findings,
        files_to_replace=changed_files,
    )
def build_project_with_proposed_files(
    sample_project: ProjectContext,
    proposed_files: list[FileReplacement],
) -> ProjectContext:
    candidate_files = dict(
        sample_project.files
    )

    for replacement in proposed_files:
        safe_path = validate_replacement_path(
            replacement.file_path
        )

        candidate_files[safe_path] = (
            replacement.replacement_content
        )

    return ProjectContext(
        project_name=sample_project.project_name,
        project_source=sample_project.project_source,
        repository_path=sample_project.repository_path,
        issue=sample_project.issue,
        readme=sample_project.readme,
        contributing=sample_project.contributing,
        files=candidate_files,
        issue_images=sample_project.issue_images,
    )


def merge_proposed_files(
    original_project: ProjectContext,
    existing_proposed_files: list[FileReplacement],
    revised_proposed_files: list[FileReplacement],
) -> list[FileReplacement]:
    final_files_by_path: dict[
        str,
        FileReplacement,
    ] = {}

    for replacement in (
        existing_proposed_files
        + revised_proposed_files
    ):
        safe_path = validate_replacement_path(
            replacement.file_path
        )

        final_files_by_path[safe_path] = (
            FileReplacement(
                file_path=safe_path,
                reason=replacement.reason,
                replacement_content=(
                    replacement.replacement_content
                ),
            )
        )

    final_files: list[FileReplacement] = []

    for replacement in final_files_by_path.values():
        original_content = original_project.files.get(
            replacement.file_path
        )

        if (
            original_content is not None
            and original_content
            == replacement.replacement_content
        ):
            continue

        final_files.append(replacement)

    return final_files


def build_worker_input(
    worker_id: str,
    assigned_task: str,
    shared_worker_results: dict[str, WorkerResult],
    sample_project: ProjectContext,
    issue_analysis: IssueAnalysis,
    candidate_test_result: (
        RepositoryTestResult | None
    ) = None,
) -> str:
    worker = get_available_worker(
        worker_id
    )

    dependency_file_paths = [
        replacement.file_path
        for result
        in shared_worker_results.values()
        for replacement
        in result.files_to_replace
    ]

    preferred_paths = [
        *issue_analysis.likely_files,
        *dependency_file_paths,
    ]

    query_parts = [
        sample_project.issue,
        assigned_task,
        issue_analysis.summary,
    ]

    if candidate_test_result is not None:
        query_parts.extend(
            [
                candidate_test_result.stdout,
                candidate_test_result.stderr,
            ]
        )

    repository_context = (
        build_repository_context(
            sample_project.files,
            query_text="\n".join(
                query_parts
            ),
            preferred_paths=preferred_paths,
        )
    )

    capabilities = ", ".join(
        worker.get("capabilities", [])
    )

    if shared_worker_results:
        shared_results = "\n\n".join(
            f"--- RESULT FROM: {dependency_id} ---\n"
            f"{result.model_dump_json(indent=2)}"
            for dependency_id, result
            in shared_worker_results.items()
        )
    else:
        shared_results = (
            "No earlier worker results were assigned to you."
        )

    if candidate_test_result is None:
        candidate_test_text = (
            "No candidate Docker test result "
            "was supplied."
        )
    else:
        candidate_test_text = (
            candidate_test_result.model_dump_json(
                indent=2
            )
        )

    return f"""
=== ASSIGNED WORKER ===
Worker ID: {worker["id"]}
Name: {worker["name"]}
Description: {worker["description"]}
Capabilities: {capabilities or "None listed"}

=== YOUR ASSIGNED TASK ===
{assigned_task}

=== RESULTS SHARED BY MANAGER ===
{shared_results}

=== CANDIDATE DOCKER TEST RESULT ===
{candidate_test_text}

=== ORIGINAL GITHUB ISSUE ===
{sample_project.issue}

=== REPOSITORY README ===
{sample_project.readme}

=== REPOSITORY CONTRIBUTING INSTRUCTIONS ===
{sample_project.contributing}

=== APPROVED MANAGER ANALYSIS AND PLAN ===
{issue_analysis.model_dump_json(indent=2)}

=== REPOSITORY CONTEXT ===
{repository_context}
""".strip()


async def run_worker(
    worker_id: str,
    assigned_task: str,
    shared_worker_results: dict[str, WorkerResult],
    sample_project: ProjectContext,
    issue_analysis: IssueAnalysis,
    candidate_test_result: (
        RepositoryTestResult | None
    ) = None,
) -> WorkerResult:
    worker_agent = load_worker_agent(
        worker_id
    )

    worker_input = build_worker_input(
        worker_id,
        assigned_task,
        shared_worker_results,
        sample_project,
        issue_analysis,
        candidate_test_result,
    )

    result = await Runner.run(
        worker_agent,
        build_input_with_issue_images(
            worker_input,
            sample_project,
        ),
        max_turns=3,
    )

    if not isinstance(
        result.final_output,
        WorkerResult,
    ):
        raise TypeError(
            f"Worker returned an unexpected output type: {worker_id}"
        )

    return remove_unchanged_replacements(
        result.final_output,
        sample_project,
    )


async def run_assigned_workers(
    sample_project: ProjectContext,
    issue_analysis: IssueAnalysis,
    candidate_test_result: (
        RepositoryTestResult | None
    ) = None,
) -> tuple[
    dict[str, WorkerResult],
    list[FileReplacement],
]:
    worker_results: dict[str, WorkerResult] = {}
    proposed_files_by_path: dict[
        str,
        FileReplacement,
    ] = {}

    assignments = sorted(
        issue_analysis.worker_assignments,
        key=lambda assignment: assignment.order,
    )

    for assignment in assignments:
        shared_worker_results = {
            dependency_id: worker_results[
                dependency_id
            ]
            for dependency_id
            in assignment.depends_on
        }

        worker_result = await run_worker(
            assignment.worker_id,
            assignment.task,
            shared_worker_results,
            sample_project,
            issue_analysis,
            candidate_test_result,
        )

        worker_results[
            assignment.worker_id
        ] = worker_result

        for replacement in (
            worker_result.files_to_replace
        ):
            existing_replacement = (
                proposed_files_by_path.get(
                    replacement.file_path
                )
            )

            if (
                existing_replacement is not None
                and existing_replacement.replacement_content
                != replacement.replacement_content
            ):
                raise ValueError(
                    "Workers proposed conflicting replacements for: "
                    f"{replacement.file_path}"
                )

            proposed_files_by_path[
                replacement.file_path
            ] = replacement

    return (
        worker_results,
        list(proposed_files_by_path.values()),
    )