from agents import Runner

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)
from contrigent_api.agents.issue_analyzer.agent import (
    issue_analyzer,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    IssueAnalysis,
    WorkerAssignment,
)
from contrigent_api.models.project_context import (
    ProjectContext,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
from contrigent_api.services.worker_discovery import (
    discover_workers,
)

from contrigent_api.services.issue_image_input_builder import (
    build_input_with_issue_images,
)

def build_available_workers_section(
    workers: list[dict],
) -> str:
    enabled_workers = [
        worker
        for worker in workers
        if worker.get("enabled") is True
    ]

    if not enabled_workers:
        return (
            "No worker agents are currently available."
        )

    worker_sections = []

    for worker in enabled_workers:
        capabilities = ", ".join(
            worker.get("capabilities", [])
        )

        worker_sections.append(
            f"""Worker ID: {worker["id"]}
Name: {worker["name"]}
Description: {worker["description"]}
Capabilities: {capabilities or "None listed"}"""
        )

    return "\n\n".join(worker_sections)


def build_analysis_input(
    project: ProjectContext,
    workers: list[dict],
) -> str:
    repository_files = "\n\n".join(
        f"--- FILE: {path} ---\n{content}"
        for path, content in project.files.items()
    )

    available_workers = (
        build_available_workers_section(
            workers
        )
    )

    return f"""
=== AVAILABLE WORKERS ===
{available_workers}

=== GITHUB ISSUE ===
{project.issue}

=== README ===
{project.readme}

=== CONTRIBUTING INSTRUCTIONS ===
{project.contributing}

=== REPOSITORY FILES ===
{repository_files}
""".strip()


def validate_worker_assignments(
    worker_assignments: list[WorkerAssignment],
    available_workers: list[dict],
) -> None:
    available_worker_ids = {
        worker["id"]
        for worker in available_workers
        if worker.get("enabled") is True
    }

    selected_worker_ids = [
        assignment.worker_id
        for assignment in worker_assignments
    ]

    unknown_workers = (
        set(selected_worker_ids)
        - available_worker_ids
    )

    if unknown_workers:
        raise ValueError(
            "Issue Analyzer assigned unavailable workers: "
            + ", ".join(
                sorted(unknown_workers)
            )
        )

    if len(selected_worker_ids) != len(
        set(selected_worker_ids)
    ):
        raise ValueError(
            "Issue Analyzer assigned the same "
            "worker more than once."
        )

    assignment_orders = [
        assignment.order
        for assignment in worker_assignments
    ]

    if len(assignment_orders) != len(
        set(assignment_orders)
    ):
        raise ValueError(
            "Worker assignment order values "
            "must be unique."
        )

    assignments_by_worker_id = {
        assignment.worker_id: assignment
        for assignment in worker_assignments
    }

    for assignment in worker_assignments:
        for dependency_id in (
            assignment.depends_on
        ):
            dependency = (
                assignments_by_worker_id.get(
                    dependency_id
                )
            )

            if dependency is None:
                raise ValueError(
                    f"Worker '{assignment.worker_id}' "
                    "depends on unassigned worker "
                    f"'{dependency_id}'."
                )

            if (
                dependency.order
                >= assignment.order
            ):
                raise ValueError(
                    f"Worker '{assignment.worker_id}' "
                    f"depends on '{dependency_id}', but "
                    "dependencies must run earlier."
                )


async def analyze_project(
    project: ProjectContext,
):
    workers = discover_workers()

    agent_input = build_analysis_input(
        project,
        workers,
    )

    result = await Runner.run(
        issue_analyzer,
        build_input_with_issue_images(
            agent_input,
            project,
        ),
        max_turns=3,
    )
    if not isinstance(
        result.final_output,
        IssueAnalysis,
    ):
        raise TypeError(
            "Issue Analyzer returned an "
            "unexpected output type."
        )

    validate_worker_assignments(
        result.final_output.worker_assignments,
        workers,
    )

    return (
        result.final_output,
        result.context_wrapper.usage,
    )


def build_revision_input(
    project: ProjectContext,
    workers: list[dict],
    original_analysis: IssueAnalysis,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
    reviewer_result: ReviewerResult,
    candidate_test_result: (
        RepositoryTestResult | None
    ) = None,
) -> str:
    repository_files = "\n\n".join(
        f"--- FILE: {path} ---\n{content}"
        for path, content in project.files.items()
    )

    available_workers = (
        build_available_workers_section(
            workers
        )
    )

    worker_results_text = "\n\n".join(
        f"--- WORKER: {worker_id} ---\n"
        f"{result.model_dump_json(indent=2)}"
        for worker_id, result
        in worker_results.items()
    )

    if not worker_results_text:
        worker_results_text = (
            "No worker results."
        )

    proposed_files_text = "\n\n".join(
        (
            "--- PROPOSED FILE: "
            f"{replacement.file_path} ---\n"
            f"Reason: {replacement.reason}\n"
            "--- REPLACEMENT CONTENT START ---\n"
            f"{replacement.replacement_content}\n"
            "--- REPLACEMENT CONTENT END ---"
        )
        for replacement in proposed_files
    )

    if not proposed_files_text:
        proposed_files_text = (
            "No files were proposed."
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
=== REVISION TASK ===
The Independent Reviewer returned `changes_required` for the current candidate.
Re-evaluate the review findings against the original GitHub issue, repository evidence,
and approved scope. Decide which findings are valid and in scope, which findings are
unsupported or out of scope, and whether the implementation approach or worker tasks
must change. Create revised worker assignments for only the work that is actually
needed. Do not expand scope merely to satisfy a reviewer comment.

=== AVAILABLE WORKERS ===
{available_workers}

=== ORIGINAL GITHUB ISSUE ===
{project.issue}

=== README ===
{project.readme}

=== CONTRIBUTING INSTRUCTIONS ===
{project.contributing}

=== CURRENT MANAGER ANALYSIS AND PLAN ===
{original_analysis.model_dump_json(indent=2)}

=== CURRENT WORKER RESULTS ===
{worker_results_text}

=== CURRENT COMBINED PROPOSED FILES ===
{proposed_files_text}

=== CANDIDATE DOCKER TEST RESULT ===
{candidate_test_text}

=== INDEPENDENT REVIEWER FEEDBACK ===
{reviewer_result.model_dump_json(indent=2)}

=== ORIGINAL REPOSITORY FILES ===
{repository_files}
""".strip()


async def replan_after_review(
    project: ProjectContext,
    original_analysis: IssueAnalysis,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
    reviewer_result: ReviewerResult,
    candidate_test_result: (
        RepositoryTestResult | None
    ) = None,
):
    workers = discover_workers()

    agent_input = build_revision_input(
        project,
        workers,
        original_analysis,
        worker_results,
        proposed_files,
        reviewer_result,
        candidate_test_result,
    )

    result = await Runner.run(
        issue_analyzer,
        build_input_with_issue_images(
            agent_input,
            project,
        ),
        max_turns=3,
    )

    if not isinstance(
        result.final_output,
        IssueAnalysis,
    ):
        raise TypeError(
            "Issue Analyzer returned an "
            "unexpected output type."
        )

    validate_worker_assignments(
        result.final_output.worker_assignments,
        workers,
    )

    return (
        result.final_output,
        result.context_wrapper.usage,
    )


def build_test_failure_revision_input(
    project: ProjectContext,
    workers: list[dict],
    current_analysis: IssueAnalysis,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
    test_result: RepositoryTestResult,
) -> str:
    repository_files = "\n\n".join(
        f"--- FILE: {path} ---\n{content}"
        for path, content in project.files.items()
    )

    available_workers = (
        build_available_workers_section(
            workers
        )
    )

    worker_results_text = "\n\n".join(
        f"--- WORKER: {worker_id} ---\n"
        f"{result.model_dump_json(indent=2)}"
        for worker_id, result
        in worker_results.items()
    )

    if not worker_results_text:
        worker_results_text = (
            "No worker results."
        )

    proposed_files_text = "\n\n".join(
        (
            "--- PROPOSED FILE: "
            f"{replacement.file_path} ---\n"
            f"Reason: {replacement.reason}\n"
            "--- REPLACEMENT CONTENT START ---\n"
            f"{replacement.replacement_content}\n"
            "--- REPLACEMENT CONTENT END ---"
        )
        for replacement in proposed_files
    )

    if not proposed_files_text:
        proposed_files_text = (
            "No files were proposed."
        )

    return f"""
=== TEST FAILURE REMEDIATION TASK ===
The current candidate was executed by Contrigent's deterministic Docker test runner
and did not pass. Diagnose the supplied test evidence. Decide whether the failure comes
from application code, a newly proposed test, an existing regression, dependency setup,
or another issue-relevant cause. Create revised worker assignments only for work needed
to make the candidate correct. Do not weaken or delete a valid failing test merely to
make the suite green. Preserve valid existing and previously proposed tests unless a
specific test is incorrect or no longer relevant.

=== AVAILABLE WORKERS ===
{available_workers}

=== ORIGINAL GITHUB ISSUE ===
{project.issue}

=== README ===
{project.readme}

=== CONTRIBUTING INSTRUCTIONS ===
{project.contributing}

=== CURRENT MANAGER ANALYSIS AND PLAN ===
{current_analysis.model_dump_json(indent=2)}

=== CURRENT WORKER RESULTS ===
{worker_results_text}

=== CURRENT COMBINED PROPOSED FILES ===
{proposed_files_text}

=== ACTUAL DOCKER TEST RESULT ===
{test_result.model_dump_json(indent=2)}

=== ORIGINAL REPOSITORY FILES ===
{repository_files}
""".strip()


async def replan_after_test_failure(
    project: ProjectContext,
    current_analysis: IssueAnalysis,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
    test_result: RepositoryTestResult,
):
    workers = discover_workers()

    agent_input = (
        build_test_failure_revision_input(
            project,
            workers,
            current_analysis,
            worker_results,
            proposed_files,
            test_result,
        )
    )

    result = await Runner.run(
        issue_analyzer,
        build_input_with_issue_images(
            agent_input,
            project,
        ),
        max_turns=3,
    )

    if not isinstance(
        result.final_output,
        IssueAnalysis,
    ):
        raise TypeError(
            "Issue Analyzer returned an "
            "unexpected output type."
        )

    validate_worker_assignments(
        result.final_output.worker_assignments,
        workers,
    )

    return (
        result.final_output,
        result.context_wrapper.usage,
    )


async def analyze_sample_project(
    project_name: str,
):
    project = load_sample_project(
        project_name
    )

    return await analyze_project(
        project
    )