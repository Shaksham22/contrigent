import argparse
from pathlib import Path

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

    try:
        result = run_repository_tests(
            repository_path
        )
    except RepositoryTestRunnerError as error:
        print(
            f"Repository test runner error: {error}"
        )
        raise SystemExit(2) from error

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


if __name__ == "__main__":
    main()