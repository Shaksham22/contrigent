from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4
from pydantic import Field

from pydantic import BaseModel, Field

from contrigent_api.agents.issue_analyzer.output_schema import (
    IssueAnalysis,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)

from contrigent_api.models.project_context import (
    ProjectSource,
)

class RunStatus(str, Enum):
    ANALYZING = "analyzing"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    PLAN_APPROVED = "plan_approved"
    RUNNING_WORKERS = "running_workers"
    WORKERS_COMPLETED = "workers_completed"
    RUNNING_REVIEWER = "running_reviewer"
    AWAITING_FINAL_APPROVAL = "awaiting_final_approval"
    FINAL_APPROVED = "final_approved"
    APPLYING_CHANGES = "applying_changes"
    CHANGES_APPLIED = "changes_applied"
    COMPLETED = "completed"
    FAILED = "failed"

class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_name: str
    project_source: ProjectSource
    status: RunStatus

    analysis: IssueAnalysis | None = None

    plan_approved: bool = False
    plan_approved_at: datetime | None = None

    worker_work_completed: bool = False

    worker_results: dict[
        str,
        WorkerResult,
    ] = Field(
        default_factory=dict
    )

    proposed_files: list[
        FileReplacement
    ] = Field(
        default_factory=list
    )
    reviewer_result: ReviewerResult | None = None
    final_approved: bool = False
    final_approved_at: datetime | None = None
    changes_applied: bool = False
    changes_applied_at: datetime | None = None

    original_branch: str | None = None
    run_branch: str | None = None

    applied_files: list[str] = Field(
        default_factory=list
)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

changes_applied: bool = False
changes_applied_at: datetime | None = None

original_branch: str | None = None
run_branch: str | None = None

applied_files: list[str] = Field(
    default_factory=list
)