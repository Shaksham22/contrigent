from pathlib import Path
from urllib.request import Request
import base64
import socket

import pytest

from contrigent_api.models.run_record import (
    RunStatus,
)
from contrigent_api.services import (
    contribution_policy_checker,
)
from contrigent_api.services.contribution_policy_checker import (
    ContributionPolicyOutcome,
    ExternalPolicyFetchError,
    ExternalPolicyPage,
    PolicyLink,
    check_contribution_policy,
    fetch_external_policy_page,
    validate_external_policy_url,
)


REPOSITORY_URL = (
    "https://github.com/example/project"
)


def no_community_profile(
    _url: str,
    **_kwargs,
):
    return {
        "files": {},
    }


def check_local_repository(
    repository_path: Path,
    *,
    external_fetcher=None,
):
    return check_contribution_policy(
        repository_path,
        REPOSITORY_URL,
        github_fetcher=no_community_profile,
        external_fetcher=external_fetcher,
    )


def write_policy(
    repository_path: Path,
    relative_path: str,
    content: str,
) -> None:
    policy_path = (
        repository_path
        / relative_path
    )
    policy_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    policy_path.write_text(
        content,
        encoding="utf-8",
    )


def public_resolver(
    _hostname: str,
    _port: int,
    **_kwargs,
):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("93.184.216.34", 443),
        )
    ]


def test_repository_without_policy_has_no_explicit_prohibition(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "README.md",
        "Example project.",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


@pytest.mark.parametrize(
    "policy_text",
    [
        "Do not use AI or LLM tools to contribute.",
        "AI-generated contributions will be closed.",
        (
            "Automated contributions and bot-generated pull requests "
            "are prohibited."
        ),
        "Contributions produced using generative AI are not accepted.",
        "Pull requests created with GitHub Copilot are prohibited.",
    ],
)
def test_explicit_ai_or_automation_contribution_policy_blocks(
    tmp_path: Path,
    policy_text: str,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        policy_text,
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.BLOCKED
    assert result.source == "CONTRIBUTING.md"
    assert result.evidence == policy_text


@pytest.mark.parametrize(
    "policy_text",
    [
        "AI-assisted contributions are welcome.",
        "We do not prohibit AI-assisted contributions.",
        "Our project discusses AI and automation.",
        "Our contributor guide mentions GitHub Copilot.",
        "Do not use AI for release-note translation.",
        "Automated builds run for every contribution.",
    ],
)
def test_non_prohibitive_or_unrelated_ai_language_does_not_block(
    tmp_path: Path,
    policy_text: str,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        policy_text,
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        ".github/CONTRIBUTING.md",
        "docs/contributing.md",
    ],
)
def test_nested_contributing_documents_are_discovered(
    tmp_path: Path,
    relative_path: str,
) -> None:
    write_policy(
        tmp_path,
        relative_path,
        "AI-generated contributions are not allowed.",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.BLOCKED
    assert result.source == relative_path


def test_github_community_profile_contributing_is_inspected(
    tmp_path: Path,
) -> None:
    content_url = (
        "https://api.github.com/repos/example/"
        "project/contents/CONTRIBUTING.md"
    )
    calls: list[str] = []

    def github_fetcher(
        url: str,
        **_kwargs,
    ):
        calls.append(url)

        if url.endswith("/community/profile"):
            return {
                "files": {
                    "contributing": {
                        "url": content_url,
                    }
                }
            }

        return {
            "encoding": "base64",
            "content": base64.b64encode(
                b"AI-generated contributions will be rejected."
            ).decode("ascii"),
        }

    result = check_contribution_policy(
        tmp_path,
        REPOSITORY_URL,
        github_fetcher=github_fetcher,
    )

    assert result.outcome == ContributionPolicyOutcome.BLOCKED
    assert result.source == (
        "GitHub community profile CONTRIBUTING"
    )
    assert content_url in calls


def test_absent_community_profile_contributing_does_not_block(
    tmp_path: Path,
) -> None:
    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


def test_unreadable_community_profile_contributing_is_inconclusive(
    tmp_path: Path,
) -> None:
    content_url = (
        "https://api.github.com/repos/example/"
        "project/contents/CONTRIBUTING.md"
    )

    def github_fetcher(
        url: str,
        **_kwargs,
    ):
        if url.endswith("/community/profile"):
            return {
                "files": {
                    "contributing": {
                        "url": content_url,
                    }
                }
            }

        raise contribution_policy_checker.GitHubProjectDownloadError(
            "Simulated GitHub failure"
        )

    result = check_contribution_policy(
        tmp_path,
        REPOSITORY_URL,
        github_fetcher=github_fetcher,
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert result.source == (
        "GitHub community profile CONTRIBUTING"
    )


def test_relative_local_policy_link_is_read_without_external_fetch(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        "Read our [contribution policy](docs/policy.md).",
    )
    write_policy(
        tmp_path,
        "docs/policy.md",
        "AI-assisted contributions are welcome.",
    )

    result = check_local_repository(
        tmp_path,
        external_fetcher=(
            lambda _url: pytest.fail(
                "A local policy path was fetched externally."
            )
        ),
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


def test_relative_local_policy_link_can_block(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        "Read our [contribution policy](docs/rules.md).",
    )
    write_policy(
        tmp_path,
        "docs/rules.md",
        "AI-generated contributions are not allowed.",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.BLOCKED
    assert result.source == "docs/rules.md"


def test_nested_local_policy_path_resolves_from_source_directory(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "docs/CONTRIBUTING.md",
        "Read the [contribution policy](policies/rules.md).",
    )
    write_policy(
        tmp_path,
        "docs/policies/rules.md",
        "AI-generated pull requests will be rejected.",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.BLOCKED
    assert result.source == "docs/policies/rules.md"


def test_repository_root_relative_policy_path_resolves_inside_repository(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "docs/CONTRIBUTING.md",
        "Read the [AI policy](/internal/rules.md).",
    )
    write_policy(
        tmp_path,
        "internal/rules.md",
        "AI-assisted contributions are welcome.",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )
    assert "internal/rules.md" in result.checked_sources


@pytest.mark.parametrize(
    "link",
    [
        "#contribution-policy",
        "mailto:maintainer@example.com",
        "javascript:alert('not-executed')",
        "tel:+15555550123",
    ],
)
def test_non_document_policy_links_are_ignored(
    tmp_path: Path,
    link: str,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        f"See the [contribution policy]({link}).",
    )

    result = check_local_repository(
        tmp_path,
        external_fetcher=(
            lambda _url: pytest.fail(
                "A non-document link was fetched."
            )
        ),
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


def test_authoritative_local_traversal_outside_repository_is_inconclusive(
    tmp_path: Path,
) -> None:
    outside_path = (
        tmp_path.parent
        / f"{tmp_path.name}-outside.md"
    )
    outside_path.write_text(
        "AI-assisted contributions are welcome.",
        encoding="utf-8",
    )
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        (
            "Read the [contribution policy](../"
            f"{outside_path.name})."
        ),
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert result.source == "CONTRIBUTING.md"
    assert "outside the repository" in (
        result.evidence or ""
    )


def test_missing_authoritative_local_policy_is_inconclusive(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        "Read the [contribution policy](docs/missing.md).",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert "docs/missing.md" in (
        result.evidence or ""
    )
    assert "does not exist" in (
        result.evidence or ""
    )


def test_oversized_authoritative_local_policy_is_inconclusive(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        "Read the [contribution policy](docs/rules.md).",
    )
    write_policy(
        tmp_path,
        "docs/rules.md",
        "x" * (
            contribution_policy_checker
            .MAX_LOCAL_POLICY_FILE_BYTES
            + 1
        ),
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert "bounded read limit" in (
        result.evidence or ""
    )


def test_local_policy_link_cycle_terminates(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        "Read the [contribution policy](docs/rules.md).",
    )
    write_policy(
        tmp_path,
        "docs/rules.md",
        "Return to the [contribution policy](../CONTRIBUTING.md).",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )
    assert result.checked_sources.count(
        "docs/rules.md"
    ) == 1


def test_pre_discovered_linked_policy_inherits_authority_for_next_hop(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        "Read the [contribution policy](docs/policy.md).",
    )
    write_policy(
        tmp_path,
        "docs/policy.md",
        "Then read the [contribution policy](missing/rules.md).",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert result.source == "docs/policy.md"
    assert "missing/rules.md" in (
        result.evidence or ""
    )


def test_duplicate_local_policy_links_are_read_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        (
            "[Contribution policy](docs/rules.md)\n"
            "[AI policy](docs/rules.md)"
        ),
    )
    write_policy(
        tmp_path,
        "docs/rules.md",
        "AI-assisted contributions are welcome.",
    )
    original_read_text = Path.read_text
    linked_reads = 0

    def counting_read_text(
        path: Path,
        *args,
        **kwargs,
    ) -> str:
        nonlocal linked_reads

        if path.name == "rules.md":
            linked_reads += 1

        return original_read_text(
            path,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        Path,
        "read_text",
        counting_read_text,
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )
    assert linked_reads == 1


def test_oversized_readme_is_not_authoritative_failure(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "README.md",
        "x" * (
            contribution_policy_checker
            .MAX_LOCAL_POLICY_FILE_BYTES
            + 1
        ),
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


def test_unreadable_heuristic_policy_file_is_not_authoritative_failure(
    tmp_path: Path,
) -> None:
    policy_path = (
        tmp_path
        / "automation-policy.md"
    )
    policy_path.write_bytes(
        b"\xff\xfe"
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "CONTRIBUTING.md",
        ".github/CONTRIBUTING.md",
        "docs/CONTRIBUTING.rst",
    ],
)
def test_unreadable_authoritative_contributing_is_inconclusive(
    tmp_path: Path,
    relative_path: str,
) -> None:
    policy_path = (
        tmp_path
        / relative_path
    )
    policy_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    policy_path.write_bytes(
        b"\xff\xfe"
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert result.source == relative_path


def test_authoritative_external_contribution_link_is_followed(
    tmp_path: Path,
) -> None:
    policy_url = "https://docs.example.org/contributing"
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        (
            "Read our [contribution policy]("
            f"{policy_url})."
        ),
    )
    fetched: list[str] = []

    def external_fetcher(url: str) -> ExternalPolicyPage:
        fetched.append(url)
        return ExternalPolicyPage(
            url=url,
            text=(
                "Do not use large language models to submit "
                "contributions."
            ),
            links=(),
        )

    result = check_local_repository(
        tmp_path,
        external_fetcher=external_fetcher,
    )

    assert result.outcome == ContributionPolicyOutcome.BLOCKED
    assert fetched == [policy_url]


def test_two_hop_external_ai_policy_is_discovered(
    tmp_path: Path,
) -> None:
    guide_url = "https://docs.example.org/contributing"
    ai_policy_url = "https://docs.example.org/policies/ai"
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        f"Read our [contribution guide]({guide_url}).",
    )
    pages = {
        guide_url: ExternalPolicyPage(
            url=guide_url,
            text="Project contribution guidelines.",
            links=(
                PolicyLink(
                    url=ai_policy_url,
                    label="AI policy",
                    nearby_text="AI policy for contributors",
                ),
            ),
        ),
        ai_policy_url: ExternalPolicyPage(
            url=ai_policy_url,
            text=(
                "Generative AI contributions are not accepted."
            ),
            links=(),
        ),
    }

    result = check_local_repository(
        tmp_path,
        external_fetcher=pages.__getitem__,
    )

    assert result.outcome == ContributionPolicyOutcome.BLOCKED
    assert result.source == ai_policy_url


def test_external_traversal_stops_at_depth_two(
    tmp_path: Path,
) -> None:
    guide_url = "https://docs.example.org/contributing"
    second_url = "https://docs.example.org/policies/ai"
    third_url = "https://docs.example.org/policies/llm"
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        f"Read the [contribution guide]({guide_url}).",
    )
    calls: list[str] = []

    def external_fetcher(url: str) -> ExternalPolicyPage:
        calls.append(url)

        if url == guide_url:
            links = (
                PolicyLink(
                    url=second_url,
                    label="AI policy",
                    nearby_text="AI policy",
                ),
            )
        elif url == second_url:
            links = (
                PolicyLink(
                    url=third_url,
                    label="LLM policy",
                    nearby_text="LLM policy",
                ),
            )
        else:
            raise AssertionError(
                "Traversal exceeded depth two."
            )

        return ExternalPolicyPage(
            url=url,
            text="No explicit prohibition here.",
            links=links,
        )

    result = check_local_repository(
        tmp_path,
        external_fetcher=external_fetcher,
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )
    assert calls == [guide_url, second_url]


def test_external_page_count_is_capped(
    tmp_path: Path,
) -> None:
    links = "\n".join(
        (
            f"[Contribution policy {index}]("
            f"https://docs{index}.example.org/contributing)"
        )
        for index in range(7)
    )
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        links,
    )
    calls: list[str] = []

    def external_fetcher(url: str) -> ExternalPolicyPage:
        calls.append(url)
        return ExternalPolicyPage(
            url=url,
            text="No explicit prohibition.",
            links=(),
        )

    result = check_local_repository(
        tmp_path,
        external_fetcher=external_fetcher,
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )
    assert len(calls) == (
        contribution_policy_checker
        .MAX_EXTERNAL_POLICY_PAGES
    )


def test_duplicate_external_url_is_fetched_once(
    tmp_path: Path,
) -> None:
    policy_url = "https://docs.example.org/contributing"
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        (
            f"[Contribution guide]({policy_url})\n"
            f"[Contribution policy]({policy_url})"
        ),
    )
    calls = 0

    def external_fetcher(url: str) -> ExternalPolicyPage:
        nonlocal calls
        calls += 1
        return ExternalPolicyPage(
            url=url,
            text="No explicit prohibition.",
            links=(),
        )

    result = check_local_repository(
        tmp_path,
        external_fetcher=external_fetcher,
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )
    assert calls == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/contributing",
        "https://localhost/contributing",
        "https://127.0.0.1/contributing",
        "https://10.0.0.1/contributing",
        "https://169.254.10.20/contributing",
    ],
)
def test_unsafe_external_policy_urls_are_rejected(
    url: str,
) -> None:
    with pytest.raises(
        ExternalPolicyFetchError,
    ):
        validate_external_policy_url(
            url,
            resolver=public_resolver,
        )


def test_hostname_resolving_to_private_address_is_rejected() -> None:
    def private_resolver(
        _hostname: str,
        _port: int,
        **_kwargs,
    ):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("192.168.1.10", 443),
            )
        ]

    with pytest.raises(
        ExternalPolicyFetchError,
        match="non-public",
    ):
        validate_external_policy_url(
            "https://policy.example.org/contributing",
            resolver=private_resolver,
        )


def test_redirect_to_private_target_is_rejected() -> None:
    handler = (
        contribution_policy_checker
        ._SafePolicyRedirectHandler(
            resolver=public_resolver
        )
    )

    with pytest.raises(
        ExternalPolicyFetchError,
    ):
        handler.redirect_request(
            Request(
                "https://public.example.org/contributing"
            ),
            None,
            302,
            "Found",
            {},
            "https://127.0.0.1/private-policy",
        )


class FakeHeaders:
    def __init__(
        self,
        content_type: str,
        content_length: int | None = None,
    ) -> None:
        self.content_type = content_type
        self.content_length = content_length

    def get_content_type(self) -> str:
        return self.content_type

    def get_content_charset(self) -> str:
        return "utf-8"

    def get(
        self,
        name: str,
    ) -> str | None:
        if (
            name == "Content-Length"
            and self.content_length is not None
        ):
            return str(self.content_length)

        return None


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        content_type: str,
        body: bytes,
        content_length: int | None = None,
    ) -> None:
        self.url = url
        self.headers = FakeHeaders(
            content_type,
            content_length,
        )
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class FakeOpener:
    def __init__(
        self,
        response: FakeResponse,
    ) -> None:
        self.response = response
        self.requests: list[Request] = []

    def open(
        self,
        request: Request,
        timeout: int,
    ) -> FakeResponse:
        assert timeout == 5
        self.requests.append(request)
        return self.response


def test_oversized_external_response_is_rejected() -> None:
    url = "https://docs.example.org/contributing"
    response = FakeResponse(
        url=url,
        content_type="text/plain",
        body=b"small",
        content_length=(
            contribution_policy_checker
            .MAX_EXTERNAL_POLICY_BYTES
            + 1
        ),
    )

    with pytest.raises(
        ExternalPolicyFetchError,
        match="too large",
    ):
        fetch_external_policy_page(
            url,
            resolver=public_resolver,
            opener=FakeOpener(response),
        )


def test_non_text_external_response_is_rejected() -> None:
    url = "https://docs.example.org/contributing"
    response = FakeResponse(
        url=url,
        content_type="application/octet-stream",
        body=b"binary",
    )

    with pytest.raises(
        ExternalPolicyFetchError,
        match="not text",
    ):
        fetch_external_policy_page(
            url,
            resolver=public_resolver,
            opener=FakeOpener(response),
        )


def test_github_token_is_not_sent_to_external_policy_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://docs.example.org/contributing"
    response = FakeResponse(
        url=url,
        content_type="text/plain",
        body=b"Contribution guide.",
    )
    opener = FakeOpener(response)
    monkeypatch.setenv(
        "GITHUB_TOKEN",
        "github-secret-token",
    )

    fetch_external_policy_page(
        url,
        resolver=public_resolver,
        opener=opener,
    )

    request_headers = {
        key.casefold(): value
        for key, value
        in opener.requests[0].header_items()
    }
    assert "authorization" not in request_headers
    assert "github-secret-token" not in str(
        request_headers
    )


def test_random_source_or_readme_urls_are_not_followed(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "src/example.py",
        'HELP_URL = "https://random.example.org/download"',
    )
    write_policy(
        tmp_path,
        "README.md",
        "See the [project demo](https://random.example.org/demo).",
    )

    result = check_local_repository(
        tmp_path,
        external_fetcher=(
            lambda _url: pytest.fail(
                "An unrelated URL was followed."
            )
        ),
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


def test_unretrievable_authoritative_policy_is_inconclusive(
    tmp_path: Path,
) -> None:
    policy_url = "https://docs.example.org/contributing"
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        f"Read the [contribution policy]({policy_url}).",
    )

    def fail_fetch(_url: str) -> ExternalPolicyPage:
        raise ExternalPolicyFetchError(
            "The policy page could not be retrieved."
        )

    result = check_local_repository(
        tmp_path,
        external_fetcher=fail_fetch,
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert result.source == "CONTRIBUTING.md"
    assert result.policy_url == policy_url


def test_insecure_authoritative_policy_link_is_inconclusive(
    tmp_path: Path,
) -> None:
    policy_url = "http://docs.example.org/contributing"
    write_policy(
        tmp_path,
        "CONTRIBUTING.md",
        f"Read the [contribution policy]({policy_url}).",
    )

    result = check_local_repository(
        tmp_path
    )

    assert result.outcome == ContributionPolicyOutcome.INCONCLUSIVE
    assert result.policy_url == policy_url
    assert "HTTPS" in (result.evidence or "")


def test_failed_unrelated_external_link_is_not_inconclusive(
    tmp_path: Path,
) -> None:
    write_policy(
        tmp_path,
        "README.md",
        "See [status](https://status.example.org/uptime).",
    )

    result = check_local_repository(
        tmp_path,
        external_fetcher=(
            lambda _url: pytest.fail(
                "An unrelated URL was fetched."
            )
        ),
    )

    assert result.outcome == (
        ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
    )


def test_public_run_statuses_are_unchanged() -> None:
    assert {status.value for status in RunStatus} == {
        "analyzing",
        "awaiting_plan_approval",
        "plan_approved",
        "running_workers",
        "workers_completed",
        "running_reviewer",
        "awaiting_final_approval",
        "final_approved",
        "applying_changes",
        "changes_applied",
        "running_tests",
        "tests_passed",
        "tests_failed",
        "committing",
        "committed",
        "pushing",
        "pushed",
        "creating_draft_pr",
        "completed",
        "failed",
    }
