from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)


@dataclass(frozen=True)
class RunProgressEvent:
    kind: str
    message: str
    details: tuple[str, ...] = ()


RunProgressCallback = Callable[
    [RunProgressEvent],
    None,
]


def report_run_progress(
    callback: RunProgressCallback | None,
    kind: str,
    message: str,
    details: tuple[str, ...] = (),
) -> None:
    if callback is None:
        return

    callback(
        RunProgressEvent(
            kind=kind,
            message=message,
            details=details,
        )
    )


def build_test_failure_details(
    result: RepositoryTestResult,
    *,
    max_output_lines: int = 12,
) -> tuple[str, ...]:
    details: list[str] = [
        f"Stage: {result.stage}",
    ]

    if result.timed_out:
        details.append(
            "The test command timed out."
        )

    if result.exit_code is not None:
        details.append(
            f"Exit code: {result.exit_code}"
        )

    combined_output = "\n".join(
        part
        for part in (
            result.stdout,
            result.stderr,
        )
        if part.strip()
    )

    output_lines = [
        line.strip()
        for line
        in combined_output.splitlines()
        if line.strip()
    ]

    if output_lines:
        details.append(
            "Relevant output:"
        )

        details.extend(
            line[:300]
            for line
            in output_lines[
                -max_output_lines:
            ]
        )

    return tuple(details)