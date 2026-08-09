from dataclasses import dataclass


@dataclass
class User:
    username: str
    display_name: str | None


def get_display_name(user: User) -> str:
    return user.display_name.upper()