from contrigent_api.cli.prompts import (
    ask_for_approval,
    ask_for_round_limit,
)
from contrigent_api.cli.display import (
    show_run_progress,
)
from contrigent_api.services.run_progress import (
    RunProgressEvent,
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

def test_run_progress_displays_failure_details(
    capsys,
) -> None:
    show_run_progress(
        RunProgressEvent(
            kind="testing_failed",
            message=(
                "Candidate tests failed"
            ),
            details=(
                "Stage: tests",
                "Exit code: 2",
                (
                    "ERROR collecting "
                    "tests/test_example.py"
                ),
            ),
        )
    )

    output = (
        capsys.readouterr().out
    )

    assert (
        "Candidate tests failed"
        in output
    )

    assert (
        "Exit code: 2"
        in output
    )

    assert (
        "ERROR collecting"
        in output
    )


def test_repository_preflight_progress_is_displayed(
    capsys,
) -> None:
    messages = (
        ("preflight_started", "Repository preflight"),
        (
            "preflight_detecting",
            "Detecting test environment",
        ),
        (
            "preflight_verifying",
            "Verifying untouched repository",
        ),
        (
            "preflight_discovery",
            "Setup specialist attempt 1/2",
        ),
        ("preflight_passed", "Baseline passed"),
        ("analysis_started", "Starting issue analysis"),
    )

    for kind, message in messages:
        show_run_progress(
            RunProgressEvent(
                kind=kind,
                message=message,
            )
        )

    output = capsys.readouterr().out

    for _kind, message in messages:
        assert message in output
