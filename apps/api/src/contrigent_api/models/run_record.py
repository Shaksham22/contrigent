from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from contrigent_api.agents.issue_analyzer.output_schema import IssueAnalysis


class RunStatus(str, Enum):
    ANALYZING = "analyzing"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    PLAN_APPROVED = "plan_approved"
    FAILED = "failed"


class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)

    sample_project_name: str

    status: RunStatus

    analysis: IssueAnalysis | None = None

    plan_approved: bool = False

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    plan_approved_at: datetime | None = None