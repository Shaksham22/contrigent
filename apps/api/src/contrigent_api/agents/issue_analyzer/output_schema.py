from enum import Enum
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator


def normalize_worker_assignment_file_path(
    file_path: str,
) -> str:
    clean_path = file_path.strip()

    if not clean_path:
        raise ValueError(
            "Worker assignment file paths cannot be blank."
        )

    path = PurePosixPath(clean_path)

    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() == "."
    ):
        raise ValueError(
            "Worker assignment file paths must be safe "
            f"repository-relative paths: {file_path}"
        )

    return path.as_posix()


class WorkerAssignment(BaseModel):
    order: int = Field(ge=1)
    worker_id: str
    task: str
    files: list[str] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("files")
    @classmethod
    def validate_files(
        cls,
        files: list[str],
    ) -> list[str]:
        normalized_files = [
            normalize_worker_assignment_file_path(
                file_path
            )
            for file_path in files
        ]

        if len(normalized_files) != len(
            set(normalized_files)
        ):
            raise ValueError(
                "A worker assignment cannot list the "
                "same file more than once."
            )

        return normalized_files


def validate_worker_assignment_file_ownership(
    assignments: list[WorkerAssignment],
) -> None:
    owners_by_path: dict[str, str] = {}

    for assignment in assignments:
        for file_path in assignment.files:
            safe_path = (
                normalize_worker_assignment_file_path(
                    file_path
                )
            )
            existing_owner = owners_by_path.get(
                safe_path
            )

            if existing_owner is not None:
                raise ValueError(
                    "Worker assignments give file "
                    f"'{safe_path}' to multiple workers "
                    "in the same execution cycle: "
                    f"'{existing_owner}' and "
                    f"'{assignment.worker_id}'."
                )

            owners_by_path[safe_path] = (
                assignment.worker_id
            )


class Feasibility(str, Enum):
    FEASIBLE = "feasible"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSAFE = "unsafe"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Risk(BaseModel):
    category: str
    description: str
    severity: RiskSeverity


class ImplementationStep(BaseModel):
    order: int = Field(ge=1)
    description: str


class IssueAnalysis(BaseModel):
    summary: str
    acceptance_criteria: list[str]
    ambiguities: list[str]
    repository_instructions: list[str]
    likely_files: list[str]
    risks: list[Risk]
    feasibility: Feasibility

    context_request_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Repository-relative files requested for "
            "additional bounded analysis context."
        ),
    )
    context_search_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Repository symbols or concepts requested for "
            "deterministic bounded search."
        ),
    )

    worker_assignments: list[WorkerAssignment] = Field(
        description=(
            "Specific work assigned to available worker agents."
        )
    )

    implementation_plan: list[ImplementationStep]
