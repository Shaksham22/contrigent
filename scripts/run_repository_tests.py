import argparse
from pathlib import Path
import sys
import threading
import time

from contrigent_api.services.repository_test_runner import (
    RepositoryTestRunnerError,
    run_repository_tests,
)


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

    args = parser.parse_args()

    repository_path = Path(
        args.repository_path
    ).resolve()

    stop_event = threading.Event()

    processing_thread = threading.Thread(
        target=show_processing,
        args=(stop_event,),
        daemon=True,
    )

    processing_thread.start()

    try:
        result = run_repository_tests(
            repository_path
        )

    except RepositoryTestRunnerError as error:
        stop_event.set()
        processing_thread.join()

        print(
            f"Repository test runner error: {error}"
        )

        raise SystemExit(2) from error

    finally:
        stop_event.set()
        processing_thread.join()
    print()
    print(
        "Repository tests:"
        f" {'PASSED' if result.passed else 'FAILED'}"
    )
    print(
        f"Stage: {result.stage}"
    )
    print(
        f"Exit code: {result.exit_code}"
    )
    print(
        f"Duration: {result.duration_seconds}s"
    )

    if result.stdout:
        print()
        print("STDOUT:")
        print(result.stdout)

    if result.stderr:
        print()
        print("STDERR:")
        print(result.stderr)

    raise SystemExit(
        0 if result.passed else 1
    )
def show_processing(
    stop_event: threading.Event,
) -> None:
    dot_count = 1

    while not stop_event.is_set():
        message = (
            "Processing"
            + "." * dot_count
        )

        sys.stdout.write(
            f"\r{message:<20}"
        )
        sys.stdout.flush()

        dot_count += 1

        if dot_count > 3:
            dot_count = 1

        time.sleep(0.5)

    sys.stdout.write(
        "\r" + " " * 20 + "\r"
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()