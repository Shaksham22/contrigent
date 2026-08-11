from typing import Literal

from pydantic import BaseModel, Field


class ReviewFinding(BaseModel):
    category: str
    description: str
    severity: Literal[
        "low",
        "medium",
        "high",
    ]


class ReviewerResult(BaseModel):
    recommendation: Literal[
        "approve",
        "changes_required",
    ]

    summary: str

    findings: list[ReviewFinding] = Field(
        default_factory=list
    )

    files_reviewed: list[str] = Field(
        default_factory=list
    )