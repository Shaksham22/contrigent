import base64
from pathlib import Path

from contrigent_api.models.project_context import (
    ProjectContext,
)


IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def image_path_to_data_url(
    image_path: Path,
) -> str:
    mime_type = IMAGE_MIME_TYPES.get(
        image_path.suffix.lower()
    )

    if mime_type is None:
        raise ValueError(
            "Unsupported GitHub issue "
            "image type: "
            f"{image_path.name}"
        )

    encoded_image = base64.b64encode(
        image_path.read_bytes()
    ).decode(
        "ascii"
    )

    return (
        f"data:{mime_type};base64,"
        f"{encoded_image}"
    )


def build_input_with_issue_images(
    text_input: str,
    project: ProjectContext,
):
    if not project.issue_images:
        return text_input

    content: list[dict] = [
        {
            "type": "input_text",
            "text": text_input,
        },
        {
            "type": "input_text",
            "text": (
                "=== GITHUB ISSUE IMAGES ===\n"
                "The following images were "
                "attached to the GitHub issue "
                "or its comments. Treat them "
                "as issue evidence and use "
                "them together with the "
                "written discussion."
            ),
        },
    ]

    for image_path in (
        project.issue_images
    ):
        content.extend(
            [
                {
                    "type": "input_text",
                    "text": (
                        "GitHub issue image: "
                        f"{image_path.name}"
                    ),
                },
                {
                    "type": "input_image",
                    "image_url": (
                        image_path_to_data_url(
                            image_path
                        )
                    ),
                    "detail": "high",
                },
            ]
        )

    return [
        {
            "role": "user",
            "content": content,
        }
    ]