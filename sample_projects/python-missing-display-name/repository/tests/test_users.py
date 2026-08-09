from src.users import User, get_display_name


def test_returns_uppercase_display_name() -> None:
    user = User(
        username="shaksham",
        display_name="Shaksham Shubham",
    )

    assert get_display_name(user) == "SHAKSHAM SHUBHAM"


def test_falls_back_to_username_when_display_name_is_missing() -> None:
    user = User(
        username="shaksham",
        display_name=None,
    )

    assert get_display_name(user) == "shaksham"