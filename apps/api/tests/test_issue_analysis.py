from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
import pytest

from contrigent_api.services.issue_analysis_runner import (
    build_analysis_input,
    validate_worker_assignments,
)
from contrigent_api.agents.issue_analyzer.output_schema import (
    WorkerAssignment,
)

def test_build_analysis_input_contains_repository_context() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    agent_input = build_analysis_input(
        sample_project,
        workers=[],
    )

    assert "Handle users without a display name" in agent_input
    assert "All behavioral changes must include automated tests" in agent_input
    assert "src/users.py" in agent_input
    assert "display_name.upper()" in agent_input
    
def test_unavailable_required_worker_is_rejected() -> None:
    workers = [
        {
            "id": "backend_solver",
            "enabled": True,
        }
    ]

    with pytest.raises(
        ValueError,
        match="unavailable workers",
    ):
        validate_worker_assignments(
            [
                WorkerAssignment(
                    order=1,
                    worker_id="made_up_solver",
                    task="Fix the backend bug.",
                    depends_on=[],
                )
            ],
            workers,
        )

def test_build_analysis_input_contains_available_workers() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    workers = [
        {
            "id": "backend_solver",
            "name": "Backend Solver",
            "description": "Handles backend Python work.",
            "capabilities": [
                "backend",
                "python",
                "api",
            ],
            "enabled": True,
            "model": "gpt-test",
        },
        {
            "id": "disabled_solver",
            "name": "Disabled Solver",
            "description": "Should not be available.",
            "capabilities": ["testing"],
            "enabled": False,
            "model": "gpt-test",
        },
    ]

    agent_input = build_analysis_input(
        sample_project,
        workers,
    )

    assert "=== AVAILABLE WORKERS ===" in agent_input
    assert "backend_solver" in agent_input
    assert "Backend Solver" in agent_input
    assert "Handles backend Python work." in agent_input
    assert "backend, python, api" in agent_input

    assert "disabled_solver" not in agent_input