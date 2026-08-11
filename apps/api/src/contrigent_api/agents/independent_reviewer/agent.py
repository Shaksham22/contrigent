from pathlib import Path
import tomllib

from agents import Agent

from .output_schema import ReviewerResult


AGENT_ID = "independent_reviewer"

AGENT_FOLDER = Path(__file__).resolve().parent


def find_model_config_file() -> Path:
    current_folder = AGENT_FOLDER

    while True:
        candidate = (
            current_folder
            / "agent_models.toml"
        )

        if candidate.exists():
            return candidate

        if current_folder == current_folder.parent:
            break

        current_folder = current_folder.parent

    raise FileNotFoundError(
        "Could not find agent_models.toml."
    )


MODEL_CONFIG_FILE = (
    find_model_config_file()
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
    name="Independent Reviewer",
    instructions=agent_instructions,
    model=get_assigned_model(),
    output_type=ReviewerResult,
)
