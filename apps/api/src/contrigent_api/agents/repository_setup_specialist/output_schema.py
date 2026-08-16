from pydantic import BaseModel, Field


class RepositorySetupProposal(BaseModel):
    python_version: str
    dependency_setup_commands: list[
        list[str]
    ] = Field(
        min_length=1,
        max_length=8,
    )
    test_command: list[str] = Field(
        min_length=1,
        max_length=32,
    )
    evidence: list[str] = Field(
        min_length=1,
        max_length=12,
    )
