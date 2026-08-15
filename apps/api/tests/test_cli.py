from contrigent_api.cli.prompts import (
    ask_for_approval,
    ask_for_round_limit,
)


def test_approval_accepts_yes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "y",
    )

    approved = ask_for_approval(
        "Proceed?",
        lambda: None,
    )

    assert approved is True


def test_approval_accepts_no(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "n",
    )

    approved = ask_for_approval(
        "Proceed?",
        lambda: None,
    )

    assert approved is False


def test_details_can_be_shown_before_approval(
    monkeypatch,
) -> None:
    answers = iter(
        [
            "d",
            "y",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: next(
            answers
        ),
    )

    details_shown: list[bool] = []

    approved = ask_for_approval(
        "Proceed?",
        lambda: details_shown.append(
            True
        ),
    )

    assert approved is True
    assert details_shown == [
        True
    ]


def test_round_limit_uses_default(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "",
    )

    assert (
        ask_for_round_limit(
            "Maximum testing rounds",
        )
        == 2
    )


def test_round_limit_accepts_value(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "3",
    )

    assert (
        ask_for_round_limit(
            "Maximum review rounds",
        )
        == 3
    )


def test_round_limit_rejects_invalid_value(
    monkeypatch,
) -> None:
    answers = iter(
        [
            "0",
            "11",
            "three",
            "4",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: next(
            answers
        ),
    )

    assert (
        ask_for_round_limit(
            "Maximum review rounds",
        )
        == 4
    )