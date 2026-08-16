from pathlib import Path

import pytest

from contrigent_api.services import worker_discovery


@pytest.fixture
def isolated_worker_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    workers_folder = tmp_path / "workers"

    model_config_file = (
        tmp_path / "agent_models.toml"
    )

    model_config_file.write_text(
    """[backend_solver]
models = [{ model = "gpt-backend-test" }]

[frontend_solver]
models = [{ model = "gpt-frontend-test" }]
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        worker_discovery,
        "WORKERS_FOLDER",
        workers_folder,
    )

    monkeypatch.setattr(
        worker_discovery,
        "MODEL_CONFIG_FILE",
        model_config_file,
    )

    return workers_folder, model_config_file


def create_test_worker(
    workers_folder: Path,
    folder_name: str,
    worker_id: str,
    worker_name: str,
    description: str,
    capabilities: list[str],
    enabled: bool = True,
    agent_type: str = "worker",
) -> None:
    worker_folder = (
        workers_folder / folder_name
    )

    worker_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    enabled_value = (
        "true" if enabled else "false"
    )

    capabilities_value = ", ".join(
        f'"{capability}"'
        for capability in capabilities
    )

    worker_info = f'''id = "{worker_id}"
name = "{worker_name}"
agent_type = "{agent_type}"
enabled = {enabled_value}

description = """
{description}
"""

capabilities = [{capabilities_value}]
'''

    (
        worker_folder / "agent_info.toml"
    ).write_text(
        worker_info,
        encoding="utf-8",
    )


def test_returns_empty_list_when_workers_folder_does_not_exist(
    isolated_worker_files: tuple[Path, Path],
) -> None:
    workers_folder, _ = isolated_worker_files

    assert not workers_folder.exists()

    assert worker_discovery.discover_workers() == []


def test_discovers_worker_information_and_model(
    isolated_worker_files: tuple[Path, Path],
) -> None:
    workers_folder, _ = isolated_worker_files

    create_test_worker(
        workers_folder=workers_folder,
        folder_name="backend_solver",
        worker_id="backend_solver",
        worker_name="Backend Solver",
        description=(
            "Handles backend APIs, Python services, "
            "server logic, and integrations."
        ),
        capabilities=[
            "backend",
            "api",
            "python",
        ],
    )

    workers = worker_discovery.discover_workers()

    assert workers == [
        {
            "id": "backend_solver",
            "name": "Backend Solver",
            "description": (
                "Handles backend APIs, Python services, "
                "server logic, and integrations."
            ),
            "capabilities": [
                "backend",
                "api",
                "python",
            ],
            "enabled": True,
            "model": "gpt-backend-test",
        }
    ]


def test_discovers_multiple_workers_in_consistent_order(
    isolated_worker_files: tuple[Path, Path],
) -> None:
    workers_folder, _ = isolated_worker_files

    create_test_worker(
        workers_folder=workers_folder,
        folder_name="frontend_solver",
        worker_id="frontend_solver",
        worker_name="Frontend Solver",
        description="Handles frontend work.",
        capabilities=[
            "frontend",
            "ui",
        ],
    )

    create_test_worker(
        workers_folder=workers_folder,
        folder_name="backend_solver",
        worker_id="backend_solver",
        worker_name="Backend Solver",
        description="Handles backend work.",
        capabilities=[
            "backend",
            "api",
        ],
    )

    workers = worker_discovery.discover_workers()

    assert [
        worker["id"]
        for worker in workers
    ] == [
        "backend_solver",
        "frontend_solver",
    ]


def test_disabled_worker_keeps_disabled_status(
    isolated_worker_files: tuple[Path, Path],
) -> None:
    workers_folder, _ = isolated_worker_files

    create_test_worker(
        workers_folder=workers_folder,
        folder_name="backend_solver",
        worker_id="backend_solver",
        worker_name="Backend Solver",
        description="Handles backend work.",
        capabilities=["backend"],
        enabled=False,
    )

    workers = worker_discovery.discover_workers()

    assert len(workers) == 1
    assert workers[0]["enabled"] is False


def test_folder_without_agent_info_is_ignored(
    isolated_worker_files: tuple[Path, Path],
) -> None:
    workers_folder, _ = isolated_worker_files

    incomplete_worker = (
        workers_folder / "incomplete_worker"
    )

    incomplete_worker.mkdir(
        parents=True
    )

    workers = worker_discovery.discover_workers()

    assert workers == []


def test_non_worker_agent_is_ignored(
    isolated_worker_files: tuple[Path, Path],
) -> None:
    workers_folder, _ = isolated_worker_files

    create_test_worker(
        workers_folder=workers_folder,
        folder_name="not_a_worker",
        worker_id="not_a_worker",
        worker_name="Not A Worker",
        description="Not a worker agent.",
        capabilities=[],
        agent_type="manager",
    )

    workers = worker_discovery.discover_workers()

    assert workers == []
