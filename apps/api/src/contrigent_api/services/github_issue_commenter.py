from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json

from contrigent_api.services.github_project_downloader import (
    GitHubProjectDownloadError,
    parse_github_issue_url,
)
from contrigent_api.services.github_pull_request_creator import (
    GITHUB_API_VERSION,
    GitHubPullRequestError,
    get_github_token,
)


class GitHubIssueCommentError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubIssueCommentResult:
    number: int
    url: str


def create_issue_comment(
    issue_url: str,
    body: str,
) -> GitHubIssueCommentResult:
    try:
        issue = parse_github_issue_url(
            issue_url
        )
        token = get_github_token()
    except (
        GitHubProjectDownloadError,
        GitHubPullRequestError,
    ) as error:
        raise GitHubIssueCommentError(
            "Could not prepare the GitHub issue comment request."
        ) from error

    payload = {
        "body": body,
    }
    request = Request(
        (
            "https://api.github.com/repos/"
            f"{issue.owner}/{issue.repository}/"
            f"issues/{issue.issue_number}/comments"
        ),
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
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
        raise GitHubIssueCommentError(
            "GitHub rejected issue comment creation "
            f"with HTTP {error.code}."
        ) from error
    except URLError as error:
        raise GitHubIssueCommentError(
            "Could not connect to GitHub while posting "
            "the issue comment."
        ) from error
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        raise GitHubIssueCommentError(
            "GitHub returned an unreadable issue comment response."
        ) from error

    number = response_data.get(
        "id"
    )
    url = response_data.get(
        "html_url"
    )

    if (
        not isinstance(number, int)
        or not isinstance(url, str)
        or not url
    ):
        raise GitHubIssueCommentError(
            "GitHub returned an unexpected issue comment response."
        )

    return GitHubIssueCommentResult(
        number=number,
        url=url,
    )
