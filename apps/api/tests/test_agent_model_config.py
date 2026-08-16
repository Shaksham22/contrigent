from pathlib import Path

import pytest

from contrigent_api.services.agent_model_config import (
    build_agent_model_arguments,
    get_agent_model_config,
    load_agent_model_configs,
)


def write_model_config(
    tmp_path: Path,
    content: str,
) -> Path:
    config_file = tmp_path / "agent_models.toml"
    config_file.write_text(
        content,
        encoding="utf-8",
    )
    return config_file


def test_single_model_ladder_reuses_final_model(
    tmp_path: Path,
) -> None:
    config_file = write_model_config(
        tmp_path,
        """[python_solver]
models = [
    { model = "model-a" },
]
""",
    )

    for invocation_number in (1, 2, 10):
        config = get_agent_model_config(
            "python_solver",
            invocation_number,
            config_file,
        )

        assert config.model == "model-a"
        assert config.reasoning_effort is None


def test_multi_model_ladder_escalates_and_holds_final_tier(
    tmp_path: Path,
) -> None:
    config_file = write_model_config(
        tmp_path,
        """[testing_specialist]
models = [
    { model = "model-a" },
    { model = "model-b", reasoning_effort = "high" },
]
""",
    )

    first = get_agent_model_config(
        "testing_specialist",
        1,
        config_file,
    )
    second = get_agent_model_config(
        "testing_specialist",
        2,
        config_file,
    )
    third = get_agent_model_config(
        "testing_specialist",
        3,
        config_file,
    )

    assert first.model == "model-a"
    assert first.reasoning_effort is None
    assert second.model == "model-b"
    assert second.reasoning_effort == "high"
    assert third == second

    arguments = build_agent_model_arguments(
        "testing_specialist",
        config_file,
        invocation_number=2,
    )
    assert arguments["model"] == "model-b"
    assert (
        arguments["model_settings"]
        .reasoning.effort
        == "high"
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            """[python_solver]
""",
            "must contain a models list",
        ),
        (
            """[python_solver]
models = []
""",
            "at least one model",
        ),
        (
            """[python_solver]
model = "model-a"
""",
            "unsupported configuration fields",
        ),
        (
            """[python_solver]
models = ["model-a"]
""",
            "must be an inline table",
        ),
        (
            """[python_solver]
models = [{ model = "" }]
""",
            "must configure a model",
        ),
        (
            """[python_solver]
models = [{ model = "model-a", reasoning_effort = "extreme" }]
""",
            "invalid reasoning_effort",
        ),
        (
            """[python_solver]
models = [{ model = "model-a", temperature = 1 }]
""",
            "unsupported fields",
        ),
    ],
)
def test_malformed_model_ladders_are_rejected(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    config_file = write_model_config(
        tmp_path,
        content,
    )

    with pytest.raises(
        ValueError,
        match=message,
    ):
        load_agent_model_configs(
            config_file
        )


def test_unknown_agent_and_invalid_invocation_are_rejected(
    tmp_path: Path,
) -> None:
    config_file = write_model_config(
        tmp_path,
        """[python_solver]
models = [{ model = "model-a" }]
""",
    )

    with pytest.raises(
        ValueError,
        match="No model configuration",
    ):
        get_agent_model_config(
            "missing_agent",
            1,
            config_file,
        )

    with pytest.raises(
        ValueError,
        match="at least 1",
    ):
        get_agent_model_config(
            "python_solver",
            0,
            config_file,
        )


def test_all_configured_agents_have_nonempty_ladders() -> None:
    configured = load_agent_model_configs()
    expected_agent_ids = {
        "issue_analyzer",
        "code_editor",
        "python_solver",
        "testing_specialist",
        "independent_reviewer",
        "pull_request_documentation_agent",
        "frontend_solver",
        "documentation_specialist",
        "database_solver",
        "configuration_specialist",
        "advanced_solver",
        "repository_setup_specialist",
    }

    assert set(configured) == expected_agent_ids
    assert all(configured.values())


def test_production_python_does_not_hardcode_model_names() -> None:
    source_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "contrigent_api"
    )

    source_files = list(
        source_root.rglob("*.py")
    )
    source_files.append(
        source_root.parents[3]
        / "scripts"
        / "create_agent.py"
    )

    for source_file in source_files:
        source = source_file.read_text(
            encoding="utf-8"
        )
        assert "gpt-5.4-mini" not in source
        assert "gpt-5.6-sol" not in source
