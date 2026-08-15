from collections.abc import Callable


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