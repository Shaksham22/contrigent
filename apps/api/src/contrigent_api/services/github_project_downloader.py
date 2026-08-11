from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
import re
import shutil
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[5]

DOWNLOADED_GITHUB_PROJECTS_FOLDER = (
    PROJECT_ROOT
    / "downloaded_github_projects"
)


class GitHubProjectDownloadError(RuntimeError):
    pass


@dataclass
class GitHubIssueLocation:
    owner: str
    repository: str
    issue_number: int


@dataclass
class DownloadedGitHubProject:
    project_name: str
    project_folder: Path
    issue_file: Path
    repository_folder: Path
    issue_url: str
    repository_url: str


def parse_github_repository_url(
    repository_url: str,
) -> tuple[str, str]:
    parsed_url = urlparse(
        repository_url.strip()
    )

    if parsed_url.scheme != "https":
        raise GitHubProjectDownloadError(
            "GitHub repository URL must use HTTPS."
        )

    if parsed_url.netloc.lower() != "github.com":
        raise GitHubProjectDownloadError(
            "Repository URL must be a github.com URL."
        )

    path_parts = [
        part
        for part in parsed_url.path.strip("/").split("/")
        if part
    ]

    if len(path_parts) != 2:
        raise GitHubProjectDownloadError(
            "Repository URL must identify one GitHub repository."
        )

    owner = path_parts[0]
    repository = path_parts[1]

    if repository.endswith(".git"):
        repository = repository[:-4]

    if not owner or not repository:
        raise GitHubProjectDownloadError(
            "Repository URL is missing owner or repository name."
        )

    return owner, repository


def parse_github_issue_url(
    issue_url: str,
) -> GitHubIssueLocation:
    parsed_url = urlparse(
        issue_url.strip()
    )

    if parsed_url.scheme != "https":
        raise GitHubProjectDownloadError(
            "GitHub issue URL must use HTTPS."
        )

    if parsed_url.netloc.lower() != "github.com":
        raise GitHubProjectDownloadError(
            "Issue URL must be a github.com URL."
        )

    path_parts = [
        part
        for part in parsed_url.path.strip("/").split("/")
        if part
    ]

    if (
        len(path_parts) != 4
        or path_parts[2] != "issues"
    ):
        raise GitHubProjectDownloadError(
            "Issue URL must look like "
            "https://github.com/owner/repository/issues/123"
        )

    owner = path_parts[0]
    repository = path_parts[1]

    try:
        issue_number = int(
            path_parts[3]
        )
    except ValueError as error:
        raise GitHubProjectDownloadError(
            "GitHub issue number must be a number."
        ) from error

    if issue_number < 1:
        raise GitHubProjectDownloadError(
            "GitHub issue number must be positive."
        )

    return GitHubIssueLocation(
        owner=owner,
        repository=repository,
        issue_number=issue_number,
    )


def validate_issue_matches_repository(
    issue_location: GitHubIssueLocation,
    repository_url: str,
) -> None:
    repository_owner, repository_name = (
        parse_github_repository_url(
            repository_url
        )
    )

    if (
        issue_location.owner.casefold()
        != repository_owner.casefold()
        or issue_location.repository.casefold()
        != repository_name.casefold()
    ):
        raise GitHubProjectDownloadError(
            "GitHub issue and repository URLs "
            "must belong to the same repository."
        )


def normalize_project_name_part(
    value: str,
) -> str:
    normalized = re.sub(
        r"[^a-zA-Z0-9]+",
        "-",
        value.strip(),
    )

    return normalized.strip("-").lower()


def build_downloaded_project_name(
    issue_location: GitHubIssueLocation,
) -> str:
    owner = normalize_project_name_part(
        issue_location.owner
    )

    repository = normalize_project_name_part(
        issue_location.repository
    )

    return (
        f"{owner}-{repository}-"
        f"issue-{issue_location.issue_number}"
    )


def build_github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Contrigent",
        "X-GitHub-Api-Version": "2026-03-10",
    }

    github_token = os.getenv(
        "GITHUB_TOKEN"
    )

    if github_token:
        headers["Authorization"] = (
            f"Bearer {github_token}"
        )

    return headers


def fetch_github_json(
    api_url: str,
):
    request = Request(
        api_url,
        headers=build_github_api_headers(),
    )

    try:
        with urlopen(
            request,
            timeout=30,
        ) as response:
            return json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except HTTPError as error:
        raise GitHubProjectDownloadError(
            f"GitHub API returned HTTP {error.code}."
        ) from error

    except URLError as error:
        raise GitHubProjectDownloadError(
            f"Could not connect to GitHub: {error.reason}"
        ) from error


def fetch_all_issue_comments(
    owner: str,
    repository: str,
    issue_number: int,
) -> list[dict]:
    comments: list[dict] = []
    page = 1

    while True:
        page_comments = fetch_github_json(
            "https://api.github.com/repos/"
            f"{owner}/{repository}/issues/"
            f"{issue_number}/comments"
            f"?per_page=100&page={page}"
        )

        if not isinstance(
            page_comments,
            list,
        ):
            raise GitHubProjectDownloadError(
                "GitHub returned an unexpected comments response."
            )

        comments.extend(
            page_comments
        )

        if len(page_comments) < 100:
            break

        page += 1

    return comments


def build_issue_markdown(
    issue: dict,
    comments: list[dict],
) -> str:
    title = issue.get(
        "title",
        "Untitled GitHub Issue",
    )

    body = issue.get(
        "body"
    ) or ""

    issue_author = (
        issue.get("user") or {}
    ).get(
        "login",
        "unknown"
    )

    issue_url = issue.get(
        "html_url",
        "",
    )

    sections = [
        f"# {title}",
        "",
        f"Author: {issue_author}",
        f"GitHub URL: {issue_url}",
        "",
        "## Issue Description",
        "",
        body,
        "",
        "## Discussion",
        "",
    ]

    if not comments:
        sections.append(
            "No issue comments."
        )

    for index, comment in enumerate(
        comments,
        start=1,
    ):
        comment_author = (
            comment.get("user") or {}
        ).get(
            "login",
            "unknown",
        )

        created_at = comment.get(
            "created_at",
            "",
        )

        comment_body = comment.get(
            "body"
        ) or ""

        sections.extend(
            [
                f"### Comment {index}",
                "",
                f"Author: {comment_author}",
                f"Created: {created_at}",
                "",
                comment_body,
                "",
            ]
        )

    return "\n".join(
        sections
    ).strip() + "\n"


def clone_github_repository(
    repository_url: str,
    repository_folder: Path,
) -> None:
    result = subprocess.run(
        [
            "git",
            "clone",
            repository_url,
            str(repository_folder),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Git clone failed."
        )

        raise GitHubProjectDownloadError(
            message
        )


def download_github_project(
    issue_url: str,
    repository_url: str,
) -> DownloadedGitHubProject:
    issue_location = parse_github_issue_url(
        issue_url
    )

    validate_issue_matches_repository(
        issue_location,
        repository_url,
    )

    project_name = (
        build_downloaded_project_name(
            issue_location
        )
    )

    project_folder = (
        DOWNLOADED_GITHUB_PROJECTS_FOLDER
        / project_name
    )

    if project_folder.exists():
        raise GitHubProjectDownloadError(
            f"Downloaded GitHub project already exists: {project_name}"
        )

    issue_file = (
        project_folder
        / "github_issue.md"
    )

    repository_folder = (
        project_folder
        / "repository"
    )

    api_issue_url = (
        "https://api.github.com/repos/"
        f"{issue_location.owner}/"
        f"{issue_location.repository}/issues/"
        f"{issue_location.issue_number}"
    )

    try:
        project_folder.mkdir(
            parents=True
        )

        issue = fetch_github_json(
            api_issue_url
        )

        if not isinstance(
            issue,
            dict,
        ):
            raise GitHubProjectDownloadError(
                "GitHub returned an unexpected issue response."
            )

        comments = (
            fetch_all_issue_comments(
                issue_location.owner,
                issue_location.repository,
                issue_location.issue_number,
            )
        )

        issue_file.write_text(
            build_issue_markdown(
                issue,
                comments,
            ),
            encoding="utf-8",
        )

        clone_github_repository(
            repository_url,
            repository_folder,
        )

    except Exception:
        if project_folder.exists():
            shutil.rmtree(
                project_folder
            )

        raise

    return DownloadedGitHubProject(
        project_name=project_name,
        project_folder=project_folder,
        issue_file=issue_file,
        repository_folder=repository_folder,
        issue_url=issue_url,
        repository_url=repository_url,
    )


def get_or_download_github_project(
    issue_url: str,
    repository_url: str,
) -> DownloadedGitHubProject:
    issue_location = parse_github_issue_url(
        issue_url
    )

    validate_issue_matches_repository(
        issue_location,
        repository_url,
    )

    project_name = (
        build_downloaded_project_name(
            issue_location
        )
    )

    project_folder = (
        DOWNLOADED_GITHUB_PROJECTS_FOLDER
        / project_name
    )

    issue_file = (
        project_folder
        / "github_issue.md"
    )

    repository_folder = (
        project_folder
        / "repository"
    )

    if project_folder.exists():
        if (
            issue_file.is_file()
            and repository_folder.is_dir()
            and (
                repository_folder / ".git"
            ).exists()
        ):
            return DownloadedGitHubProject(
                project_name=project_name,
                project_folder=project_folder,
                issue_file=issue_file,
                repository_folder=repository_folder,
                issue_url=issue_url,
                repository_url=repository_url,
            )

        raise GitHubProjectDownloadError(
            "Existing downloaded project is incomplete: "
            f"{project_name}"
        )

    return download_github_project(
        issue_url,
        repository_url,
    )