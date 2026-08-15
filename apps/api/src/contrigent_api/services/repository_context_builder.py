from __future__ import annotations

import re
from collections.abc import Iterable


MAX_REPOSITORY_CONTEXT_CHARS = 180_000
MAX_REPOSITORY_FILE_TREE_CHARS = 50_000


LOW_SIGNAL_TERMS = {
    "about",
    "after",
    "again",
    "also",
    "before",
    "could",
    "from",
    "github",
    "have",
    "into",
    "issue",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "with",
    "would",
}


TERM_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_.-]{2,}"
)


def build_repository_context(
    files: dict[str, str],
    *,
    query_text: str,
    preferred_paths: Iterable[str] = (),
    max_context_chars: int = (
        MAX_REPOSITORY_CONTEXT_CHARS
    ),
) -> str:
    file_tree = build_repository_file_tree(
        files
    )

    selected_files = select_repository_files(
        files,
        query_text=query_text,
        preferred_paths=preferred_paths,
        max_context_chars=max_context_chars,
    )

    if selected_files:
        file_contents = "\n\n".join(
            (
                f"--- FILE: {path} ---\n"
                f"{content}"
            )
            for path, content
            in selected_files
        )
    else:
        file_contents = (
            "No repository file contents "
            "were selected."
        )

    return f"""
=== REPOSITORY FILE TREE ===
{file_tree}

=== SELECTED REPOSITORY FILE CONTENT ===
{file_contents}
""".strip()


def build_repository_file_tree(
    files: dict[str, str],
) -> str:
    file_tree = "\n".join(
        sorted(files)
    )

    if (
        len(file_tree)
        <= MAX_REPOSITORY_FILE_TREE_CHARS
    ):
        return file_tree

    return (
        file_tree[
            :MAX_REPOSITORY_FILE_TREE_CHARS
        ]
        + "\n\n"
        + "[FILE TREE TRUNCATED]"
    )


def select_repository_files(
    files: dict[str, str],
    *,
    query_text: str,
    preferred_paths: Iterable[str] = (),
    max_context_chars: int = (
        MAX_REPOSITORY_CONTEXT_CHARS
    ),
) -> list[tuple[str, str]]:
    preferred = {
        _normalize_path(path)
        for path in preferred_paths
        if path.strip()
    }

    query_terms = _extract_query_terms(
        query_text
    )

    ranked_files = sorted(
        files.items(),
        key=lambda item: (
            -_score_file(
                item[0],
                item[1],
                query_terms,
                preferred,
            ),
            len(item[1]),
            item[0],
        ),
    )

    selected: list[
        tuple[str, str]
    ] = []

    used_chars = 0

    for path, content in ranked_files:
        section_size = (
            len(path)
            + len(content)
            + 32
        )

        if (
            used_chars + section_size
            > max_context_chars
        ):
            continue

        selected.append(
            (
                path,
                content,
            )
        )

        used_chars += section_size

    return selected


def _score_file(
    path: str,
    content: str,
    query_terms: set[str],
    preferred_paths: set[str],
) -> int:
    normalized_path = (
        _normalize_path(path)
    )

    path_lower = (
        normalized_path.lower()
    )

    content_lower = content.lower()

    score = 0

    if normalized_path in preferred_paths:
        score += 100_000

    for term in query_terms:
        if term in path_lower:
            score += 1_000

        occurrences = (
            content_lower.count(term)
        )

        score += min(
            occurrences,
            10,
        ) * 10

    if (
        path_lower.startswith("tests/")
        or "/tests/" in path_lower
        or path_lower.startswith("test_")
        or "/test_" in path_lower
    ):
        score += 25

    return score


def _extract_query_terms(
    text: str,
) -> set[str]:
    terms = {
        match.group(0).lower()
        for match
        in TERM_PATTERN.finditer(text)
    }

    return {
        term
        for term in terms
        if (
            len(term) >= 4
            and term
            not in LOW_SIGNAL_TERMS
        )
    }


def _normalize_path(
    path: str,
) -> str:
    return (
        path.strip()
        .removeprefix("./")
    )