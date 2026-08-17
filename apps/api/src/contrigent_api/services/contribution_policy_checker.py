from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import (
    unquote,
    urljoin,
    urlparse,
    urlunparse,
)
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)
import base64
import binascii
import ipaddress
import os
import re
import socket

from contrigent_api.services.github_project_downloader import (
    GitHubProjectDownloadError,
    fetch_github_json,
    parse_github_repository_url,
)


MAX_LOCAL_POLICY_FILES = 50
MAX_LOCAL_POLICY_FILE_BYTES = 250_000
MAX_TOTAL_LOCAL_POLICY_BYTES = 1_000_000
MAX_LOCAL_POLICY_LINKED_FILES = 20
MAX_LOCAL_POLICY_LINK_DEPTH = 2
MAX_EXTERNAL_POLICY_PAGES = 5
MAX_EXTERNAL_POLICY_DEPTH = 2
MAX_EXTERNAL_POLICY_BYTES = 250_000
EXTERNAL_POLICY_TIMEOUT_SECONDS = 5
MAX_POLICY_EVIDENCE_CHARS = 400

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".cache",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "htmlcov",
    "node_modules",
    "target",
    "venv",
}

POLICY_TEXT_SUFFIXES = {
    "",
    ".markdown",
    ".md",
    ".rst",
    ".txt",
}

POLICY_FILENAME_CONCEPTS = (
    "ai",
    "automation",
    "contributing",
    "contribution",
    "contributor",
    "guidelines",
    "llm",
    "policy",
)

AI_CONCEPT_PATTERN = re.compile(
    r"(?:\bAI\b|artificial\s+intelligence|\bLLMs?\b|"
    r"large\s+language\s+models?|generative\s+AI|ChatGPT|"
    r"(?:GitHub\s+)?Copilot|"
    r"AI[-\s]+(?:assisted|generated)|bot[-\s]+generated|"
    r"\bbots?\b|\bautomation\b|automated\s+(?:contributions?|"
    r"submissions?|pull\s+requests?|interactions?))",
    re.IGNORECASE,
)

PROHIBITION_PATTERN = re.compile(
    r"(?:\bprohibit(?:ed|s)?\b|\bnot\s+allowed\b|"
    r"\bdo\s+not\s+use\b|\bdo\s+not\s+submit\b|"
    r"\bnot\s+(?:be\s+)?accepted\b|"
    r"\bwill\s+be\s+(?:rejected|closed)\b|"
    r"\bbanned\b|\bmust\s+not\b|\bmay\s+not\b|"
    r"\bwe\s+(?:do\s+not\s+accept|reject)\b)",
    re.IGNORECASE,
)

CONTRIBUTION_SCOPE_PATTERN = re.compile(
    r"(?:contribut\w*|pull\s+requests?|\bPRs?\b|submissions?|"
    r"patches?|source\s+code|\bcode\b|tests?|documentation|"
    r"\bdocs?\b|issues?|comments?)",
    re.IGNORECASE,
)

NEGATED_PROHIBITION_PATTERN = re.compile(
    r"(?:do\s+not\s+prohibit|not\s+prohibited|not\s+banned|"
    r"not\s+disallowed|AI[-\s]+assisted\s+contributions?\s+"
    r"(?:are\s+)?welcome|AI\s+tools?\s+may\s+be\s+used)",
    re.IGNORECASE,
)

DEPTH_ONE_LINK_PATTERN = re.compile(
    r"(?:contribut(?:ing|ion|or)|guidelines?|polic(?:y|ies))",
    re.IGNORECASE,
)

DEPTH_TWO_LINK_PATTERN = re.compile(
    r"(?:\bAI\b|\bLLM\b|artificial[-\s]+intelligence|"
    r"generative[-\s]+AI|automation|contribution[-\s]+policy|"
    r"project[-\s]+polic(?:y|ies)|polic(?:y|ies))",
    re.IGNORECASE,
)

MARKDOWN_LINK_PATTERN = re.compile(
    r"\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)",
)
PLAIN_URL_PATTERN = re.compile(
    r"https?://[^\s<>\[\]()]+",
    re.IGNORECASE,
)


class ContributionPolicyOutcome(str, Enum):
    NO_EXPLICIT_PROHIBITION = "no_explicit_prohibition"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class ContributionPolicyResult:
    outcome: ContributionPolicyOutcome
    source: str | None
    evidence: str | None
    checked_sources: tuple[str, ...]
    policy_url: str | None = None


@dataclass(frozen=True)
class PolicyDocument:
    source: str
    text: str
    local_path: Path | None = None
    authoritative: bool = False


@dataclass(frozen=True)
class LocalPolicyReadFailure:
    source: str
    evidence: str
    authoritative: bool


@dataclass(frozen=True)
class PolicyLink:
    url: str
    label: str
    nearby_text: str


@dataclass(frozen=True)
class ExternalPolicyPage:
    url: str
    text: str
    links: tuple[PolicyLink, ...]


@dataclass(frozen=True)
class _QueuedPolicyLink:
    link: PolicyLink
    source: str
    depth: int


@dataclass(frozen=True)
class _QueuedLocalPolicyLink:
    link: PolicyLink
    source_document: PolicyDocument
    depth: int


class ExternalPolicyFetchError(RuntimeError):
    pass


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[PolicyLink] = []
        self._ignored_depth = 0
        self._active_href: str | None = None
        self._active_label: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag_name = tag.casefold()

        if tag_name in {"script", "style"}:
            self._ignored_depth += 1
            return

        if self._ignored_depth or tag_name != "a":
            return

        attributes = dict(attrs)
        href = attributes.get("href")

        if href:
            self._active_href = href
            self._active_label = []

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        tag_name = tag.casefold()

        if tag_name in {"script", "style"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return

        if (
            tag_name == "a"
            and self._active_href is not None
        ):
            label = normalize_whitespace(
                " ".join(self._active_label)
            )
            self.links.append(
                PolicyLink(
                    url=self._active_href,
                    label=label,
                    nearby_text=label,
                )
            )
            self._active_href = None
            self._active_label = []

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self._ignored_depth:
            return

        self.text_parts.append(data)

        if self._active_href is not None:
            self._active_label.append(data)


class _SafePolicyRedirectHandler(
    HTTPRedirectHandler
):
    def __init__(self, resolver=None) -> None:
        super().__init__()
        self._resolver = resolver

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        validate_external_policy_url(
            new_url,
            resolver=self._resolver,
        )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def normalize_whitespace(
    value: str,
) -> str:
    return " ".join(
        value.split()
    )


def find_explicit_prohibition(
    text: str,
) -> str | None:
    contexts: list[str] = []

    for paragraph in re.split(
        r"\n\s*\n",
        text,
    ):
        normalized_paragraph = normalize_whitespace(
            paragraph
        )

        if not normalized_paragraph:
            continue

        sentences = re.split(
            r"(?<=[.!?])\s+|\n+",
            paragraph,
        )
        contexts.extend(
            normalize_whitespace(sentence)
            for sentence in sentences
            if normalize_whitespace(sentence)
        )

        if len(sentences) > 1:
            contexts.append(
                normalized_paragraph
            )

    seen_contexts: set[str] = set()

    for context in contexts:
        if context in seen_contexts:
            continue

        seen_contexts.add(context)

        if NEGATED_PROHIBITION_PATTERN.search(
            context
        ):
            continue

        if not AI_CONCEPT_PATTERN.search(
            context
        ):
            continue

        if not PROHIBITION_PATTERN.search(
            context
        ):
            continue

        if not CONTRIBUTION_SCOPE_PATTERN.search(
            context
        ):
            continue

        return context[
            :MAX_POLICY_EVIDENCE_CHARS
        ]

    return None


def _policy_file_priority(
    relative_path: Path,
) -> int | None:
    path_text = relative_path.as_posix().casefold()
    name = relative_path.name.casefold()
    suffix = relative_path.suffix.casefold()

    if suffix not in POLICY_TEXT_SUFFIXES:
        return None

    if name.startswith("contributing"):
        return 0

    if (
        path_text.startswith(".github/contributing")
        or path_text.startswith("docs/contributing")
    ):
        return 0

    if (
        len(relative_path.parts) == 1
        and name.startswith("readme")
    ):
        return 1

    if (
        path_text.startswith(
            ".github/pull_request_template"
        )
        or name.startswith("code_of_conduct")
        or name.startswith("governance")
    ):
        return 2

    name_tokens = set(
        re.findall(
            r"[a-z0-9]+",
            relative_path.stem.casefold(),
        )
    )

    if any(
        concept in name_tokens
        for concept in POLICY_FILENAME_CONCEPTS
    ):
        return 3

    return None


def _is_authoritative_local_policy_path(
    relative_path: Path,
) -> bool:
    path_text = relative_path.as_posix().casefold()
    name = relative_path.name.casefold()

    if (
        len(relative_path.parts) == 1
        and name.startswith("contributing")
    ):
        return True

    return (
        path_text.startswith(
            ".github/contributing"
        )
        or path_text.startswith(
            "docs/contributing"
        )
    )


def discover_local_policy_documents(
    repository_path: Path,
) -> tuple[
    list[PolicyDocument],
    list[LocalPolicyReadFailure],
]:
    repository_root = repository_path.resolve()
    candidates: list[tuple[int, Path, Path]] = []

    for folder, directory_names, file_names in os.walk(
        repository_root
    ):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in IGNORED_DIRECTORY_NAMES
            and not (
                Path(folder) / name
            ).is_symlink()
        )

        folder_path = Path(folder)

        for file_name in sorted(file_names):
            file_path = folder_path / file_name

            try:
                relative_path = file_path.relative_to(
                    repository_root
                )
            except ValueError:
                continue

            priority = _policy_file_priority(
                relative_path
            )

            if priority is None:
                continue

            candidates.append(
                (
                    priority,
                    relative_path,
                    file_path,
                )
            )

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1].as_posix().casefold(),
            item[1].as_posix(),
        )
    )
    documents: list[PolicyDocument] = []
    failures: list[
        LocalPolicyReadFailure
    ] = []
    total_bytes = 0

    for _, relative_path, file_path in candidates[
        :MAX_LOCAL_POLICY_FILES
    ]:
        source = relative_path.as_posix()
        authoritative = (
            _is_authoritative_local_policy_path(
                relative_path
            )
        )

        if file_path.is_symlink():
            failures.append(
                LocalPolicyReadFailure(
                    source=source,
                    evidence=(
                        "The policy file is a symbolic link and was not read."
                    ),
                    authoritative=authoritative,
                )
            )
            continue

        try:
            resolved_file = file_path.resolve()

            if not resolved_file.is_relative_to(
                repository_root
            ):
                failures.append(
                    LocalPolicyReadFailure(
                        source=source,
                        evidence=(
                            "The policy file resolves outside the repository."
                        ),
                        authoritative=authoritative,
                    )
                )
                continue

            file_size = file_path.stat().st_size

            if file_size > MAX_LOCAL_POLICY_FILE_BYTES:
                failures.append(
                    LocalPolicyReadFailure(
                        source=source,
                        evidence=(
                            "The policy file exceeds the bounded read limit."
                        ),
                        authoritative=authoritative,
                    )
                )
                continue

            if (
                total_bytes + file_size
                > MAX_TOTAL_LOCAL_POLICY_BYTES
            ):
                failures.append(
                    LocalPolicyReadFailure(
                        source=source,
                        evidence=(
                            "The total local policy read limit was reached."
                        ),
                        authoritative=authoritative,
                    )
                )
                continue

            content = file_path.read_text(
                encoding="utf-8"
            )
        except (
            OSError,
            UnicodeDecodeError,
        ):
            failures.append(
                LocalPolicyReadFailure(
                    source=source,
                    evidence=(
                        "The policy file could not be read as UTF-8 text."
                    ),
                    authoritative=authoritative,
                )
            )
            continue

        total_bytes += file_size
        documents.append(
            PolicyDocument(
                source=source,
                text=content,
                local_path=relative_path,
                authoritative=authoritative,
            )
        )

    return documents, failures


def _decode_github_content(
    response: object,
) -> str:
    if not isinstance(response, dict):
        raise ValueError(
            "GitHub returned an unexpected CONTRIBUTING response."
        )

    content = response.get("content")
    encoding = response.get("encoding")

    if (
        not isinstance(content, str)
        or encoding != "base64"
    ):
        raise ValueError(
            "GitHub did not return readable CONTRIBUTING content."
        )

    compact_content = "".join(
        content.split()
    )

    if len(compact_content) > (
        (MAX_LOCAL_POLICY_FILE_BYTES * 4 // 3)
        + 8
    ):
        raise ValueError(
            "GitHub CONTRIBUTING content exceeds the read limit."
        )

    try:
        decoded = base64.b64decode(
            compact_content,
            validate=True,
        )
    except (
        binascii.Error,
        ValueError,
    ) as error:
        raise ValueError(
            "GitHub returned invalid CONTRIBUTING content."
        ) from error

    if len(decoded) > MAX_LOCAL_POLICY_FILE_BYTES:
        raise ValueError(
            "GitHub CONTRIBUTING content exceeds the read limit."
        )

    return decoded.decode(
        "utf-8"
    )


def _is_safe_github_content_api_url(
    api_url: str,
) -> bool:
    try:
        parsed = urlparse(api_url)
        port = parsed.port
    except ValueError:
        return False

    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.github.com"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path.startswith("/repos/")
    )


def load_github_community_contributing(
    repository_url: str,
    *,
    github_fetcher=None,
) -> tuple[
    PolicyDocument | None,
    tuple[str, str] | None,
    list[str],
]:
    fetcher = github_fetcher or fetch_github_json
    owner, repository = parse_github_repository_url(
        repository_url
    )
    profile_url = (
        "https://api.github.com/repos/"
        f"{owner}/{repository}/community/profile"
    )
    checked_sources = [profile_url]

    try:
        profile = fetcher(
            profile_url,
            allow_not_found=True,
        )
    except GitHubProjectDownloadError:
        return None, None, checked_sources

    if not isinstance(profile, dict):
        return None, None, checked_sources

    files = profile.get("files")

    if not isinstance(files, dict):
        return None, None, checked_sources

    contributing = files.get("contributing")

    if not isinstance(contributing, dict):
        return None, None, checked_sources

    api_url = contributing.get("url")

    if (
        not isinstance(api_url, str)
        or not _is_safe_github_content_api_url(
            api_url
        )
    ):
        return (
            None,
            (
                "GitHub community profile CONTRIBUTING",
                "GitHub referenced an unsafe or invalid CONTRIBUTING URL.",
            ),
            checked_sources,
        )

    checked_sources.append(api_url)

    try:
        response = fetcher(api_url)
        content = _decode_github_content(
            response
        )
    except (
        GitHubProjectDownloadError,
        UnicodeDecodeError,
        ValueError,
    ):
        return (
            None,
            (
                "GitHub community profile CONTRIBUTING",
                f"The referenced policy could not be read: {api_url}",
            ),
            checked_sources,
        )

    return (
        PolicyDocument(
            source=(
                "GitHub community profile CONTRIBUTING"
            ),
            text=content,
            authoritative=True,
        ),
        None,
        checked_sources,
    )


def extract_policy_text_and_links(
    content: str,
    *,
    base_url: str | None = None,
    is_html: bool = False,
) -> tuple[str, tuple[PolicyLink, ...]]:
    links: list[PolicyLink] = []

    if is_html:
        parser = _VisibleHTMLParser()
        parser.feed(content)
        text = normalize_whitespace(
            " ".join(parser.text_parts)
        )
        links.extend(parser.links)
    else:
        text = normalize_whitespace(
            content
        )

        for match in MARKDOWN_LINK_PATTERN.finditer(
            content
        ):
            start = max(0, match.start() - 120)
            end = min(len(content), match.end() + 120)
            links.append(
                PolicyLink(
                    url=match.group(2),
                    label=normalize_whitespace(
                        match.group(1)
                    ),
                    nearby_text=normalize_whitespace(
                        content[start:end]
                    ),
                )
            )

        markdown_urls = {
            match.group(2)
            for match in MARKDOWN_LINK_PATTERN.finditer(
                content
            )
        }

        for match in PLAIN_URL_PATTERN.finditer(
            content
        ):
            url = match.group(0).rstrip(
                ".,;:!?\"'"
            )

            if url in markdown_urls:
                continue

            start = max(0, match.start() - 120)
            end = min(len(content), match.end() + 120)
            links.append(
                PolicyLink(
                    url=url,
                    label="",
                    nearby_text=normalize_whitespace(
                        content[start:end]
                    ),
                )
            )

    normalized_links: list[PolicyLink] = []
    seen_urls: set[str] = set()

    for link in links:
        resolved_url = (
            urljoin(base_url, link.url)
            if base_url is not None
            else link.url
        )

        if resolved_url in seen_urls:
            continue

        seen_urls.add(resolved_url)
        normalized_links.append(
            PolicyLink(
                url=resolved_url,
                label=link.label,
                nearby_text=link.nearby_text,
            )
        )

    return text, tuple(normalized_links)


def _link_is_policy_relevant(
    link: PolicyLink,
    depth: int,
) -> bool:
    parsed = urlparse(link.url)
    signal = normalize_whitespace(
        " ".join(
            (
                link.label,
                link.nearby_text,
                parsed.path.replace("-", " "),
            )
        )
    )
    pattern = (
        DEPTH_ONE_LINK_PATTERN
        if depth == 1
        else DEPTH_TWO_LINK_PATTERN
    )

    return pattern.search(signal) is not None


def _normalize_external_url(
    url: str,
) -> str:
    parsed = urlparse(
        url.strip()
    )
    hostname = parsed.hostname or ""
    netloc = hostname.casefold()

    if parsed.port not in {None, 443}:
        netloc += f":{parsed.port}"

    return urlunparse(
        (
            parsed.scheme.casefold(),
            netloc,
            parsed.path or "/",
            "",
            parsed.query,
            "",
        )
    )


def validate_external_policy_url(
    url: str,
    *,
    resolver=None,
) -> str:
    try:
        parsed = urlparse(
            url.strip()
        )
        port = parsed.port
    except ValueError as error:
        raise ExternalPolicyFetchError(
            "The policy URL is malformed."
        ) from error

    if parsed.scheme.casefold() != "https":
        raise ExternalPolicyFetchError(
            "External policy URLs must use HTTPS."
        )

    if (
        parsed.username is not None
        or parsed.password is not None
    ):
        raise ExternalPolicyFetchError(
            "External policy URLs cannot contain credentials."
        )

    if port not in {None, 443}:
        raise ExternalPolicyFetchError(
            "The external policy URL uses an unsupported port."
        )

    hostname = parsed.hostname

    if not hostname:
        raise ExternalPolicyFetchError(
            "The external policy URL has no hostname."
        )

    normalized_host = hostname.rstrip(".").casefold()

    if (
        normalized_host == "localhost"
        or normalized_host.endswith(".localhost")
    ):
        raise ExternalPolicyFetchError(
            "Localhost policy URLs are not allowed."
        )

    try:
        direct_address = ipaddress.ip_address(
            normalized_host
        )
    except ValueError:
        direct_address = None

    if (
        direct_address is not None
        and not direct_address.is_global
    ):
        raise ExternalPolicyFetchError(
            "The policy URL targets a non-public address."
        )

    address_resolver = resolver or socket.getaddrinfo

    try:
        resolved = address_resolver(
            normalized_host,
            443,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise ExternalPolicyFetchError(
            "The external policy hostname could not be resolved."
        ) from error

    addresses = {
        item[4][0]
        for item in resolved
        if len(item) >= 5
        and item[4]
    }

    if not addresses:
        raise ExternalPolicyFetchError(
            "The external policy hostname returned no addresses."
        )

    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(
                address.split("%", 1)[0]
            )
        except ValueError as error:
            raise ExternalPolicyFetchError(
                "The external policy hostname returned an invalid address."
            ) from error

        if not parsed_address.is_global:
            raise ExternalPolicyFetchError(
                "The external policy hostname resolves to a non-public address."
            )

    return _normalize_external_url(
        url
    )


def fetch_external_policy_page(
    url: str,
    *,
    resolver=None,
    opener=None,
) -> ExternalPolicyPage:
    normalized_url = validate_external_policy_url(
        url,
        resolver=resolver,
    )
    request = Request(
        normalized_url,
        headers={
            "Accept": (
                "text/html, text/plain, text/markdown, "
                "application/xhtml+xml"
            ),
            "User-Agent": "Contrigent",
        },
        method="GET",
    )
    request_opener = opener or build_opener(
        _SafePolicyRedirectHandler(
            resolver=resolver
        )
    )

    try:
        with request_opener.open(
            request,
            timeout=EXTERNAL_POLICY_TIMEOUT_SECONDS,
        ) as response:
            final_url = validate_external_policy_url(
                response.geturl(),
                resolver=resolver,
            )
            content_type = (
                response.headers
                .get_content_type()
                .casefold()
            )
            allowed_content_types = {
                "application/xhtml+xml",
                "text/html",
                "text/markdown",
                "text/plain",
                "text/x-markdown",
            }

            if content_type not in allowed_content_types:
                raise ExternalPolicyFetchError(
                    "The external policy response is not text."
                )

            content_length = response.headers.get(
                "Content-Length"
            )

            if (
                content_length is not None
                and int(content_length)
                > MAX_EXTERNAL_POLICY_BYTES
            ):
                raise ExternalPolicyFetchError(
                    "The external policy response is too large."
                )

            content_bytes = response.read(
                MAX_EXTERNAL_POLICY_BYTES + 1
            )

            if len(content_bytes) > MAX_EXTERNAL_POLICY_BYTES:
                raise ExternalPolicyFetchError(
                    "The external policy response is too large."
                )

            charset = (
                response.headers
                .get_content_charset()
                or "utf-8"
            )
            content = content_bytes.decode(
                charset,
                errors="replace",
            )
    except ExternalPolicyFetchError:
        raise
    except (
        HTTPError,
        LookupError,
        URLError,
        OSError,
        ValueError,
    ) as error:
        raise ExternalPolicyFetchError(
            "The external policy page could not be retrieved safely."
        ) from error

    text, links = extract_policy_text_and_links(
        content,
        base_url=final_url,
        is_html=(
            content_type
            in {
                "application/xhtml+xml",
                "text/html",
            }
        ),
    )

    return ExternalPolicyPage(
        url=final_url,
        text=text,
        links=links,
    )


def _blocked_result(
    source: str,
    evidence: str,
    checked_sources: list[str],
    *,
    policy_url: str | None = None,
) -> ContributionPolicyResult:
    return ContributionPolicyResult(
        outcome=ContributionPolicyOutcome.BLOCKED,
        source=source,
        evidence=evidence[
            :MAX_POLICY_EVIDENCE_CHARS
        ],
        checked_sources=tuple(checked_sources),
        policy_url=policy_url,
    )


def _inconclusive_result(
    source: str,
    evidence: str,
    checked_sources: list[str],
    *,
    policy_url: str | None = None,
) -> ContributionPolicyResult:
    return ContributionPolicyResult(
        outcome=(
            ContributionPolicyOutcome.INCONCLUSIVE
        ),
        source=source,
        evidence=evidence[
            :MAX_POLICY_EVIDENCE_CHARS
        ],
        checked_sources=tuple(checked_sources),
        policy_url=policy_url,
    )


def _is_external_http_policy_link(
    link: PolicyLink,
) -> bool:
    parsed = urlparse(
        link.url.strip()
    )

    return (
        parsed.scheme.casefold()
        in {"http", "https"}
        and bool(parsed.netloc)
    )


def _is_local_document_link(
    link: PolicyLink,
) -> bool:
    parsed = urlparse(
        link.url.strip()
    )

    return (
        not parsed.scheme
        and not parsed.netloc
        and bool(parsed.path)
    )


def _local_policy_reference_failure(
    queued: _QueuedLocalPolicyLink,
    reason: str,
    checked_sources: list[str],
) -> ContributionPolicyResult | None:
    if not queued.source_document.authoritative:
        return None

    return _inconclusive_result(
        queued.source_document.source,
        (
            "The explicitly referenced local policy "
            f"'{queued.link.url}' could not be inspected: "
            f"{reason}"
        ),
        checked_sources,
    )


def _local_linked_policy_result(
    repository_path: Path,
    documents: list[PolicyDocument],
    checked_sources: list[str],
) -> ContributionPolicyResult | None:
    repository_root = repository_path.resolve()
    queue: list[_QueuedLocalPolicyLink] = []
    seen_paths = {
        document.local_path.as_posix()
        for document in documents
        if document.local_path is not None
    }
    documents_by_path = {
        document.local_path.as_posix(): document
        for document in documents
        if document.local_path is not None
    }
    seen_path_authority = {
        document.local_path.as_posix(): (
            document.authoritative
        )
        for document in documents
        if document.local_path is not None
    }
    total_local_bytes = sum(
        len(
            document.text.encode(
                "utf-8"
            )
        )
        for document in documents
        if document.local_path is not None
    )
    linked_files_read = 0

    def enqueue_links(
        document: PolicyDocument,
        depth: int,
    ) -> None:
        if document.local_path is None:
            return

        _, links = extract_policy_text_and_links(
            document.text
        )

        for link in links:
            if (
                _link_is_policy_relevant(
                    link,
                    depth=1,
                )
                and _is_local_document_link(
                    link
                )
            ):
                queue.append(
                    _QueuedLocalPolicyLink(
                        link=link,
                        source_document=document,
                        depth=depth,
                    )
                )

    for document in list(documents):
        enqueue_links(
            document,
            depth=1,
        )

    while queue:
        queued = queue.pop(0)
        parsed = urlparse(
            queued.link.url.strip()
        )
        decoded_path = unquote(
            parsed.path
        )
        source_path = (
            queued.source_document.local_path
        )

        if source_path is None:
            continue

        if decoded_path.startswith("/"):
            candidate_path = (
                repository_root
                / decoded_path.lstrip("/")
            )
        else:
            candidate_path = (
                repository_root
                / source_path.parent
                / decoded_path
            )

        try:
            resolved_path = candidate_path.resolve()
        except OSError:
            result = _local_policy_reference_failure(
                queued,
                "the path could not be resolved safely.",
                checked_sources,
            )

            if result is not None:
                return result

            continue

        if not resolved_path.is_relative_to(
            repository_root
        ):
            result = _local_policy_reference_failure(
                queued,
                "the path resolves outside the repository.",
                checked_sources,
            )

            if result is not None:
                return result

            continue

        relative_path = resolved_path.relative_to(
            repository_root
        )
        source = relative_path.as_posix()

        if source in seen_paths:
            existing_document = (
                documents_by_path.get(
                    source
                )
            )

            if (
                queued.source_document.authoritative
                and existing_document is not None
                and not existing_document.authoritative
                and queued.depth
                < MAX_LOCAL_POLICY_LINK_DEPTH
            ):
                authoritative_document = (
                    PolicyDocument(
                        source=(
                            existing_document.source
                        ),
                        text=existing_document.text,
                        local_path=(
                            existing_document.local_path
                        ),
                        authoritative=True,
                    )
                )
                documents_by_path[
                    source
                ] = authoritative_document
                seen_path_authority[
                    source
                ] = True
                enqueue_links(
                    authoritative_document,
                    depth=queued.depth + 1,
                )

                continue

            if (
                existing_document is None
                and queued.source_document.authoritative
                and not seen_path_authority.get(
                    source,
                    False,
                )
            ):
                seen_path_authority[
                    source
                ] = True
            else:
                continue

        else:
            seen_paths.add(source)
            seen_path_authority[
                source
            ] = (
                queued.source_document.authoritative
            )

        checked_sources.append(source)

        if (
            linked_files_read
            >= MAX_LOCAL_POLICY_LINKED_FILES
        ):
            result = _local_policy_reference_failure(
                queued,
                "the bounded local policy-link file limit was reached.",
                checked_sources,
            )

            if result is not None:
                return result

            continue

        try:
            if not resolved_path.is_file():
                raise FileNotFoundError

            file_size = resolved_path.stat().st_size

            if file_size > MAX_LOCAL_POLICY_FILE_BYTES:
                result = _local_policy_reference_failure(
                    queued,
                    "the file exceeds the bounded read limit.",
                    checked_sources,
                )

                if result is not None:
                    return result

                continue

            if (
                total_local_bytes + file_size
                > MAX_TOTAL_LOCAL_POLICY_BYTES
            ):
                result = _local_policy_reference_failure(
                    queued,
                    "the total local policy read limit was reached.",
                    checked_sources,
                )

                if result is not None:
                    return result

                continue

            content = resolved_path.read_text(
                encoding="utf-8"
            )
        except FileNotFoundError:
            result = _local_policy_reference_failure(
                queued,
                "the file does not exist.",
                checked_sources,
            )

            if result is not None:
                return result

            continue
        except (
            OSError,
            UnicodeDecodeError,
        ):
            result = _local_policy_reference_failure(
                queued,
                "the file could not be read as UTF-8 text.",
                checked_sources,
            )

            if result is not None:
                return result

            continue

        linked_files_read += 1
        total_local_bytes += file_size
        linked_document = PolicyDocument(
            source=source,
            text=content,
            local_path=relative_path,
            authoritative=(
                queued.source_document.authoritative
            ),
        )
        documents.append(
            linked_document
        )
        documents_by_path[
            source
        ] = linked_document
        evidence = find_explicit_prohibition(
            content
        )

        if evidence is not None:
            return _blocked_result(
                source,
                evidence,
                checked_sources,
            )

        if queued.depth < MAX_LOCAL_POLICY_LINK_DEPTH:
            enqueue_links(
                linked_document,
                depth=queued.depth + 1,
            )

    return None


def _external_policy_result(
    documents: list[PolicyDocument],
    checked_sources: list[str],
    *,
    external_fetcher=None,
) -> ContributionPolicyResult | None:
    fetcher = (
        external_fetcher
        or fetch_external_policy_page
    )
    queue: list[_QueuedPolicyLink] = []

    for document in documents:
        _, links = extract_policy_text_and_links(
            document.text
        )

        for link in links:
            if _link_is_policy_relevant(
                link,
                depth=1,
            ) and _is_external_http_policy_link(
                link
            ):
                queue.append(
                    _QueuedPolicyLink(
                        link=link,
                        source=document.source,
                        depth=1,
                    )
                )

    seen_urls: set[str] = set()
    fetched_pages = 0

    while (
        queue
        and fetched_pages
        < MAX_EXTERNAL_POLICY_PAGES
    ):
        queued = queue.pop(0)

        try:
            normalized_url = _normalize_external_url(
                queued.link.url
            )
        except ValueError:
            normalized_url = queued.link.url

        if normalized_url in seen_urls:
            continue

        seen_urls.add(normalized_url)

        try:
            page = fetcher(
                queued.link.url
            )
        except ExternalPolicyFetchError as error:
            return _inconclusive_result(
                queued.source,
                str(error),
                checked_sources,
                policy_url=queued.link.url,
            )

        fetched_pages += 1
        checked_sources.append(page.url)
        seen_urls.add(page.url)
        evidence = find_explicit_prohibition(
            page.text
        )

        if evidence is not None:
            return _blocked_result(
                page.url,
                evidence,
                checked_sources,
                policy_url=page.url,
            )

        if queued.depth >= MAX_EXTERNAL_POLICY_DEPTH:
            continue

        page_host = urlparse(
            page.url
        ).hostname
        next_links = [
            link
            for link in page.links
            if _link_is_policy_relevant(
                link,
                depth=queued.depth + 1,
            )
            and _is_external_http_policy_link(
                link
            )
        ]
        next_links.sort(
            key=lambda link: (
                (
                    urlparse(link.url).hostname
                    != page_host
                ),
                link.url,
            )
        )

        for link in next_links:
            queue.append(
                _QueuedPolicyLink(
                    link=link,
                    source=page.url,
                    depth=queued.depth + 1,
                )
            )

    return None


def check_contribution_policy(
    repository_path: Path,
    repository_url: str,
    *,
    github_fetcher=None,
    external_fetcher=None,
) -> ContributionPolicyResult:
    documents, local_failures = (
        discover_local_policy_documents(
            repository_path
        )
    )
    checked_sources = [
        document.source
        for document in documents
    ]
    checked_sources.extend(
        failure.source
        for failure
        in local_failures
        if failure.source not in checked_sources
    )

    for document in documents:
        evidence = find_explicit_prohibition(
            document.text
        )

        if evidence is not None:
            return _blocked_result(
                document.source,
                evidence,
                checked_sources,
            )

    (
        community_document,
        community_failure,
        community_checked,
    ) = load_github_community_contributing(
        repository_url,
        github_fetcher=github_fetcher,
    )
    checked_sources.extend(
        community_checked
    )

    if community_document is not None:
        documents.append(
            community_document
        )
        evidence = find_explicit_prohibition(
            community_document.text
        )

        if evidence is not None:
            return _blocked_result(
                community_document.source,
                evidence,
                checked_sources,
            )

    local_link_result = (
        _local_linked_policy_result(
            repository_path,
            documents,
            checked_sources,
        )
    )

    if local_link_result is not None:
        return local_link_result

    external_result = _external_policy_result(
        documents,
        checked_sources,
        external_fetcher=external_fetcher,
    )

    if external_result is not None:
        return external_result

    authoritative_local_failure = next(
        (
            failure
            for failure in local_failures
            if failure.authoritative
        ),
        None,
    )

    if authoritative_local_failure is not None:
        return _inconclusive_result(
            authoritative_local_failure.source,
            authoritative_local_failure.evidence,
            checked_sources,
        )

    if community_failure is not None:
        source, evidence = community_failure
        return _inconclusive_result(
            source,
            evidence,
            checked_sources,
        )

    return ContributionPolicyResult(
        outcome=(
            ContributionPolicyOutcome.NO_EXPLICIT_PROHIBITION
        ),
        source=None,
        evidence=None,
        checked_sources=tuple(checked_sources),
    )


def build_policy_stop_message(
    result: ContributionPolicyResult,
) -> str:
    source = result.source or "Unknown policy source"
    evidence = result.evidence or "No readable evidence was available."

    if result.outcome == ContributionPolicyOutcome.BLOCKED:
        heading = "Contribution blocked by repository policy"
        explanation = (
            "Contrigent found an explicit policy that prohibits this "
            "type of AI-assisted or automated contribution."
        )
    else:
        heading = "Contribution policy could not be verified"
        explanation = (
            "The repository explicitly references contribution policy "
            "material that Contrigent could not safely retrieve or read."
        )

    policy_url_section = (
        f"\nPolicy URL:\n{result.policy_url}\n"
        if result.policy_url is not None
        else ""
    )

    return (
        f"{heading}\n\n"
        f"{explanation}\n\n"
        f"Source:\n{source}\n"
        f"{policy_url_section}\n"
        f"Evidence:\n{evidence}\n\n"
        "Contrigent stopped before repository testing or AI analysis.\n\n"
        "No source files were changed.\n"
        "No commit was created.\n"
        "No branch was pushed.\n"
        "No pull request was created.\n"
        "No issue comment was posted."
    )
