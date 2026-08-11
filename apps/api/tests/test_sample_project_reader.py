import pytest

from contrigent_api.services.sample_project_reader import (
    SampleProjectNotFoundError,
    load_sample_project,
)


def test_loads_controlled_sample_project() -> None:
    sample_project = load_sample_project("python-missing-display-name")

    assert sample_project.project_name == "python-missing-display-name"
    assert sample_project.project_source.value == "sample"

    assert "Handle users without a display name" in sample_project.issue
    assert "automated tests" in sample_project.contributing

    assert "src/users.py" in sample_project.files
    assert "display_name.upper()" in sample_project.files["src/users.py"]

    assert "tests/test_users.py" in sample_project.files
    assert (
        "test_falls_back_to_username_when_display_name_is_missing"
        in sample_project.files["tests/test_users.py"]
    )


def test_unknown_sample_project_is_rejected() -> None:
    with pytest.raises(SampleProjectNotFoundError):
        load_sample_project("does-not-exist")


def test_path_traversal_is_rejected() -> None:
    with pytest.raises(SampleProjectNotFoundError):
        load_sample_project("../docs")