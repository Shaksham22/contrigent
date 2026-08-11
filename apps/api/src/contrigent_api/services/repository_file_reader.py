from pathlib import Path


IGNORED_FOLDER_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
}

MAX_TEXT_FILE_BYTES = 200_000


def read_repository_text_files(
    repository_path: Path,
) -> dict[str, str]:
    files: dict[str, str] = {}

    for file_path in sorted(
        repository_path.rglob("*")
    ):
        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(
            repository_path
        )

        if any(
            part in IGNORED_FOLDER_NAMES
            for part in relative_path.parts
        ):
            continue

        if (
            file_path.stat().st_size
            > MAX_TEXT_FILE_BYTES
        ):
            continue

        try:
            content = file_path.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError:
            continue

        files[
            relative_path.as_posix()
        ] = content

    return files