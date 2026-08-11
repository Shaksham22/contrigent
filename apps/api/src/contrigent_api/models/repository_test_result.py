from typing import Literal

from pydantic import BaseModel, Field


class RepositoryTestResult(BaseModel):
    passed: bool

    stage: Literal[
        "dependency_setup",
        "tests",
    ]

    command: list[str] = Field(
        default_factory=list
    )

    exit_code: int | None = None
    timed_out: bool = False

    duration_seconds: float

    stdout: str = ""
    stderr: str = ""