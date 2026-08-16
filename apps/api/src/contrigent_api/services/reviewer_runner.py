from agents import Runner
from uuid import UUID

from contrigent_api.services.agent_model_config import (
    configure_agent_for_run_invocation,
)
from contrigent_api.services.repository_context_builder import (
    build_repository_context,
)

from contrigent_api.agents.independent_reviewer.agent import (
    AGENT_ID as INDEPENDENT_REVIEWER_AGENT_ID,
    agent as independent_reviewer,
)
from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)
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

from contrigent_api.services.issue_image_input_builder import (
    build_input_with_issue_images,
)
from contrigent_api.services.worker_runner import (
    build_project_with_proposed_files,
)


def build_proposed_files_section(
    proposed_files,
) -> str:
    if not proposed_files:
        return "No files were proposed."

    sections: list[str] = []

    for proposed_file in proposed_files:
        sections.extend(
            [
                "=== PROPOSED FILE START ===",
                f"FILE PATH: {proposed_file.file_path}",
                "",
                "CHANGE REASON METADATA:",
                proposed_file.reason,
                "",
                (
                    "IMPORTANT: The change reason above is metadata. "
                    "It is NOT part of the replacement file content."
                ),
                "",
                "--- REPLACEMENT CONTENT START ---",
                proposed_file.replacement_content,
                "--- REPLACEMENT CONTENT END ---",
                "=== PROPOSED FILE END ===",
                "",
            ]
        )

    return "\n".join(sections)

def build_reviewer_input(
    sample_project: ProjectContext,
    issue_analysis: IssueAnalysis,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
    previous_reviewer_result: ReviewerResult | None = None,
    candidate_test_result: (
        RepositoryTestResult | None
    ) = None,
) -> str:
    worker_file_paths = [
        replacement.file_path
        for result
        in worker_results.values()
        for replacement
        in result.files_to_replace
    ]

    proposed_file_paths = [
        replacement.file_path
        for replacement
        in proposed_files
    ]

    previous_reviewed_files = (
        previous_reviewer_result.files_reviewed
        if previous_reviewer_result
        is not None
        else []
    )

    preferred_paths = [
        *issue_analysis.likely_files,
        *worker_file_paths,
        *proposed_file_paths,
        *previous_reviewed_files,
    ]

    query_parts = [
        sample_project.issue,
        issue_analysis.summary,
        *[
            replacement.reason
            for replacement
            in proposed_files
        ],
    ]

    if previous_reviewer_result is not None:
        query_parts.append(
            previous_reviewer_result.summary
        )

        query_parts.extend(
            finding.description
            for finding
            in previous_reviewer_result.findings
        )

    if candidate_test_result is not None:
        query_parts.extend(
            [
                candidate_test_result.stdout,
                candidate_test_result.stderr,
            ]
        )

    candidate_project = (
        build_project_with_proposed_files(
            sample_project,
            proposed_files,
        )
    )

    repository_context = (
        build_repository_context(
            candidate_project.files,
            query_text="\n".join(
                query_parts
            ),
            preferred_paths=preferred_paths,
        )
    )

    worker_results_text = "\n\n".join(
        f"--- WORKER: {worker_id} ---\n"
        f"{result.model_dump_json(indent=2)}"
        for worker_id, result
        in worker_results.items()
    )

    proposed_files_section = build_proposed_files_section(
        proposed_files
    )

    if not worker_results_text:
        worker_results_text = "No worker results."

    if previous_reviewer_result is None:
        previous_review_text = (
            "No previous review. This is the first review round."
        )
    else:
        previous_review_text = (
            previous_reviewer_result.model_dump_json(
                indent=2
            )
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
=== ORIGINAL GITHUB ISSUE ===
{sample_project.issue}

=== REPOSITORY README ===
{sample_project.readme}

=== REPOSITORY CONTRIBUTING INSTRUCTIONS ===
{sample_project.contributing}

=== APPROVED MANAGER ANALYSIS AND PLAN ===
{issue_analysis.model_dump_json(indent=2)}

=== CURRENT MATERIALIZED CANDIDATE CONTEXT ===
{repository_context}

=== WORKER RESULTS ===
{worker_results_text}

=== COMBINED PROPOSED FILES ===
{proposed_files_section}

=== CANDIDATE DOCKER TEST RESULT ===
{candidate_test_text}

=== PREVIOUS REVIEW CONTEXT — HISTORICAL ===
{previous_review_text}

The CURRENT MATERIALIZED CANDIDATE CONTEXT and COMBINED PROPOSED FILES are
authoritative. Previous review findings describe an earlier candidate state.
Before repeating any previous finding, verify that the concern still exists in the
current materialized candidate. If the current candidate no longer contains the
behavior described by a previous finding, treat that finding as resolved and do not
repeat it. Independently reassess all findings against the original issue and scope.
""".strip()


async def run_reviewer(
    sample_project: ProjectContext,
    issue_analysis: IssueAnalysis,
    worker_results: dict[str, WorkerResult],
    proposed_files: list[FileReplacement],
    previous_reviewer_result: ReviewerResult | None = None,
    candidate_test_result: (
        RepositoryTestResult | None
    ) = None,
    *,
    run_id: UUID,
) -> ReviewerResult:
    reviewer_input = build_reviewer_input(
        sample_project,
        issue_analysis,
        worker_results,
        proposed_files,
        previous_reviewer_result,
        candidate_test_result,
    )
    runner_input = build_input_with_issue_images(
        reviewer_input,
        sample_project,
    )
    configured_agent = (
        configure_agent_for_run_invocation(
            INDEPENDENT_REVIEWER_AGENT_ID,
            independent_reviewer,
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
        ReviewerResult,
    ):
        raise TypeError(
            "Independent Reviewer returned an unexpected output type."
        )

    return result.final_output
