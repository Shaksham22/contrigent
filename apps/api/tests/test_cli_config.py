import os

from contrigent_api.cli import (
    config,
)


def test_missing_required_tokens(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = (
        tmp_path / ".env"
    )

    monkeypatch.setattr(
        config,
        "ENV_FILE",
        env_file,
    )

    monkeypatch.delenv(
        "OPENAI_API_KEY",
        raising=False,
    )

    monkeypatch.delenv(
        "GITHUB_TOKEN",
        raising=False,
    )

    missing = (
        config.missing_required_tokens()
    )

    assert missing == [
        (
            "OpenAI API key",
            "OPENAI_API_KEY",
        ),
        (
            "GitHub PAT (classic)",
            "GITHUB_TOKEN",
        ),
    ]


def test_token_is_saved_to_env_file(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = (
        tmp_path / ".env"
    )

    monkeypatch.setattr(
        config,
        "ENV_FILE",
        env_file,
    )

    monkeypatch.delenv(
        "OPENAI_API_KEY",
        raising=False,
    )

    config._save_token(
        "OPENAI_API_KEY",
        "fake-test-token",
    )

    assert (
        os.environ[
            "OPENAI_API_KEY"
        ]
        == "fake-test-token"
    )

    assert (
        "OPENAI_API_KEY="
        in env_file.read_text(
            encoding="utf-8"
        )
    )