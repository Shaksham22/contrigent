import argparse

from contrigent_api.services.github_project_downloader import (
    download_github_project,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download a GitHub issue and clone "
            "its repository for Contrigent."
        )
    )

    parser.add_argument(
        "issue_url",
        help="Full GitHub issue URL.",
    )

    parser.add_argument(
        "repository_url",
        help="Full GitHub repository URL.",
    )

    args = parser.parse_args()

    project = download_github_project(
        issue_url=args.issue_url,
        repository_url=args.repository_url,
    )

    print()
    print("GitHub project downloaded successfully.")
    print(
        f"Project name: {project.project_name}"
    )
    print(
        f"Issue file: {project.issue_file}"
    )
    print(
        f"Repository: {project.repository_folder}"
    )


if __name__ == "__main__":
    main()