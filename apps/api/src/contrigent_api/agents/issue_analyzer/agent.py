from pathlib import Path
import tomllib

from agents import Agent

from .output_schema import IssueAnalysis


AGENT_FOLDER = Path(__file__).resolve().parent
CONFIG_FILE = AGENT_FOLDER.parents[1] / "agent_models.toml"


def read_agent_definition(filename: str) -> str:
    return (AGENT_FOLDER / filename).read_text(
        encoding="utf-8"
    )


def get_assigned_model(agent_name: str) -> str:
    with CONFIG_FILE.open("rb") as file:
        config = tomllib.load(file)

    return config["agents"][agent_name]


agent_instructions = "\n\n".join(
    [
        read_agent_definition("identity.md"),
        read_agent_definition("job.md"),
        read_agent_definition("rules.md"),
    ]
)


issue_analyzer = Agent(
    name="Issue Analyzer",
    instructions=agent_instructions,
    model=get_assigned_model("issue_analyzer"),
    output_type=IssueAnalysis,
)