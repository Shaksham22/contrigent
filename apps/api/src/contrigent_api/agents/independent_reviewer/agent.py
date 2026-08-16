from pathlib import Path
from agents import Agent
from .output_schema import ReviewerResult


AGENT_ID = "independent_reviewer"

from contrigent_api.services.agent_model_config import (
    build_agent_model_arguments,
)

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


agent = Agent(
    name="Independent Reviewer",
    instructions=agent_instructions,
    **build_agent_model_arguments(
        AGENT_ID
    ),
    output_type=ReviewerResult,
)
