from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os

from contrigent_api.services.github_project_downloader import (
    parse_github_issue_url,
    parse_github_repository_url,
)


GITHUB_API_VERSION = "2026-03-10"
PULL_REQUEST_ATTRIBUTION = (
    "\n\n---\n\n"
    "This pull request and its code changes were generated using "
    "**Contrigent**, a multi-agent software engineering framework "
    "developed by [Shaksham22](https://github.com/Shaksham22)."
)


class GitHubPullRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubPullRequestResult:
    number: int
    url: str


def get_github_token() -> str:
    token = os.getenv(
        "GITHUB_TOKEN",
        "",
    ).strip()

    if not token:
        raise GitHubPullRequestError(
            "GITHUB_TOKEN is required to create "
            "a draft pull request."
        )

    return token


def get_issue_title(
    issue_markdown: str,
) -> str:
    for line in issue_markdown.splitlines():
        stripped = line.strip()

        if stripped.startswith("# "):
            title = stripped[2:].strip()

            if title:
                return title

    return "Contrigent proposed changes"


def build_pull_request_body(
    issue_number: int,
    analysis_summary: str,
    test_summary: str,
) -> str:
    return (
        "## Summary\n\n"
        f"{analysis_summary}\n\n"
        "## Validation\n\n"
        "- Repository tests passed in Contrigent's "
        "isolated Docker test environment.\n"
        f"- Test result: {test_summary}\n\n"
        f"Closes #{issue_number}\n\n"
        "---\n"
        "Draft pull request created by Contrigent "
        "after human approval."
    )

def create_draft_pull_request(
    repository_url: str,
    issue_url: str,
    head_owner: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
) -> GitHubPullRequestResult:
    repository_owner, repository_name = (
        parse_github_repository_url(
            repository_url
        )
    )

    issue_location = parse_github_issue_url(
        issue_url
    )

    if (
        issue_location.owner.casefold()
        != repository_owner.casefold()
        or issue_location.repository.casefold()
        != repository_name.casefold()
    ):
        raise GitHubPullRequestError(
            "GitHub issue and repository do not match."
        )

    token = get_github_token()

    pull_request_body = (
        body.rstrip()
        + PULL_REQUEST_ATTRIBUTION
    )

    payload = {
        "title": title,
        "head": (
            f"{head_owner}:{head_branch}"
        ),
        "base": base_branch,
        "body": pull_request_body,
        "draft": True,
    }

    request = Request(
        (
            "https://api.github.com/repos/"
            f"{repository_owner}/"
            f"{repository_name}/pulls"
        ),
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": (
                f"Bearer {token}"
            ),
            "X-GitHub-Api-Version": (
                GITHUB_API_VERSION
            ),
            "User-Agent": "Contrigent",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=30,
        ) as response:
            response_data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except HTTPError as error:
        details = error.read().decode(
            "utf-8",
            errors="replace",
        )

        raise GitHubPullRequestError(
            "GitHub rejected draft PR creation "
            f"with HTTP {error.code}: "
            f"{details[:500]}"
        ) from error

    except URLError as error:
        raise GitHubPullRequestError(
            "Could not connect to GitHub "
            f"while creating the draft PR: "
            f"{error.reason}"
        ) from error

    number = response_data.get(
        "number"
    )

    url = response_data.get(
        "html_url"
    )

    if (
        not isinstance(number, int)
        or not isinstance(url, str)
        or not url
    ):
        raise GitHubPullRequestError(
            "GitHub returned an unexpected "
            "draft PR response."
        )

    return GitHubPullRequestResult(
        number=number,
        url=url,
    )