from pathlib import Path

from contrigent_api.agents.code_editor.output_schema import CodeEditResult


GENERATED_OUTPUTS_ROOT = (
    Path(__file__).resolve().parents[5]
    / "generated_outputs"
)


def save_code_edit_output(
    project_name: str,
    code_edit_result: CodeEditResult,
) -> Path:
    output_folder = GENERATED_OUTPUTS_ROOT / project_name

    replacement_files_folder = (
        output_folder / "replacement_files"
    )

    replacement_files_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    instructions = [
        f"# Code Edit Instructions - {project_name}",
        "",
        code_edit_result.summary,
        "",
        "## Files to Replace",
        "",
    ]

    for file_replacement in code_edit_result.files_to_replace:
        instructions.extend(
            [
                f"### {file_replacement.file_path}",
                "",
                file_replacement.reason,
                "",
            ]
        )

        output_file = (
            replacement_files_folder
            / file_replacement.file_path
        )

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file.write_text(
            file_replacement.replacement_content,
            encoding="utf-8",
        )

    instructions_file = (
        output_folder / "instructions.md"
    )

    instructions_file.write_text(
        "\n".join(instructions),
        encoding="utf-8",
    )

    return output_folder