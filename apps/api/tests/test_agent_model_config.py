from pathlib import Path

import pytest

from contrigent_api.services.agent_model_config import (
    build_agent_model_arguments,
    load_agent_model_config,
)


def test_loads_model_without_reasoning(
    tmp_path: Path,
) -> None:
    config_file = (
        tmp_path / "agent_models.toml"
    )

    config_file.write_text(
        """[agents]
python_solver = { model = "gpt-test" }
""",
        encoding="utf-8",
    )

    config = load_agent_model_config(
        "python_solver",
        config_file,
    )

    assert config.model == "gpt-test"

    assert (
        config.reasoning_effort
        is None
    )


def test_builds_high_reasoning_settings(
    tmp_path: Path,
) -> None:
    config_file = (
        tmp_path / "agent_models.toml"
    )

    config_file.write_text(
        """[agents]
issue_analyzer = { model = "gpt-test", reasoning_effort = "high" }
""",
        encoding="utf-8",
    )

    arguments = (
        build_agent_model_arguments(
            "issue_analyzer",
            config_file,
        )
    )

    assert (
        arguments["model"]
        == "gpt-test"
    )

    model_settings = (
        arguments["model_settings"]
    )

    assert (
        model_settings.reasoning
        is not None
    )

    assert (
        model_settings.reasoning.effort
        == "high"
    )


def test_old_string_model_format_is_rejected(
    tmp_path: Path,
) -> None:
    config_file = (
        tmp_path / "agent_models.toml"
    )

    config_file.write_text(
        """[agents]
python_solver = "gpt-test"
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="inline table",
    ):
        load_agent_model_config(
            "python_solver",
            config_file,
        )