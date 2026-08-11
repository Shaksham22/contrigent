from contrigent_api.models.project_context import (
    ProjectContext,
    ProjectSource,
)
from contrigent_api.services.repository_file_reader import (
    read_repository_text_files,
)
from pathlib import Path


SAMPLE_PROJECTS_ROOT = Path(__file__).resolve().parents[5] / "sample_projects"


class SampleProjectNotFoundError(Exception):
    """Raised when a requested sample project does not exist."""





def load_sample_project(name: str) -> ProjectContext:
    sample_projects_root = SAMPLE_PROJECTS_ROOT.resolve()
    sample_project_path = (sample_projects_root / name).resolve()

    # Only allow projects directly inside sample_projects/.
    if sample_project_path.parent != sample_projects_root:
        raise SampleProjectNotFoundError(name)

    if not sample_project_path.is_dir():
        raise SampleProjectNotFoundError(name)

    issue_path = sample_project_path / "github_issue.md"
    repository_path = sample_project_path / "repository"

    readme_path = repository_path / "README.md"
    contributing_path = repository_path / "CONTRIBUTING.md"

    required_files = [
        issue_path,
        readme_path,
        contributing_path,
    ]

    if not all(path.is_file() for path in required_files):
        raise SampleProjectNotFoundError(name)

    issue = issue_path.read_text(
        encoding="utf-8"
    )

    readme = readme_path.read_text(
        encoding="utf-8"
    )

    contributing = contributing_path.read_text(
        encoding="utf-8"
    )

    files = read_repository_text_files(
        repository_path
    )

    return ProjectContext(
        project_name=name,
        project_source=ProjectSource.SAMPLE,
        repository_path=repository_path,
        issue=issue,
        readme=readme,
        contributing=contributing,
        files=files,
    )