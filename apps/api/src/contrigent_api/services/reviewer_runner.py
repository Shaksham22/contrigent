from agents import Runner

from contrigent_api.agents.independent_reviewer.agent import (
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
    repository_files = "\n\n".join(
        f"--- ORIGINAL FILE: {path} ---\n{content}"
        for path, content
        in sample_project.files.items()
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

=== ORIGINAL REPOSITORY FILES ===
{repository_files}

=== WORKER RESULTS ===
{worker_results_text}

=== COMBINED PROPOSED FILES ===
{proposed_files_section}

=== CANDIDATE DOCKER TEST RESULT ===
{candidate_test_text}

=== PREVIOUS REVIEW CONTEXT ===
{previous_review_text}

If previous review context is present, use it to verify whether valid concerns
were addressed, but independently reassess those findings against the current
proposal and issue scope. Do not preserve a previous conclusion automatically.
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
) -> ReviewerResult:
    reviewer_input = build_reviewer_input(
        sample_project,
        issue_analysis,
        worker_results,
        proposed_files,
        previous_reviewer_result,
        candidate_test_result,
    )
    result = await Runner.run(
        independent_reviewer,
        reviewer_input,
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