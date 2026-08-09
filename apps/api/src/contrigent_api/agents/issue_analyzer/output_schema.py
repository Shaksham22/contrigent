from enum import Enum

from pydantic import BaseModel, Field


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
    implementation_plan: list[ImplementationStep]