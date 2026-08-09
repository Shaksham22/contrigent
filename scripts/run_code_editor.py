import asyncio
import json

from dotenv import load_dotenv

from contrigent_api.services.code_editor_runner import edit_sample_project
from contrigent_api.services.issue_analysis_runner import analyze_sample_project
from contrigent_api.services.sample_project_reader import load_sample_project


async def main() -> None:
    load_dotenv()

    sample_project_name = "python-missing-display-name"

    print("\nLoading sample project...")

    sample_project = load_sample_project(
        sample_project_name
    )

    print("Running Issue Analyzer...")

    issue_analysis, _usage = await analyze_sample_project(
        sample_project_name
    )

    print("Running Code Editor...")

    code_edit_result = await edit_sample_project(
        sample_project,
        issue_analysis,
    )

    print("\n=== CODE EDITOR RESULT ===\n")

    print(
        json.dumps(
            code_edit_result.model_dump(mode="json"),
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())