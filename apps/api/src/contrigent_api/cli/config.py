from __future__ import annotations

import os
from pathlib import Path
import sys
import termios
import tty

from getpass import getpass
import os

from dotenv import (
    load_dotenv,
    set_key,
)

from getpass import getpass

PROJECT_ROOT = (
    Path(__file__).resolve().parents[5]
)

ENV_FILE = PROJECT_ROOT / ".env"

TOKEN_TYPES = {
    "1": (
        "OpenAI API key",
        "OPENAI_API_KEY",
    ),
    "2": (
        "GitHub PAT (classic)",
        "GITHUB_TOKEN",
    ),
}

REQUIRED_TOKENS = (
    (
        "OpenAI API key",
        "OPENAI_API_KEY",
    ),
    (
        "GitHub PAT (classic)",
        "GITHUB_TOKEN",
    ),
)


def load_environment() -> None:
    load_dotenv(
        ENV_FILE,
        override=False,
    )


def missing_required_tokens(
) -> list[tuple[str, str]]:
    load_environment()

    missing: list[
        tuple[str, str]
    ] = []

    for label, environment_name in (
        REQUIRED_TOKENS
    ):
        value = os.getenv(
            environment_name,
            "",
        ).strip()

        if not value:
            missing.append(
                (
                    label,
                    environment_name,
                )
            )

    return missing


def add_token_interactively() -> None:
    print()
    print("Add Contrigent token")
    print()

    for option, (
        label,
        _,
    ) in TOKEN_TYPES.items():
        print(
            f"[{option}] {label}"
        )

    print()

    while True:
        choice = input(
            "Select token type: "
        ).strip()

        token_type = TOKEN_TYPES.get(
            choice
        )

        if token_type is not None:
            break

        print(
            "Please select 1 or 2."
        )

    label, environment_name = (
        token_type
    )

    _prompt_and_save_token(
        label,
        environment_name,
    )


def ensure_required_tokens() -> bool:
    missing = (
        missing_required_tokens()
    )

    if not missing:
        return True

    print("Configuration required.")
    print()
    print(
        "Contrigent needs two credentials "
        "before it can work with GitHub and "
        "the AI models."
    )
    print()
    print(
        "OpenAI API key:"
    )
    print(
        "Used by the Manager, workers, and "
        "Independent Reviewer."
    )
    print()
    print(
        "GitHub PAT (classic):"
    )
    print(
        "Used to identify your GitHub account, "
        "create or access your fork, push the "
        "Contrigent branch, and create the "
        "draft pull request."
    )
    print()
    print(
        "Credentials are stored locally in "
        "Contrigent's .env file and are not "
        "sent to the AI agents."
    )
    print()

    print("Missing:")

    for label, _ in missing:
        print(
            f"- {label}"
        )

    while True:
        print()
        print(
            "[A] Add missing tokens now"
        )
        print(
            "[F] Configure using .env file"
        )
        print(
            "[Q] Quit"
        )
        print()

        choice = input(
            "> "
        ).strip().lower()

        if choice == "a":
            for (
                label,
                environment_name,
            ) in missing:
                _prompt_and_save_token(
                    label,
                    environment_name,
                )

            return (
                not missing_required_tokens()
            )

        if choice == "f":
            _show_env_file_instructions()

            input(
                "\nPress Enter after saving "
                "the .env file..."
            )

            load_dotenv(
                ENV_FILE,
                override=True,
            )

            missing = (
                missing_required_tokens()
            )

            if not missing:
                print()
                print(
                    "✓ Credentials configured"
                )
                return True

            print()
            print(
                "Required credentials are "
                "still missing."
            )

            continue

        if choice == "q":
            return False

        print(
            "Please enter A, F, or Q."
        )


def _prompt_and_save_token(
    label: str,
    environment_name: str,
) -> None:
    print()
    if (
        environment_name
        == "OPENAI_API_KEY"
    ):
        print(
            "Paste your OpenAI API key."
        )
        print(
            "It will be stored locally and "
            "shown only as * characters."
        )

    elif (
        environment_name
        == "GITHUB_TOKEN"
    ):
        print(
            "Paste your GitHub PAT (classic)."
        )
        print(
            "Contrigent uses this for fork, "
            "push, and draft pull request "
            "operations."
        )
        print(
            "It will be stored locally and "
            "shown only as * characters."
        )

    print()
    print(
        f"Enter {label}:"
)

    token = _masked_input(
        "> "
    ).strip()

    if not token:
        print(
            "Token cannot be empty."
        )

        _prompt_and_save_token(
            label,
            environment_name,
        )

        return

    _save_token(
        environment_name,
        token,
    )

    print()
    print(
        f"✓ {label} saved"
    )


def _save_token(
    environment_name: str,
    token: str,
) -> None:
    ENV_FILE.touch(
        mode=0o600,
        exist_ok=True,
    )

    set_key(
        str(ENV_FILE),
        environment_name,
        token,
        quote_mode="always",
    )

    ENV_FILE.chmod(
        0o600
    )

    os.environ[
        environment_name
    ] = token


def _show_env_file_instructions(
) -> None:
    print()
    print("Credential file:")
    print(
        ENV_FILE
    )
    print()

    print(
        "Add these values:"
    )
    print()
    print(
        "OPENAI_API_KEY=<your-openai-key>"
    )
    print(
        "GITHUB_TOKEN=<your-github-pat>"
    )

def _masked_input(
    prompt: str = "> ",
) -> str:
    print(
        prompt,
        end="",
        flush=True,
    )

    file_descriptor = (
        sys.stdin.fileno()
    )

    old_settings = (
        termios.tcgetattr(
            file_descriptor
        )
    )

    characters: list[str] = []

    try:
        tty.setraw(
            file_descriptor
        )

        while True:
            character = (
                sys.stdin.read(1)
            )

            if character in {
                "\r",
                "\n",
            }:
                print()
                break

            if character == "\x03":
                raise KeyboardInterrupt

            if character == "\x04":
                raise EOFError

            if character in {
                "\x7f",
                "\b",
            }:
                if characters:
                    characters.pop()

                    print(
                        "\b \b",
                        end="",
                        flush=True,
                    )

                continue

            if character.isprintable():
                characters.append(
                    character
                )

                print(
                    "*",
                    end="",
                    flush=True,
                )

    finally:
        termios.tcsetattr(
            file_descriptor,
            termios.TCSADRAIN,
            old_settings,
        )

    return "".join(
        characters
    )