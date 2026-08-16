from agents import Runner
from uuid import UUID

from contrigent_api.agents.code_editor.agent import (
    AGENT_ID as CODE_EDITOR_AGENT_ID,
    code_editor,
)
from contrigent_api.agents.code_editor.output_schema import CodeEditResult
from contrigent_api.agents.issue_analyzer.output_schema import IssueAnalysis
from contrigent_api.services.agent_model_config import (
    configure_agent_for_run_invocation,
)
from contrigent_api.services.sample_project_reader import SampleProjectContext


def build_code_editor_input(
    sample_project: SampleProjectContext,
    issue_analysis: IssueAnalysis,
) -> str:
    repository_files = "\n\n".join(
        f"--- FILE: {path} ---\n{content}"
        for path, content in sample_project.files.items()
    )

    return f"""
=== ORIGINAL GITHUB ISSUE ===
{sample_project.issue}

=== REPOSITORY README ===
{sample_project.readme}

=== REPOSITORY CONTRIBUTING INSTRUCTIONS ===
{sample_project.contributing}

=== APPROVED ISSUE ANALYSIS ===
{issue_analysis.model_dump_json(indent=2)}

=== REPOSITORY FILES ===
{repository_files}
""".strip()


async def edit_sample_project(
    sample_project: SampleProjectContext,
    issue_analysis: IssueAnalysis,
    *,
    run_id: UUID,
) -> CodeEditResult:
    agent_input = build_code_editor_input(
        sample_project,
        issue_analysis,
    )

    configured_agent = (
        configure_agent_for_run_invocation(
            CODE_EDITOR_AGENT_ID,
            code_editor,
            run_id,
        )
    )
    result = await Runner.run(
        configured_agent,
        agent_input,
        max_turns=3,
    )

    if not isinstance(
        result.final_output,
        CodeEditResult,
    ):
        raise TypeError(
            "Code Editor returned an unexpected output type."
        )

    return result.final_output
