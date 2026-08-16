from pathlib import Path

from agents import Agent

from contrigent_api.services.agent_model_config import (
    build_agent_model_arguments,
)

from .output_schema import WorkerResult


AGENT_ID = "advanced_solver"

AGENT_FOLDER = (
    Path(__file__).resolve().parent
)


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
        read_agent_definition(
            "identity.md"
        ),
        read_agent_definition(
            "job.md"
        ),
        read_agent_definition(
            "rules.md"
        ),
    ]
)


agent = Agent(
    name="Advanced Solver",
    instructions=agent_instructions,
    output_type=WorkerResult,
    **build_agent_model_arguments(
        AGENT_ID
    ),
)
