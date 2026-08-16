from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib

from agents import ModelSettings
from openai.types.shared import Reasoning


MODEL_CONFIG_FILE = (
    Path(__file__).resolve().parents[1]
    / "agent_models.toml"
)

ALLOWED_REASONING_EFFORTS = {
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}


@dataclass(frozen=True)
class AgentModelConfig:
    model: str
    reasoning_effort: str | None = None


def load_agent_model_configs(
    config_file: Path = MODEL_CONFIG_FILE,
) -> dict[str, AgentModelConfig]:
    with config_file.open("rb") as file:
        config = tomllib.load(file)

    agents = config.get(
        "agents"
    )

    if not isinstance(
        agents,
        dict,
    ):
        raise ValueError(
            "agent_models.toml is missing "
            "the [agents] section."
        )

    model_configs: dict[
        str,
        AgentModelConfig,
    ] = {}

    for agent_id, entry in agents.items():
        if not isinstance(
            entry,
            dict,
        ):
            raise ValueError(
                (
                    f"Agent '{agent_id}' model "
                    "configuration must be an "
                    "inline table."
                )
            )

        model = entry.get(
            "model"
        )

        if (
            not isinstance(model, str)
            or not model.strip()
        ):
            raise ValueError(
                (
                    f"Agent '{agent_id}' must "
                    "configure a model."
                )
            )

        reasoning_effort = entry.get(
            "reasoning_effort"
        )

        if reasoning_effort is not None:
            if (
                not isinstance(
                    reasoning_effort,
                    str,
                )
                or reasoning_effort
                not in ALLOWED_REASONING_EFFORTS
            ):
                raise ValueError(
                    (
                        f"Agent '{agent_id}' has "
                        "an invalid "
                        "reasoning_effort."
                    )
                )

        model_configs[
            agent_id
        ] = AgentModelConfig(
            model=model.strip(),
            reasoning_effort=(
                reasoning_effort
            ),
        )

    return model_configs


def load_agent_model_config(
    agent_id: str,
    config_file: Path = MODEL_CONFIG_FILE,
) -> AgentModelConfig:
    configs = load_agent_model_configs(
        config_file
    )

    try:
        return configs[
            agent_id
        ]
    except KeyError as error:
        raise ValueError(
            (
                "No model configuration "
                f"exists for agent "
                f"'{agent_id}'."
            )
        ) from error


def build_agent_model_arguments(
    agent_id: str,
    config_file: Path = MODEL_CONFIG_FILE,
) -> dict[str, Any]:
    config = load_agent_model_config(
        agent_id,
        config_file,
    )

    arguments: dict[
        str,
        Any,
    ] = {
        "model": config.model,
    }

    if (
        config.reasoning_effort
        is not None
    ):
        arguments[
            "model_settings"
        ] = ModelSettings(
            reasoning=Reasoning(
                effort=(
                    config.reasoning_effort
                ),
            ),
        )

    return arguments