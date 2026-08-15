from contrigent_api.services.repository_context_builder import (
    build_repository_context,
    select_repository_files,
)


def test_small_repository_context_keeps_all_files() -> None:
    files = {
        "src/users.py": (
            "def display_name(user):\n"
            "    return user.display_name\n"
        ),
        "tests/test_users.py": (
            "def test_display_name():\n"
            "    pass\n"
        ),
    }

    context = build_repository_context(
        files,
        query_text=(
            "Fix display name handling."
        ),
    )

    assert "src/users.py" in context
    assert "tests/test_users.py" in context

    assert (
        "return user.display_name"
        in context
    )

    assert (
        "def test_display_name"
        in context
    )


def test_relevant_file_is_preferred_under_budget() -> None:
    files = {
        "docs/noise.txt": (
            "NOISE_BODY_MARKER "
            + ("x" * 5_000)
        ),
        "src/classify.py": (
            "def is_f_string(value):\n"
            "    return value.startswith('f')\n"
        ),
    }

    context = build_repository_context(
        files,
        query_text=(
            "classify.is_f_string "
            "incorrectly identifies "
            "an f-string"
        ),
        max_context_chars=500,
    )

    assert "src/classify.py" in context

    assert (
        "def is_f_string"
        in context
    )

    assert (
        "docs/noise.txt"
        in context
    )

    assert (
        "NOISE_BODY_MARKER"
        not in context
    )


def test_preferred_file_wins_even_when_query_is_unrelated() -> None:
    files = {
        "src/first.py": (
            "FIRST_FILE_MARKER\n"
            + ("a" * 1_000)
        ),
        "src/target.py": (
            "TARGET_FILE_MARKER\n"
        ),
    }

    selected = select_repository_files(
        files,
        query_text="unrelated words",
        preferred_paths=[
            "src/target.py"
        ],
        max_context_chars=200,
    )

    selected_paths = [
        path
        for path, _
        in selected
    ]

    assert (
        selected_paths[0]
        == "src/target.py"
    )