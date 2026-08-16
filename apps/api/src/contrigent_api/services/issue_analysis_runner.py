from agents import Runner

from contrigent_api.services.repository_context_builder import (
    build_repository_context,
)

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)
from contrigent_api.agents.issue_analyzer.agent import (
    issue_analyzer,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
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
    repository_context = (
        build_repository_context(
            project.files,
            query_text=project.issue,
        )
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

=== REPOSITORY CONTEXT ===
{repository_context}
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
    preferred_paths = [
        *original_analysis.likely_files,
        *[
            replacement.file_path
            for replacement
            in proposed_files
        ],
        *reviewer_result.files_reviewed,
    ]

    repository_context = (
        build_repository_context(
            project.files,
            query_text=(
                project.issue
                + "\n"
                + original_analysis.summary
                + "\n"
                + reviewer_result.summary
                + "\n"
                + "\n".join(
                    finding.description
                    for finding
                    in reviewer_result.findings
                )
            ),
            preferred_paths=preferred_paths,
        )
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

=== REPOSITORY CONTEXT ===
{repository_context}
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
def build_proposed_file_ownership_section(
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
) -> str:
    owners_by_path: dict[
        str,
        set[str],
    ] = {}

    for worker_id, result in (
        worker_results.items()
    ):
        for replacement in (
            result.files_to_replace
        ):
            owners_by_path.setdefault(
                replacement.file_path,
                set(),
            ).add(
                worker_id
            )

    lines = []

    for replacement in proposed_files:
        owners = sorted(
            owners_by_path.get(
                replacement.file_path,
                set(),
            )
        )

        owner_text = (
            ", ".join(owners)
            if owners
            else "unknown"
        )

        lines.append(
            (
                f"{replacement.file_path} "
                f"→ {owner_text}"
            )
        )

    if not lines:
        return (
            "No proposed files."
        )

    return "\n".join(lines)


def find_test_referenced_proposed_paths(
    proposed_files: list[FileReplacement],
    test_result: RepositoryTestResult,
) -> list[str]:
    test_output = (
        test_result.stdout
        + "\n"
        + test_result.stderr
    ).lower()

    referenced_paths = []

    for replacement in proposed_files:
        file_path = (
            replacement.file_path
        )

        file_name = (
            file_path
            .replace("\\", "/")
            .rsplit("/", 1)[-1]
        )

        if (
            file_path.lower()
            in test_output
            or file_name.lower()
            in test_output
        ):
            referenced_paths.append(
                file_path
            )

    return referenced_paths

def build_test_failure_revision_input(
    project: ProjectContext,
    workers: list[dict],
    current_analysis: IssueAnalysis,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
    test_result: RepositoryTestResult,
) -> str:
    preferred_paths = [
        *current_analysis.likely_files,
        *[
            replacement.file_path
            for replacement
            in proposed_files
        ],
    ]

    repository_context = (
        build_repository_context(
            project.files,
            query_text=(
                project.issue
                + "\n"
                + current_analysis.summary
                + "\n"
                + test_result.stdout
                + "\n"
                + test_result.stderr
            ),
            preferred_paths=preferred_paths,
        )
    )

    available_workers = (
        build_available_workers_section(
            workers
        )
    )
    proposed_file_ownership = (
        build_proposed_file_ownership_section(
            worker_results,
            proposed_files,
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
The current Contrigent candidate failed deterministic repository testing.

First classify the failure using the supplied evidence. Use one of these conceptual
categories:

1. candidate_implementation_defect
   The proposed implementation itself is incorrect.

2. test_or_fixture_defect
   A proposed test, fixture, test-data file, or test expectation is incorrect,
   malformed, or insufficient.

3. environment_or_configuration_defect
   The candidate or repository setup has an actionable dependency, packaging,
   configuration, build, or runtime problem.

4. original_issue_failure
   The candidate executes successfully enough to reach the reported behavior,
   but the proposed solution still does not satisfy the original issue.

5. insufficient_evidence
   A supported correction cannot be identified because genuinely necessary
   information is missing from the issue, repository, worker results, candidate,
   or deterministic test evidence.

A failed candidate is not automatically `needs_clarification`.

If deterministic testing identifies an actionable defect in a file proposed by
Contrigent, use PROPOSED FILE OWNERSHIP to understand which worker produced that file.
Assign that worker again when appropriate, or another available specialist when its
capabilities are a better match for the required correction.

This applies generally to source code, tests, fixtures, configuration, packaging,
database changes, frontend code, documentation, and other candidate files.

Preserve parts of the candidate that are not contradicted by the execution evidence.

Do not restart unrelated implementation work merely because another candidate file
failed.

Do not weaken, remove, or bypass a valid failing test merely to make the suite pass.

Use `needs_clarification` only when genuinely missing information is required before a
supported correction can be identified.

If a supported correction can be attempted from the supplied evidence:

- keep `feasibility` as `feasible`
- create at least one worker assignment
- make each assignment describe the concrete remediation
- use dependencies only when the later worker actually requires revised output from
  an earlier worker

A failed candidate must not be returned as `feasible` with no worker assignments.

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

=== PROPOSED FILE OWNERSHIP ===
{proposed_file_ownership}

=== CURRENT COMBINED PROPOSED FILES ===
{proposed_files_text}

=== ACTUAL DOCKER TEST RESULT ===
{test_result.model_dump_json(indent=2)}

=== REPOSITORY CONTEXT ===
{repository_context}
""".strip()

def build_test_failure_reconsideration_input(
    original_input: str,
    previous_analysis: IssueAnalysis,
    referenced_proposed_paths: list[str],
) -> str:
    referenced_files = "\n".join(
        f"- {path}"
        for path
        in referenced_proposed_paths
    )

    return f"""
{original_input}

=== REMEDIATION DECISION RECONSIDERATION ===
Your previous remediation decision would stop automatic development without producing
a new candidate.

However, deterministic test output explicitly references one or more files that are
part of the current Contrigent candidate:

{referenced_files}

This does not prove that a repair is possible, and you must not invent one.

Re-evaluate the failure once.

Determine whether the supplied repository evidence, worker results, proposed file
contents, file ownership, and deterministic test output provide enough information for
an appropriate worker to attempt a concrete correction.

If they do:

- return `feasible`
- assign the appropriate worker or workers
- describe the concrete remediation task
- preserve unaffected candidate work

If genuinely necessary information is still missing:

- return `needs_clarification`
- identify exactly what information is missing
- explain why the referenced candidate failure cannot be corrected from the supplied
  evidence

Do not return `needs_clarification` merely because the current candidate failed.

=== PREVIOUS REMEDIATION DECISION ===
{previous_analysis.model_dump_json(indent=2)}
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

    analysis = result.final_output

    validate_worker_assignments(
        analysis.worker_assignments,
        workers,
    )

    referenced_proposed_paths = (
        find_test_referenced_proposed_paths(
            proposed_files,
            test_result,
        )
    )

    should_reconsider = (
        bool(
            referenced_proposed_paths
        )
        and (
            analysis.feasibility
            == Feasibility.NEEDS_CLARIFICATION
            or (
                analysis.feasibility
                == Feasibility.FEASIBLE
                and not analysis.worker_assignments
            )
        )
    )

    if not should_reconsider:
        return (
            analysis,
            result.context_wrapper.usage,
        )

    reconsideration_input = (
        build_test_failure_reconsideration_input(
            agent_input,
            analysis,
            referenced_proposed_paths,
        )
    )

    reconsideration_result = (
        await Runner.run(
            issue_analyzer,
            build_input_with_issue_images(
                reconsideration_input,
                project,
            ),
            max_turns=3,
        )
    )

    if not isinstance(
        reconsideration_result.final_output,
        IssueAnalysis,
    ):
        raise TypeError(
            "Issue Analyzer returned an "
            "unexpected output type."
        )

    reconsidered_analysis = (
        reconsideration_result.final_output
    )

    validate_worker_assignments(
        reconsidered_analysis.worker_assignments,
        workers,
    )

    return (
        reconsidered_analysis,
        (
            reconsideration_result
            .context_wrapper
            .usage
        ),
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