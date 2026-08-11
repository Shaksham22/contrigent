from pathlib import Path

from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.services.github_project_downloader import (
    DOWNLOADED_GITHUB_PROJECTS_FOLDER,
)
from contrigent_api.services.repository_file_reader import (
    read_repository_text_files,
)


class DownloadedGitHubProjectNotFoundError(
    FileNotFoundError
):
    pass


def load_downloaded_github_project(
    project_name: str,
) -> ProjectContext:
    root_folder = (
        DOWNLOADED_GITHUB_PROJECTS_FOLDER.resolve()
    )

    project_folder = (
        root_folder
        / project_name
    ).resolve()

    if not project_folder.is_relative_to(
        root_folder
    ):
        raise DownloadedGitHubProjectNotFoundError(
            "GitHub project path is outside "
            "downloaded_github_projects."
        )

    issue_file = (
        project_folder
        / "github_issue.md"
    )

    repository_folder = (
        project_folder
        / "repository"
    )

    if (
        not issue_file.is_file()
        or not repository_folder.is_dir()
    ):
        raise DownloadedGitHubProjectNotFoundError(
            f"Downloaded GitHub project not found: {project_name}"
        )

    readme_file = (
        repository_folder / "README.md"
    )

    contributing_file = (
        repository_folder
        / "CONTRIBUTING.md"
    )

    issue = issue_file.read_text(
        encoding="utf-8"
    )

    readme = (
        readme_file.read_text(
            encoding="utf-8"
        )
        if readme_file.exists()
        else ""
    )

    contributing = (
        contributing_file.read_text(
            encoding="utf-8"
        )
        if contributing_file.exists()
        else ""
    )

    files = read_repository_text_files(
        repository_folder
    )

    return ProjectContext(
        project_name=project_name,
        project_source=ProjectSource.GITHUB,
        repository_path=repository_folder,
        issue=issue,
        readme=readme,
        contributing=contributing,
        files=files,
    )