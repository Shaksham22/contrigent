from agents import Runner
from pathlib import PurePosixPath
from uuid import UUID

from contrigent_api.services.agent_model_config import (
    configure_agent_for_run_invocation,
)

from contrigent_api.services.repository_context_builder import (
    MAX_REPOSITORY_CONTEXT_CHARS,
    build_repository_context,
)

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)
from contrigent_api.agents.issue_analyzer.agent import (
    AGENT_ID as ISSUE_ANALYZER_AGENT_ID,
    issue_analyzer,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
    IssueAnalysis,
    WorkerAssignment,
    validate_worker_assignment_file_ownership,
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


MAX_CONTEXT_EXPANSION_ROUNDS = 2
MAX_REQUESTED_PATHS_PER_ROUND = 10
MAX_SEARCH_TERMS_PER_ROUND = 10
MAX_SEARCH_MATCHES_PER_TERM = 5
MAX_CONTEXT_SEARCH_TERM_LENGTH = 100
MAX_ADDITIONAL_CONTEXT_CHARS = (
    MAX_REPOSITORY_CONTEXT_CHARS
)


def normalize_context_request_path(
    file_path: str,
) -> str:
    clean_path = file_path.strip()

    if not clean_path:
        raise ValueError(
            "Repository context request paths cannot be blank."
        )

    path = PurePosixPath(clean_path)

    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() == "."
    ):
        raise ValueError(
            "Repository context request paths must be safe "
            f"repository-relative paths: {file_path}"
        )

    return path.as_posix()


def normalize_context_search_terms(
    search_terms: list[str],
) -> tuple[list[str], list[str]]:
    normalized_terms: list[str] = []
    unavailable: list[str] = []
    seen_terms: set[str] = set()

    for raw_term in search_terms:
        term = raw_term.strip()

        if not term:
            unavailable.append(
                "Blank repository search term was rejected."
            )
            continue

        normalized_key = term.casefold()

        if normalized_key in seen_terms:
            continue

        seen_terms.add(normalized_key)

        if len(term) > MAX_CONTEXT_SEARCH_TERM_LENGTH:
            unavailable.append(
                "Repository search term exceeds the "
                f"{MAX_CONTEXT_SEARCH_TERM_LENGTH}-character "
                f"limit: {term!r}."
            )
            continue

        if (
            len(normalized_terms)
            >= MAX_SEARCH_TERMS_PER_ROUND
        ):
            unavailable.append(
                "Repository search term was not used because "
                "the per-round limit was reached: "
                f"{term!r}."
            )
            continue

        normalized_terms.append(term)

    return normalized_terms, unavailable


def search_repository_files(
    project_files: dict[str, str],
    search_terms: list[str],
    *,
    excluded_paths: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    excluded = excluded_paths or set()
    matched_paths: list[str] = []
    seen_paths = set(excluded)
    unavailable: list[str] = []

    for term in search_terms:
        normalized_term = term.casefold()
        candidates: list[
            tuple[str, bool, int]
        ] = []

        for file_path, content in project_files.items():
            path_match = (
                normalized_term
                in file_path.casefold()
            )
            content_matches = (
                content.casefold().count(
                    normalized_term
                )
            )

            if path_match or content_matches:
                candidates.append(
                    (
                        file_path,
                        path_match,
                        content_matches,
                    )
                )

        candidates.sort(
            key=lambda candidate: (
                -int(candidate[1]),
                -candidate[2],
                len(candidate[0]),
                candidate[0],
            )
        )

        term_matches = 0

        for file_path, _, _ in candidates:
            if file_path in seen_paths:
                continue

            matched_paths.append(file_path)
            seen_paths.add(file_path)
            term_matches += 1

            if (
                term_matches
                >= MAX_SEARCH_MATCHES_PER_TERM
            ):
                break

        if term_matches == 0:
            unavailable.append(
                "Repository search produced no new file "
                f"matches for: {term!r}."
            )

    return matched_paths, unavailable


def _additional_context_section(
    file_path: str,
    content: str,
) -> str:
    return (
        f"--- FILE: {file_path} ---\n"
        f"{content}"
    )


def resolve_repository_context_requests(
    project_files: dict[str, str],
    analysis: IssueAnalysis,
    accumulated_paths: list[str],
) -> tuple[list[str], list[str]]:
    resolved_paths: list[str] = []
    unavailable: list[str] = []
    seen_requested_paths: set[str] = set()

    for raw_path in analysis.context_request_paths:
        try:
            file_path = normalize_context_request_path(
                raw_path
            )
        except ValueError as error:
            unavailable.append(str(error))
            continue

        if file_path in seen_requested_paths:
            continue

        seen_requested_paths.add(file_path)

        if (
            len(seen_requested_paths)
            > MAX_REQUESTED_PATHS_PER_ROUND
        ):
            unavailable.append(
                "Repository path was not used because the "
                "per-round request limit was reached: "
                f"{file_path!r}."
            )
            continue

        if file_path not in project_files:
            unavailable.append(
                "Requested repository path is not present "
                f"in project.files: {file_path!r}."
            )
            continue

        if file_path not in accumulated_paths:
            resolved_paths.append(file_path)

    search_terms, term_errors = (
        normalize_context_search_terms(
            analysis.context_search_terms
        )
    )
    unavailable.extend(term_errors)

    search_paths, search_errors = (
        search_repository_files(
            project_files,
            search_terms,
            excluded_paths={
                *accumulated_paths,
                *resolved_paths,
            },
        )
    )
    unavailable.extend(search_errors)
    resolved_paths.extend(search_paths)

    used_chars = sum(
        len(
            _additional_context_section(
                file_path,
                project_files[file_path],
            )
        )
        for file_path in accumulated_paths
    )
    bounded_paths: list[str] = []

    for file_path in resolved_paths:
        section_size = len(
            _additional_context_section(
                file_path,
                project_files[file_path],
            )
        )

        if (
            used_chars + section_size
            > MAX_ADDITIONAL_CONTEXT_CHARS
        ):
            unavailable.append(
                "Requested repository file was not supplied "
                "because the accumulated additional-context "
                f"budget was reached: {file_path!r}."
            )
            continue

        bounded_paths.append(file_path)
        used_chars += section_size

    return bounded_paths, unavailable


def build_expanded_analysis_input(
    initial_input: str,
    project: ProjectContext,
    previous_analysis: IssueAnalysis,
    accumulated_paths: list[str],
    unavailable_requests: list[str],
) -> str:
    if accumulated_paths:
        additional_context = "\n\n".join(
            _additional_context_section(
                file_path,
                project.files[file_path],
            )
            for file_path in accumulated_paths
        )
    else:
        additional_context = (
            "No additional repository files were resolved."
        )

    if unavailable_requests:
        unavailable_text = "\n".join(
            f"- {message}"
            for message in unavailable_requests
        )
    else:
        unavailable_text = "None."

    return f"""
=== ORIGINAL BOUNDED MANAGER INPUT ===
{initial_input}

=== PREVIOUS MANAGER ANALYSIS ===
{previous_analysis.model_dump_json(indent=2)}

=== ADDITIONAL REQUESTED REPOSITORY CONTEXT ===
{additional_context}

=== UNSATISFIED REPOSITORY CONTEXT REQUESTS ===
{unavailable_text}

This additional context was supplied because your previous analysis requested it.
Re-evaluate the issue using both the original context and this additional repository
evidence. Return another targeted context request only if specific additional
repository evidence is still necessary. Otherwise return the final analysis with
empty context-request lists.
""".strip()


def finalize_unresolved_context_request(
    analysis: IssueAnalysis,
    reason: str,
    unavailable_requests: list[str],
) -> IssueAnalysis:
    details = [reason, *unavailable_requests]
    detail_text = " ".join(details)

    return analysis.model_copy(
        update={
            "summary": (
                "Solution not found: Contrigent could not "
                "obtain sufficient repository evidence "
                "within bounded context expansion. "
                f"{detail_text}"
            ),
            "ambiguities": [
                *analysis.ambiguities,
                *details,
            ],
            "feasibility": Feasibility.NEEDS_CLARIFICATION,
            "context_request_paths": [],
            "context_search_terms": [],
            "worker_assignments": [],
            "implementation_plan": [],
        }
    )


async def _invoke_issue_analyzer(
    agent_input: str,
    project: ProjectContext,
    run_id: UUID,
):
    runner_input = build_input_with_issue_images(
        agent_input,
        project,
    )
    configured_agent = (
        configure_agent_for_run_invocation(
            ISSUE_ANALYZER_AGENT_ID,
            issue_analyzer,
            run_id,
        )
    )
    result = await Runner.run(
        configured_agent,
        runner_input,
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

    return (
        result.final_output,
        result.context_wrapper.usage,
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

    validate_worker_assignment_file_ownership(
        worker_assignments
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
    *,
    run_id: UUID,
):
    workers = discover_workers()

    initial_input = build_analysis_input(
        project,
        workers,
    )

    analysis, usage = await _invoke_issue_analyzer(
        initial_input,
        project,
        run_id,
    )
    expansion_rounds = 0
    accumulated_paths: list[str] = []
    unavailable_requests: list[str] = []

    while (
        analysis.context_request_paths
        or analysis.context_search_terms
    ):
        if (
            expansion_rounds
            >= MAX_CONTEXT_EXPANSION_ROUNDS
        ):
            analysis = finalize_unresolved_context_request(
                analysis,
                (
                    "The maximum of "
                    f"{MAX_CONTEXT_EXPANSION_ROUNDS} "
                    "repository context expansion rounds "
                    "was exhausted."
                ),
                unavailable_requests,
            )
            break

        new_paths, resolution_errors = (
            resolve_repository_context_requests(
                project.files,
                analysis,
                accumulated_paths,
            )
        )
        unavailable_requests.extend(
            resolution_errors
        )

        if not new_paths:
            analysis = finalize_unresolved_context_request(
                analysis,
                (
                    "The latest context request resolved "
                    "to zero new usable repository files."
                ),
                unavailable_requests,
            )
            break

        accumulated_paths.extend(new_paths)
        expansion_rounds += 1
        expanded_input = build_expanded_analysis_input(
            initial_input,
            project,
            analysis,
            accumulated_paths,
            unavailable_requests,
        )
        analysis, usage = await _invoke_issue_analyzer(
            expanded_input,
            project,
            run_id,
        )

    validate_worker_assignments(
        analysis.worker_assignments,
        workers,
    )

    return (
        analysis,
        usage,
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
    *,
    run_id: UUID,
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

    runner_input = build_input_with_issue_images(
        agent_input,
        project,
    )
    configured_agent = (
        configure_agent_for_run_invocation(
            ISSUE_ANALYZER_AGENT_ID,
            issue_analyzer,
            run_id,
        )
    )
    result = await Runner.run(
        configured_agent,
        runner_input,
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
    *,
    run_id: UUID,
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

    runner_input = build_input_with_issue_images(
        agent_input,
        project,
    )
    configured_agent = (
        configure_agent_for_run_invocation(
            ISSUE_ANALYZER_AGENT_ID,
            issue_analyzer,
            run_id,
        )
    )
    result = await Runner.run(
        configured_agent,
        runner_input,
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

    reconsideration_runner_input = (
        build_input_with_issue_images(
            reconsideration_input,
            project,
        )
    )
    reconsideration_agent = (
        configure_agent_for_run_invocation(
            ISSUE_ANALYZER_AGENT_ID,
            issue_analyzer,
            run_id,
        )
    )
    reconsideration_result = (
        await Runner.run(
            reconsideration_agent,
            reconsideration_runner_input,
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
    *,
    run_id: UUID,
):
    project = load_sample_project(
        project_name
    )

    return await analyze_project(
        project,
        run_id=run_id,
    )
