from agents import Runner

from contrigent_api.agents.issue_analyzer.agent import issue_analyzer
from contrigent_api.agents.issue_analyzer.output_schema import IssueAnalysis
from contrigent_api.services.sample_project_reader import (
    SampleProjectContext,
    load_sample_project,
)


def build_analysis_input(
    sample_project: SampleProjectContext,
) -> str:
    repository_files = "\n\n".join(
        f"--- FILE: {path} ---\n{content}"
        for path, content in sample_project.files.items()
    )

    return f"""
=== GITHUB ISSUE ===
{sample_project.issue}

=== README ===
{sample_project.readme}

=== CONTRIBUTING INSTRUCTIONS ===
{sample_project.contributing}

=== REPOSITORY FILES ===
{repository_files}
""".strip()


async def analyze_sample_project(name: str):
    sample_project = load_sample_project(name)

    agent_input = build_analysis_input(
        sample_project
    )

    result = await Runner.run(
        issue_analyzer,
        agent_input,
        max_turns=3,
    )

    if not isinstance(
        result.final_output,
        IssueAnalysis,
    ):
        raise TypeError(
            "Issue Analyzer returned an unexpected output type."
        )

    return (
        result.final_output,
        result.context_wrapper.usage,
    )