from pathlib import Path
import tomllib


BASE_FOLDER = Path(__file__).resolve().parents[1]

WORKERS_FOLDER = (
    BASE_FOLDER
    / "agents"
    / "workers"
)

MODEL_CONFIG_FILE = (
    BASE_FOLDER
    / "agent_models.toml"
)


def load_agent_models() -> dict[str, str]:
    with MODEL_CONFIG_FILE.open("rb") as file:
        config = tomllib.load(file)

    return config.get("agents", {})


def discover_workers() -> list[dict]:
    if not WORKERS_FOLDER.exists():
        return []

    agent_models = load_agent_models()

    workers = []

    for worker_folder in sorted(
        WORKERS_FOLDER.iterdir()
    ):
        if not worker_folder.is_dir():
            continue

        worker_info_file = (
            worker_folder
            / "agent_info.toml"
        )

        if not worker_info_file.exists():
            continue

        with worker_info_file.open("rb") as file:
            worker_info = tomllib.load(file)

        if worker_info.get("agent_type") != "worker":
            continue

        worker_id = worker_info.get("id")

        if not worker_id:
            continue

        if worker_id != worker_folder.name:
            raise ValueError(
                "Worker folder name does not match agent ID: "
                f"folder='{worker_folder.name}', id='{worker_id}'"
            )

        enabled = worker_info.get(
            "enabled",
            False,
        )

        model = agent_models.get(worker_id)

        if enabled and model is None:
            raise ValueError(
                f"Enabled worker has no model configured: {worker_id}"
            )

        workers.append(
            {
                "id": worker_id,
                "name": worker_info.get(
                    "name",
                    worker_id,
                ),
                "description": worker_info.get(
                    "description",
                    "",
                ).strip(),
                "capabilities": worker_info.get(
                    "capabilities",
                    [],
                ),
                "enabled": enabled,
                "model": model,
            }
        )

    return workers