import argparse
from pathlib import Path
import sys
import threading
import time

from contrigent_api.services.repository_test_runner import (
    RepositoryTestRunnerError,
    run_repository_tests,
)


PROGRESS_BAR_WIDTH = 40
DISPLAY_WIDTH = 120

SPINNER_FRAMES = (
    "◐",
    "◓",
    "◑",
    "◒",
)


class ProgressDisplay:
    def __init__(self) -> None:
        self.percentage = 0
        self.message = "Starting"

        self._spinner_index = 0
        self._stop_event = (
            threading.Event()
        )

        self._lock = (
            threading.Lock()
        )

        self._thread = threading.Thread(
            target=self._animate,
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def update(
        self,
        percentage: int,
        message: str,
    ) -> None:
        with self._lock:
            self.percentage = percentage
            self.message = message

    def _build_bar(
        self,
        percentage: int,
    ) -> str:
        filled = round(
            PROGRESS_BAR_WIDTH
            * percentage
            / 100
        )

        empty = (
            PROGRESS_BAR_WIDTH
            - filled
        )

        # Uses the exact full block and hyphen combination from your image
        return (
            "█" * filled
            + "-" * empty
        )


    def _render(
        self,
        spinner: str,
    ) -> str:
        with self._lock:
            percentage = (
                self.percentage
            )

            message = self.message

        progress_bar = self._build_bar(
            percentage
        )

        return (
            f"[{progress_bar}] "
            f"{percentage:>3}%  "
            f"{message} "
            f"{spinner}"
        )

    def _write_line(
        self,
        line: str,
    ) -> None:
        sys.stdout.write(
            "\r"
            + line.ljust(
                DISPLAY_WIDTH
            )
        )

        sys.stdout.flush()

    def _animate(self) -> None:
        while not self._stop_event.is_set():
            spinner = SPINNER_FRAMES[
                self._spinner_index
            ]

            self._write_line(
                self._render(
                    spinner
                )
            )

            self._spinner_index = (
                self._spinner_index + 1
            ) % len(
                SPINNER_FRAMES
            )

            time.sleep(0.15)

    def finish(
        self,
        percentage: int,
        message: str,
        symbol: str,
    ) -> None:
        self.update(
            percentage,
            message,
        )

        self._stop_event.set()
        self._thread.join()

        final_line = (
            self._render(
                symbol
            )
        )

        self._write_line(
            final_line
        )

        sys.stdout.write("\n")
        sys.stdout.flush()


def find_pytest_summary(
    output: str,
) -> str | None:
    for line in reversed(
        output.splitlines()
    ):
        cleaned_line = (
            line.strip()
            .strip("=")
            .strip()
        )

        if (
            " passed" in cleaned_line
            or " failed" in cleaned_line
            or " error" in cleaned_line
        ):
            return cleaned_line

    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a repository's automated tests "
            "inside Contrigent's Docker sandbox."
        )
    )

    parser.add_argument(
        "repository_path",
        help="Path to the Git repository.",
    )

    parser.add_argument(
        "--verbose",
        type=int,
        choices=(0, 1),
        default=1,
        help=(
            "Show complete repository test output. "
            "Use --verbose 0 to hide detailed output."
        ),
    )

    args = parser.parse_args()

    repository_path = Path(
        args.repository_path
    ).resolve()

    progress = ProgressDisplay()

    progress.start()

    try:
        result = run_repository_tests(
            repository_path,
            progress_callback=(
                progress.update
            ),
        )

    except RepositoryTestRunnerError as error:
        progress.finish(
            100,
            "Test runner error",
            "✗",
        )

        print(
            f"Repository test runner error: {error}"
        )

        raise SystemExit(
            2
        ) from error

    if result.passed:
        progress.finish(
            100,
            "Tests passed",
            "✓",
        )
    else:
        progress.finish(
            100,
            "Tests failed",
            "✗",
        )

    pytest_summary = (
        find_pytest_summary(
            result.stdout
        )
    )

    print()

    if pytest_summary:
        print(pytest_summary)

    print(
        "Total test time: "
        f"{result.duration_seconds}s"
    )

    if args.verbose == 1:
        if result.stdout:
            print()
            print("STDOUT:")
            print(result.stdout)

        if result.stderr:
            print()
            print("STDERR:")
            print(result.stderr)

    elif not result.passed:
        if result.stdout:
            print()
            print(result.stdout)

        if result.stderr:
            print()
            print(result.stderr)

    raise SystemExit(
        0 if result.passed else 1
    )


if __name__ == "__main__":
    main()