from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EcosystemDefinition:
    name: str
    default_docker_image: str
    evidence_paths: tuple[str, ...]
    project_manifest_names: tuple[str, ...]
    default_runtime_version: str | None
    docker_image_template: str | None = None

    def docker_image_for_runtime(
        self,
        runtime_version: str | None,
    ) -> str:
        if (
            self.docker_image_template is None
            or runtime_version is None
        ):
            return self.default_docker_image

        return self.docker_image_template.format(
            runtime_version=runtime_version
        )


PYTHON_ECOSYSTEM = EcosystemDefinition(
    name="python",
    default_docker_image=(
        "ghcr.io/astral-sh/uv:"
        "python3.12-bookworm-slim"
    ),
    evidence_paths=(
        "pyproject.toml",
        "requirements*.txt",
        "uv.lock",
        "poetry.lock",
        "Pipfile",
        "tox.ini",
        "noxfile.py",
        ".python-version",
    ),
    project_manifest_names=(
        "pyproject.toml",
        "Pipfile",
        "tox.ini",
        "noxfile.py",
    ),
    default_runtime_version="3.12",
    docker_image_template=(
        "ghcr.io/astral-sh/uv:"
        "python{runtime_version}-bookworm-slim"
    ),
)

NODE_ECOSYSTEM = EcosystemDefinition(
    name="node",
    default_docker_image="node:22-bookworm-slim",
    evidence_paths=(
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        ".nvmrc",
        ".node-version",
    ),
    project_manifest_names=("package.json",),
    default_runtime_version="22",
    docker_image_template=(
        "node:{runtime_version}-bookworm-slim"
    ),
)


ECOSYSTEM_REGISTRY: dict[
    str,
    EcosystemDefinition,
] = {
    definition.name: definition
    for definition in (
        PYTHON_ECOSYSTEM,
        NODE_ECOSYSTEM,
    )
}


def get_ecosystem_definition(
    ecosystem: str,
) -> EcosystemDefinition:
    try:
        return ECOSYSTEM_REGISTRY[
            ecosystem.strip().lower()
        ]
    except KeyError as error:
        supported = ", ".join(
            sorted(ECOSYSTEM_REGISTRY)
        )
        raise ValueError(
            "Unsupported repository ecosystem "
            f"'{ecosystem}'. Registered ecosystems: "
            f"{supported}."
        ) from error


def registered_ecosystem_names() -> tuple[str, ...]:
    return tuple(sorted(ECOSYSTEM_REGISTRY))


def all_project_manifest_names() -> frozenset[str]:
    return frozenset(
        manifest_name
        for definition in ECOSYSTEM_REGISTRY.values()
        for manifest_name in definition.project_manifest_names
    )
