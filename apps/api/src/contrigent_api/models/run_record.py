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

from contrigent_api.agents.independent_reviewer.output_schema import (
    ReviewerResult,
)

from contrigent_api.models.project_context import (
    ProjectSource,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
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
    RUNNING_TESTS = "running_tests"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    COMMITTING = "committing"
    COMMITTED = "committed"
    PUSHING = "pushing"
    PUSHED = "pushed"
    CREATING_DRAFT_PR = "creating_draft_pr"
    COMPLETED = "completed"
    FAILED = "failed"

class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_name: str
    project_source: ProjectSource
    github_issue_url: str | None = None
    github_repository_url: str | None = None
    status: RunStatus

    max_review_rounds: int = Field(
        default=2,
        ge=1,
        le=10,
    )
    max_testing_rounds: int = Field(
        default=2,
        ge=1,
        le=10,
    )

    review_rounds_completed: int = Field(
        default=0,
        ge=0,
    )
    testing_rounds_completed: int = Field(
        default=0,
        ge=0,
    )

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

    candidate_test_result: (
        RepositoryTestResult | None
    ) = None

    final_approved: bool = False
    final_approved_at: datetime | None = None
    changes_applied: bool = False
    changes_applied_at: datetime | None = None

    original_branch: str | None = None
    run_branch: str | None = None

    applied_files: list[str] = Field(
        default_factory=list
)
    repository_tests_completed: bool = False
    repository_tests_passed: bool | None = None

    repository_test_result: (
        RepositoryTestResult | None
    ) = None

    repository_tests_completed_at: (
        datetime | None
    ) = None
    commit_created: bool = False
    commit_sha: str | None = None
    commit_message: str | None = None
    committed_at: datetime | None = None

    branch_pushed: bool = False
    branch_pushed_at: datetime | None = None

    draft_pr_created: bool = False
    draft_pr_number: int | None = None
    draft_pr_url: str | None = None
    draft_pr_created_at: datetime | None = None

    completed_at: datetime | None = None

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )
