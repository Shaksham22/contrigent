from dataclasses import dataclass
from pathlib import Path


SAMPLE_PROJECTS_ROOT = Path(__file__).resolve().parents[5] / "sample_projects"


class SampleProjectNotFoundError(Exception):
    """Raised when a requested sample project does not exist."""


@dataclass(frozen=True)
class SampleProjectContext:
    name: str
    issue: str
    readme: str
    contributing: str
    files: dict[str, str]


def load_sample_project(name: str) -> SampleProjectContext:
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

    repository_files: dict[str, str] = {}

    for directory_name in ("src", "tests"):
        directory_path = repository_path / directory_name

        if not directory_path.is_dir():
            continue

        for path in sorted(directory_path.rglob("*")):
            if path.is_file():
                relative_path = path.relative_to(repository_path).as_posix()

                repository_files[relative_path] = path.read_text(
                    encoding="utf-8"
                )

    return SampleProjectContext(
        name=name,
        issue=issue_path.read_text(encoding="utf-8"),
        readme=readme_path.read_text(encoding="utf-8"),
        contributing=contributing_path.read_text(encoding="utf-8"),
        files=repository_files,
    )