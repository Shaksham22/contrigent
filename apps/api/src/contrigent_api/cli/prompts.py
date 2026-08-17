from collections.abc import Callable
import select
import sys


TimedInputReader = Callable[
    [str, float],
    str | None,
]
InputReader = Callable[[str], str]


def read_input_with_timeout(
    prompt: str,
    timeout_seconds: float,
) -> str | None:
    print(
        prompt,
        end="",
        flush=True,
    )
    readable, _, _ = select.select(
        [sys.stdin],
        [],
        [],
        timeout_seconds,
    )

    if not readable:
        print()
        return None

    value = sys.stdin.readline()

    if value.endswith("\n"):
        value = value[:-1]

    return value


def ask_for_issue_comment_decision(
    show_details: Callable[[], None],
    *,
    timeout_seconds: float = 5.0,
    timed_input_reader: TimedInputReader | None = None,
    input_reader: InputReader | None = None,
) -> bool:
    timed_reader = (
        timed_input_reader
        or read_input_with_timeout
    )
    reader = input_reader or input

    print(
        "[Y] Post now  [N] Skip  "
        "[D] Show details"
    )
    choice = timed_reader(
        "> ",
        timeout_seconds,
    )

    if choice is None:
        return True

    normalized = choice.strip().lower()

    if normalized in {"y", "yes"}:
        return True

    if normalized in {"n", "no"}:
        return False

    if normalized in {"d", "details"}:
        print()
        show_details()
        return _ask_after_issue_comment_details(
            reader
        )

    print(
        "Please enter Y, N, or D."
    )
    return _ask_for_issue_comment_without_timeout(
        show_details,
        reader,
    )


def _ask_for_issue_comment_without_timeout(
    show_details: Callable[[], None],
    input_reader: InputReader,
) -> bool:
    while True:
        print()
        print(
            "[Y] Post  [N] Skip  "
            "[D] Show details"
        )
        choice = input_reader(
            "> "
        ).strip().lower()

        if choice in {"y", "yes"}:
            return True

        if choice in {"n", "no"}:
            return False

        if choice in {"d", "details"}:
            print()
            show_details()
            return _ask_after_issue_comment_details(
                input_reader
            )

        print(
            "Please enter Y, N, or D."
        )


def _ask_after_issue_comment_details(
    input_reader: InputReader,
) -> bool:
    while True:
        print()
        print(
            "[Y] Post  [N] Skip"
        )
        choice = input_reader(
            "> "
        ).strip().lower()

        if choice in {"y", "yes"}:
            return True

        if choice in {"n", "no"}:
            return False

        print(
            "Please enter Y or N."
        )


def ask_for_approval(
    question: str,
    show_details: Callable[[], None],
    *,
    approve_label: str = "Approve",
) -> bool:
    while True:
        print()
        print(question)
        print()
        print(
            f"[Y] {approve_label}  "
            "[N] Cancel  "
            "[D] Show details"
        )

        choice = input("> ").strip().lower()

        if choice in {
            "y",
            "yes",
        }:
            return True

        if choice in {
            "n",
            "no",
        }:
            return False

        if choice in {
            "d",
            "details",
        }:
            print()
            show_details()
            continue

        print(
            "Please enter Y, N, or D."
        )

def ask_for_round_limit(
    label: str,
    *,
    default: int = 2,
) -> int:
    while True:
        value = input(
            f"{label} [{default}]: "
        ).strip()

        if not value:
            return default

        try:
            round_limit = int(
                value
            )
        except ValueError:
            print(
                "Enter a number from "
                "1 to 10."
            )
            continue

        if not 1 <= round_limit <= 10:
            print(
                "Enter a number from "
                "1 to 10."
            )
            continue

        return round_limit
