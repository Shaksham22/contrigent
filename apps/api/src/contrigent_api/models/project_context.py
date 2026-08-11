from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ProjectSource(str, Enum):
    SAMPLE = "sample"
    GITHUB = "github"


@dataclass(frozen=True)
class ProjectContext:
    project_name: str
    project_source: ProjectSource
    repository_path: Path

    issue: str
    readme: str
    contributing: str

    files: dict[str, str]