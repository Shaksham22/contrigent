import pytest
from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
from contrigent_api.services.worker_runner import (
    remove_unchanged_replacements,
    validate_replacement_path,
)


from contrigent_api.services.worker_runner import (
    build_worker_input,
    get_available_worker,
)


def test_python_solver_is_available() -> None:
    worker = get_available_worker(
        "python_solver"
    )

    assert worker["id"] == "python_solver"
    assert worker["enabled"] is True


def test_unknown_worker_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="Worker is not available",
    ):
        get_available_worker(
            "made_up_solver"
        )


def test_unsafe_replacement_path_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="unsafe replacement path",
    ):
        validate_replacement_path(
            "../../outside.py"
        )


def test_unchanged_replacement_is_removed() -> None:
    sample_project = load_sample_project(
        "python-missing-display-name"
    )

    original_content = sample_project.files[
        "tests/test_users.py"
    ]

    worker_result = WorkerResult(
        summary="No test changes needed.",
        findings=[
            "Existing tests already cover the behavior."
        ],
        files_to_replace=[
            FileReplacement(
                file_path="tests/test_users.py",
                reason="No changes required.",
                replacement_content=original_content,
            )
        ],
    )

    cleaned_result = remove_unchanged_replacements(
        worker_result,
        sample_project,
    )

    assert cleaned_result.files_to_replace == []
