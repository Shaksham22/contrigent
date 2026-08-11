from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.services.downloaded_github_project_reader import (
    load_downloaded_github_project,
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)


def load_project(
    project_name: str,
    project_source: ProjectSource,
) -> ProjectContext:
    if project_source == ProjectSource.SAMPLE:
        return load_sample_project(
            project_name
        )

    if project_source == ProjectSource.GITHUB:
        return load_downloaded_github_project(
            project_name
        )

    raise ValueError(
        f"Unsupported project source: {project_source}"
    )