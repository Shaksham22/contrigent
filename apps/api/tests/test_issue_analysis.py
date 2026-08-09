from contrigent_api.services.sample_project_reader import load_sample_project
from contrigent_api.services.issue_analysis_runner import build_analysis_input


def test_build_analysis_input_contains_repository_context() -> None:
    sample_project = load_sample_project("python-missing-display-name")

    agent_input = build_analysis_input(sample_project)

    assert "Handle users without a display name" in agent_input
    assert "All behavioral changes must include automated tests" in agent_input
    assert "src/users.py" in agent_input
    assert "display_name.upper()" in agent_input