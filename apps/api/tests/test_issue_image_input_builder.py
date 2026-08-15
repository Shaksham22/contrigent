from pathlib import Path

from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.services.issue_image_input_builder import (
    build_input_with_issue_images,
)


def make_project(
    tmp_path: Path,
    issue_images: tuple[Path, ...] = (),
) -> ProjectContext:
    return ProjectContext(
        project_name="demo",
        project_source=ProjectSource.GITHUB,
        repository_path=tmp_path,
        issue="Example issue",
        readme="",
        contributing="",
        files={},
        issue_images=issue_images,
    )


def test_plain_text_input_is_preserved_without_images(
    tmp_path: Path,
) -> None:
    project = make_project(
        tmp_path
    )

    assert (
        build_input_with_issue_images(
            "Analyze this issue.",
            project,
        )
        == "Analyze this issue."
    )


def test_issue_images_are_added_as_multimodal_input(
    tmp_path: Path,
) -> None:
    image_path = (
        tmp_path
        / "001-comment-1.png"
    )

    image_path.write_bytes(
        b"example-image-bytes"
    )

    project = make_project(
        tmp_path,
        issue_images=(
            image_path,
        ),
    )

    agent_input = (
        build_input_with_issue_images(
            "Analyze this issue.",
            project,
        )
    )

    assert isinstance(
        agent_input,
        list,
    )

    content = agent_input[0][
        "content"
    ]

    assert content[0] == {
        "type": "input_text",
        "text": "Analyze this issue.",
    }

    assert (
        "001-comment-1.png"
        in content[2]["text"]
    )

    assert (
        content[3]["type"]
        == "input_image"
    )

    assert (
        content[3]["image_url"]
        .startswith(
            "data:image/png;base64,"
        )
    )

    assert (
        content[3]["detail"]
        == "high"
    )