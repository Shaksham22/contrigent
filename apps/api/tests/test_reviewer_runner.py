from contrigent_api.models.worker_result import (
    FileReplacement,
)
from contrigent_api.services.reviewer_runner import (
    build_proposed_files_section,
)


def test_proposed_file_content_is_separated_from_reason_metadata() -> None:
    proposed_file = FileReplacement(
        file_path="src/example.py",
        reason="Fix the example bug.",
        replacement_content='"""Example module."""\n\nvalue = 1\n',
    )

    section = build_proposed_files_section(
        [proposed_file]
    )

    assert "CHANGE REASON METADATA:" in section
    assert "Fix the example bug." in section

    assert (
        "--- REPLACEMENT CONTENT START ---\n"
        '"""Example module."""'
    ) in section

    replacement_section = section.split(
        "--- REPLACEMENT CONTENT START ---",
        maxsplit=1,
    )[1].split(
        "--- REPLACEMENT CONTENT END ---",
        maxsplit=1,
    )[0]

    assert '"""Example module."""' in replacement_section
    assert "value = 1" in replacement_section
    assert "Fix the example bug." not in replacement_section
    assert "CHANGE REASON METADATA:" not in replacement_section
    assert (
        "The change reason above is metadata"
        in section
    )