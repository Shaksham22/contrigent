import asyncio
import json

from dotenv import load_dotenv

from contrigent_api.services.code_edit_output_writer import (
    save_code_edit_output,
)
from contrigent_api.services.code_editor_runner import (
    edit_sample_project,
)
from contrigent_api.services.issue_analysis_runner import (
    analyze_sample_project,
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)


async def main() -> None:
    load_dotenv()

    project_name = "python-missing-display-name"

    print("\n1. Loading sample project...")

    sample_project = load_sample_project(
        project_name
    )

    print("2. Running Issue Analyzer...")

    issue_analysis, _usage = await analyze_sample_project(
        project_name
    )

    print("3. Running Code Editor...")

    code_edit_result = await edit_sample_project(
        sample_project,
        issue_analysis,
    )

    print("4. Saving Code Editor output...")

    output_folder = save_code_edit_output(
        project_name,
        code_edit_result,
    )

    print("\n=== CODE EDITOR RESULT ===\n")

    print(
        json.dumps(
            code_edit_result.model_dump(mode="json"),
            indent=2,
        )
    )

    print(
        f"\nOutput saved to: {output_folder}"
    )


if __name__ == "__main__":
    asyncio.run(main())