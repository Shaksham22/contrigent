from pathlib import Path

import pytest

from contrigent_api.models.worker_result import (
    FileReplacement,
)
from contrigent_api.services.approved_file_applier import (
    ApprovedFileApplyError,
    apply_approved_files,
)


def test_applies_approved_file(
    tmp_path: Path,
) -> None:
    repository = (
        tmp_path / "repository"
    )

    source_folder = (
        repository / "src"
    )

    source_folder.mkdir(
        parents=True
    )

    target_file = (
        source_folder / "users.py"
    )

    target_file.write_text(
        "old code\n",
        encoding="utf-8",
    )

    apply_approved_files(
        repository,
        [
            FileReplacement(
                file_path="src/users.py",
                reason="Fix the bug.",
                replacement_content=(
                    "new code\n"
                ),
            )
        ],
    )

    assert target_file.read_text(
        encoding="utf-8"
    ) == "new code\n"


def test_rejects_path_outside_repository(
    tmp_path: Path,
) -> None:
    repository = (
        tmp_path / "repository"
    )

    repository.mkdir()

    with pytest.raises(
        ApprovedFileApplyError,
        match="Unsafe approved file path",
    ):
        apply_approved_files(
            repository,
            [
                FileReplacement(
                    file_path="../../outside.py",
                    reason="Unsafe.",
                    replacement_content="bad",
                )
            ],
        )