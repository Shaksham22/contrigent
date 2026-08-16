from pathlib import Path

from agents import Agent

from contrigent_api.services.agent_model_config import (
    build_agent_model_arguments,
)

from .output_schema import RepositorySetupProposal


AGENT_ID = "repository_setup_specialist"
AGENT_FOLDER = Path(__file__).resolve().parent


def read_agent_definition(
    filename: str,
) -> str:
    return (
        AGENT_FOLDER / filename
    ).read_text(
        encoding="utf-8"
    )


agent_instructions = "\n\n".join(
    [
        read_agent_definition("identity.md"),
        read_agent_definition("job.md"),
        read_agent_definition("rules.md"),
    ]
)


repository_setup_specialist = Agent(
    name="Repository Setup Specialist",
    instructions=agent_instructions,
    output_type=RepositorySetupProposal,
    **build_agent_model_arguments(
        AGENT_ID
    ),
)
