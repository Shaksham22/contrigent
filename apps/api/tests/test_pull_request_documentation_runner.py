from contrigent_api.models.worker_result import (
    FileReplacement,
    WorkerResult,
)
from contrigent_api.services.pull_request_documentation_runner import (
    build_worker_results_section,
)


def test_worker_documentation_contains_summary_and_reason() -> None:
    worker_results = {
        "python_solver": WorkerResult(
            summary=(
                "Made order reservation atomic."
            ),
            findings=[
                (
                    "Inventory was previously "
                    "mutated before validation "
                    "completed."
                )
            ],
            files_to_replace=[
                FileReplacement(
                    file_path=(
                        "src/inventory.py"
                    ),
                    reason=(
                        "Validate the complete "
                        "order before mutation."
                    ),
                    replacement_content=(
                        "SECRET_REPLACEMENT_CONTENT"
                    ),
                )
            ],
        )
    }

    section = (
        build_worker_results_section(
            worker_results
        )
    )

    assert (
        "Made order reservation atomic."
        in section
    )

    assert (
        "src/inventory.py"
        in section
    )

    assert (
        "Validate the complete order "
        "before mutation."
        in section
    )

    assert (
        "SECRET_REPLACEMENT_CONTENT"
        not in section
    )