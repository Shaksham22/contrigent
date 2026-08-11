from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from contrigent_api.agents.issue_analyzer.output_schema import (
    IssueAnalysis,
)
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)


class RunStatus(str, Enum):
    ANALYZING = "analyzing"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    PLAN_APPROVED = "plan_approved"
    RUNNING_WORKERS = "running_workers"
    WORKERS_COMPLETED = "workers_completed"
    COMPLETED = "completed"
    FAILED = "failed"


class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    sample_project_name: str
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

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )