from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib
from uuid import UUID

from agents import Agent, ModelSettings
from openai.types.shared import Reasoning

from contrigent_api.services.run_memory_store import (
    get_agent_invocation_count,
    record_agent_invocation,
)


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

MODEL_ENTRY_KEYS = {
    "model",
    "reasoning_effort",
}


@dataclass(frozen=True)
class AgentModelConfig:
    model: str
    reasoning_effort: str | None = None


AgentModelLadder = tuple[
    AgentModelConfig,
    ...,
]


def load_agent_model_configs(
    config_file: Path = MODEL_CONFIG_FILE,
) -> dict[str, AgentModelLadder]:
    with config_file.open("rb") as file:
        config = tomllib.load(file)

    model_ladders: dict[
        str,
        AgentModelLadder,
    ] = {}

    for agent_id, section in config.items():
        if (
            not isinstance(agent_id, str)
            or not agent_id.strip()
            or not isinstance(section, dict)
        ):
            raise ValueError(
                "Each agent model configuration must "
                "be a named TOML section."
            )

        unexpected_section_keys = (
            set(section) - {"models"}
        )

        if unexpected_section_keys:
            raise ValueError(
                f"Agent '{agent_id}' has unsupported "
                "configuration fields: "
                + ", ".join(
                    sorted(unexpected_section_keys)
                )
            )

        models = section.get("models")

        if not isinstance(models, list):
            raise ValueError(
                f"Agent '{agent_id}' must contain "
                "a models list."
            )

        if not models:
            raise ValueError(
                f"Agent '{agent_id}' must configure "
                "at least one model."
            )

        parsed_models: list[
            AgentModelConfig
        ] = []

        for index, entry in enumerate(
            models,
            start=1,
        ):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Agent '{agent_id}' model entry "
                    f"{index} must be an inline table."
                )

            unexpected_entry_keys = (
                set(entry) - MODEL_ENTRY_KEYS
            )

            if unexpected_entry_keys:
                raise ValueError(
                    f"Agent '{agent_id}' model entry "
                    f"{index} has unsupported fields: "
                    + ", ".join(
                        sorted(unexpected_entry_keys)
                    )
                )

            model = entry.get("model")

            if (
                not isinstance(model, str)
                or not model.strip()
            ):
                raise ValueError(
                    f"Agent '{agent_id}' model entry "
                    f"{index} must configure a model."
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
                        f"Agent '{agent_id}' model entry "
                        f"{index} has an invalid "
                        "reasoning_effort."
                    )

            parsed_models.append(
                AgentModelConfig(
                    model=model.strip(),
                    reasoning_effort=(
                        reasoning_effort
                    ),
                )
            )

        model_ladders[agent_id] = tuple(
            parsed_models
        )

    return model_ladders


def get_agent_model_config(
    agent_id: str,
    invocation_number: int,
    config_file: Path = MODEL_CONFIG_FILE,
) -> AgentModelConfig:
    if invocation_number < 1:
        raise ValueError(
            "Agent invocation number must be at least 1."
        )

    ladders = load_agent_model_configs(
        config_file
    )

    try:
        ladder = ladders[agent_id]
    except KeyError as error:
        raise ValueError(
            "No model configuration exists for "
            f"agent '{agent_id}'."
        ) from error

    index = min(
        invocation_number - 1,
        len(ladder) - 1,
    )

    return ladder[index]


def load_agent_model_config(
    agent_id: str,
    config_file: Path = MODEL_CONFIG_FILE,
) -> AgentModelConfig:
    return get_agent_model_config(
        agent_id,
        1,
        config_file,
    )


def build_agent_model_arguments(
    agent_id: str,
    config_file: Path = MODEL_CONFIG_FILE,
    *,
    invocation_number: int = 1,
) -> dict[str, Any]:
    config = get_agent_model_config(
        agent_id,
        invocation_number,
        config_file,
    )

    model_settings = ModelSettings()

    if config.reasoning_effort is not None:
        model_settings = ModelSettings(
            reasoning=Reasoning(
                effort=config.reasoning_effort,
            ),
        )

    return {
        "model": config.model,
        "model_settings": model_settings,
    }


def configure_agent_for_run_invocation(
    agent_id: str,
    agent: Agent[Any],
    run_id: UUID,
) -> Agent[Any]:
    invocation_number = (
        get_agent_invocation_count(
            run_id,
            agent_id,
        )
        + 1
    )
    arguments = build_agent_model_arguments(
        agent_id,
        invocation_number=invocation_number,
    )
    configured_agent = agent.clone(
        **arguments
    )
    recorded_invocation = record_agent_invocation(
        run_id,
        agent_id,
    )

    if recorded_invocation != invocation_number:
        raise RuntimeError(
            "Agent invocation count changed unexpectedly."
        )

    return configured_agent
