from enum import Enum

from pydantic import BaseModel, Field


class ProposedTestNetworkMode(str, Enum):
    NONE = "none"
    SERVICES_ONLY = "services_only"
    INTERNET = "internet"


class RepositoryServiceProposal(BaseModel):
    name: str
    image: str
    command: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    environment_variables: dict[str, str] = Field(
        default_factory=dict,
        max_length=24,
    )
    network_alias: str
    readiness_command: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    startup_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=120,
    )


class RepositorySetupProposal(BaseModel):
    ecosystem: str
    runtime_version: str | None = None
    project_root: str = "."
    dependency_setup_commands: list[
        list[str]
    ] = Field(
        default_factory=list,
        max_length=16,
    )
    background_commands: list[
        list[str]
    ] = Field(
        default_factory=list,
        max_length=8,
    )
    pre_test_commands: list[
        list[str]
    ] = Field(
        default_factory=list,
        max_length=8,
    )
    test_commands: list[
        list[str]
    ] = Field(
        min_length=1,
        max_length=16,
    )
    environment_variables: dict[str, str] = Field(
        default_factory=dict,
        max_length=32,
    )
    test_network_mode: ProposedTestNetworkMode = (
        ProposedTestNetworkMode.NONE
    )
    services: list[RepositoryServiceProposal] = Field(
        default_factory=list,
        max_length=8,
    )
    evidence: list[str] = Field(
        min_length=1,
        max_length=24,
    )
