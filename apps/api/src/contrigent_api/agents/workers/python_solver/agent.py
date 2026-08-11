from pathlib import Path
import tomllib

from agents import Agent

from .output_schema import WorkerResult


AGENT_ID = "python_solver"

AGENT_FOLDER = Path(__file__).resolve().parent

MODEL_CONFIG_FILE = (
    AGENT_FOLDER.parents[2]
    / "agent_models.toml"
)


def read_agent_definition(
    filename: str,
) -> str:
    return (
        AGENT_FOLDER / filename
    ).read_text(
        encoding="utf-8"
    )


def get_assigned_model() -> str:
    with MODEL_CONFIG_FILE.open("rb") as file:
        config = tomllib.load(file)

    return config["agents"][AGENT_ID]


agent_instructions = "\n\n".join(
    [
        read_agent_definition("identity.md"),
        read_agent_definition("job.md"),
        read_agent_definition("rules.md"),
    ]
)


agent = Agent(
    name="Python Solver",
    instructions=agent_instructions,
    model=get_assigned_model(),
    output_type=WorkerResult,
)
