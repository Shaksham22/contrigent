from pathlib import Path
import tomllib

import pytest

from scripts import create_agent


EXPECTED_WORKER_FILES = {
    "identity.md",
    "job.md",
    "rules.md",
    "agent_info.toml",
    "output_schema.py",
    "agent.py",
}


@pytest.fixture
def isolated_agent_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    workers_folder = (
        tmp_path
        / "contrigent_api"
        / "agents"
        / "workers"
    )

    model_config_file = (
        tmp_path
        / "contrigent_api"
        / "agent_models.toml"
    )

    model_config_file.parent.mkdir(
        parents=True
    )

    model_config_file.write_text(
        '[agents]\nissue_analyzer = "gpt-test"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        create_agent,
        "WORKERS_FOLDER",
        workers_folder,
    )

    monkeypatch.setattr(
        create_agent,
        "MODEL_CONFIG_FILE",
        model_config_file,
    )

    return workers_folder, model_config_file


@pytest.mark.parametrize(
    "agent_name",
    [
        "Backend Solver",
        "backend solver",
        "BACKEND SOLVER",
        "Backend-Solver",
        "backend_solver",
    ],
)
def test_agent_name_normalizes_consistently(
    agent_name: str,
) -> None:
    assert (
        create_agent.normalize_agent_name(agent_name)
        == "backend_solver"
    )


def test_creates_standard_worker_files_and_model_entry(
    isolated_agent_files: tuple[Path, Path],
) -> None:
    workers_folder, model_config_file = isolated_agent_files

    create_agent.create_worker_agent(
        agent_name="Backend Solver",
        description=(
            "Handles backend APIs, Python services, "
            "server logic, and integrations."
        ),
        model="gpt-worker-test",
    )

    worker_folder = workers_folder / "backend_solver"

    assert worker_folder.is_dir()

    assert {
        path.name
        for path in worker_folder.iterdir()
    } == EXPECTED_WORKER_FILES

    with (
        worker_folder / "agent_info.toml"
    ).open("rb") as file:
        worker_info = tomllib.load(file)

    assert worker_info["id"] == "backend_solver"
    assert worker_info["name"] == "Backend Solver"
    assert worker_info["agent_type"] == "worker"
    assert worker_info["enabled"] is True

    with model_config_file.open("rb") as file:
        model_config = tomllib.load(file)

    assert (
        model_config["agents"]["backend_solver"]
        == "gpt-worker-test"
    )


def test_blank_agent_name_is_rejected(
    isolated_agent_files: tuple[Path, Path],
) -> None:
    with pytest.raises(
        ValueError,
        match="Agent name cannot be blank",
    ):
        create_agent.create_worker_agent(
            agent_name="   ",
            description="Handles backend work.",
            model="gpt-worker-test",
        )


def test_blank_description_is_rejected(
    isolated_agent_files: tuple[Path, Path],
) -> None:
    with pytest.raises(
        ValueError,
        match="description cannot be blank",
    ):
        create_agent.create_worker_agent(
            agent_name="Backend Solver",
            description="   ",
            model="gpt-worker-test",
        )


def test_duplicate_agent_name_is_rejected(
    isolated_agent_files: tuple[Path, Path],
) -> None:
    create_agent.create_worker_agent(
        agent_name="Backend Solver",
        description="Handles backend work.",
        model="gpt-worker-test",
    )

    with pytest.raises(
        ValueError,
        match="already exists",
    ):
        create_agent.create_worker_agent(
            agent_name="BACKEND-SOLVER",
            description="Duplicate backend worker.",
            model="gpt-worker-test",
        )


def test_model_config_duplicate_is_rejected(
    isolated_agent_files: tuple[Path, Path],
) -> None:
    workers_folder, model_config_file = isolated_agent_files

    model_config_file.write_text(
        (
            '[agents]\n'
            'issue_analyzer = "gpt-test"\n'
            'Backend_Solver = "gpt-test"\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="already exists in agent_models.toml",
    ):
        create_agent.create_worker_agent(
            agent_name="backend solver",
            description="Handles backend work.",
            model="gpt-worker-test",
        )

    assert not (
        workers_folder / "backend_solver"
    ).exists()


def test_failed_model_config_update_removes_worker_folder(
    isolated_agent_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workers_folder, model_config_file = isolated_agent_files

    original_config = model_config_file.read_text(
        encoding="utf-8"
    )

    original_replace = Path.replace

    def fail_config_replace(
        path: Path,
        target: Path,
    ) -> Path:
        if path.name == "agent_models.toml.tmp":
            raise OSError(
                "simulated config update failure"
            )

        return original_replace(
            path,
            target,
        )

    monkeypatch.setattr(
        Path,
        "replace",
        fail_config_replace,
    )

    with pytest.raises(
        OSError,
        match="simulated config update failure",
    ):
        create_agent.create_worker_agent(
            agent_name="Backend Solver",
            description="Handles backend work.",
            model="gpt-worker-test",
        )

    assert not (
        workers_folder / "backend_solver"
    ).exists()

    assert (
        model_config_file.read_text(
            encoding="utf-8"
        )
        == original_config
    )

    assert not model_config_file.with_suffix(
        ".toml.tmp"
    ).exists()