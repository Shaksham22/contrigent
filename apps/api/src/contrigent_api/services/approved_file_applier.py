from pathlib import Path, PurePosixPath

from contrigent_api.models.worker_result import (
    FileReplacement,
)


class ApprovedFileApplyError(RuntimeError):
    pass


def get_safe_repository_file_path(
    repository_path: Path,
    file_path: str,
) -> Path:
    clean_path = file_path.strip()

    if not clean_path:
        raise ApprovedFileApplyError(
            "Approved file path cannot be blank."
        )

    relative_path = PurePosixPath(
        clean_path
    )

    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise ApprovedFileApplyError(
            f"Unsafe approved file path: {file_path}"
        )

    repository_root = (
        repository_path.resolve()
    )

    target_file = (
        repository_root.joinpath(
            *relative_path.parts
        ).resolve()
    )

    if not target_file.is_relative_to(
        repository_root
    ):
        raise ApprovedFileApplyError(
            f"Approved file escapes repository: {file_path}"
        )

    return target_file


def apply_approved_files(
    repository_path: Path,
    proposed_files: list[
        FileReplacement
    ],
) -> list[Path]:
    files_to_write: list[
        tuple[Path, str]
    ] = []

    for proposed_file in proposed_files:
        target_file = (
            get_safe_repository_file_path(
                repository_path,
                proposed_file.file_path,
            )
        )

        files_to_write.append(
            (
                target_file,
                proposed_file.replacement_content,
            )
        )

    applied_files = []

    for target_file, content in files_to_write:
        target_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target_file.write_text(
            content,
            encoding="utf-8",
        )

        applied_files.append(
            target_file
        )

    return applied_files