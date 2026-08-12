from uuid import UUID

from contrigent_api.models.project_context import (
    ProjectSource,
)

from contrigent_api.services.repository_test_runner import (
    run_repository_tests,
)

from contrigent_api.services.approved_file_applier import (
    apply_approved_files,
)
from contrigent_api.services.repository_git_manager import (
    create_approved_commit,
    create_run_branch,
    push_run_branch,
    rollback_run_branch,
)
from contrigent_api.services.github_project_downloader import (
    get_or_download_github_project,
)
from contrigent_api.services.downloaded_github_project_reader import (
    load_downloaded_github_project,
)
from contrigent_api.services.project_reader import (
    load_project,
)
from contrigent_api.services.github_pull_request_creator import (
    GitHubPullRequestError,
    build_pull_request_body,
    create_draft_pull_request,
    get_github_token,
    get_issue_title,
)

from contrigent_api.services.github_project_downloader import (
    get_or_download_github_project,
    parse_github_issue_url,
)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from contrigent_api.models.run_record import Run
from contrigent_api.services.issue_analysis_runner import (
    analyze_project,
)
from contrigent_api.services.run_memory_store import (
    InvalidRunTransitionError,
    RunNotFoundError,
    approve_plan,
    attach_analysis,
    complete_worker_work,
    create_run,
    fail_run,
    get_run,
    start_worker_work,
    complete_review,
    start_review,
    approve_final_changes,
    start_applying_changes,
    start_commit,
    complete_commit,
    start_push,
    complete_push,
    start_draft_pr,
    complete_draft_pr,
    complete_applying_changes,
    start_repository_tests,
    complete_repository_tests,
)

from contrigent_api.services.worker_runner import (
    run_assigned_workers,
)

from contrigent_api.services.reviewer_runner import (
    run_reviewer,
)


router = APIRouter(
    prefix="/runs",
    tags=["runs"],
)


class CreateRunRequest(BaseModel):
    project_name: str | None = None
    github_issue_url: str | None = None
    github_repository_url: str | None = None


@router.post("", response_model=Run)
async def start_run(
    request: CreateRunRequest,
) -> Run:
    using_project = (
        request.project_name is not None
    )

    using_github = (
        request.github_issue_url is not None
        or request.github_repository_url is not None
    )

    if using_project and using_github:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide either a sample project "
                "or GitHub URLs, not both."
            ),
        )

    if using_project:
        project = load_project(
            request.project_name,
            ProjectSource.SAMPLE,
        )
    else:
        if (
            request.github_issue_url is None
            or request.github_repository_url is None
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Both github_issue_url and "
                    "github_repository_url are required."
                ),
            )

        downloaded_project = (
            get_or_download_github_project(
                request.github_issue_url,
                request.github_repository_url,
            )
        )

        project = (
            load_downloaded_github_project(
                downloaded_project.project_name
            )
        )

    run = create_run(
        project.project_name,
        project.project_source,
        github_issue_url=(
            request.github_issue_url
            if project.project_source
            == ProjectSource.GITHUB
            else None
        ),
        github_repository_url=(
            request.github_repository_url
            if project.project_source
            == ProjectSource.GITHUB
            else None
        ),
    )

    try:
        analysis, _usage = (
            await analyze_project(
                project
            )
        )

        return attach_analysis(
            run.id,
            analysis,
        )

    except Exception:
        fail_run(run.id)
        raise


@router.post(
    "/{run_id}/approve-plan",
    response_model=Run,
)
async def approve_run_plan(
    run_id: UUID,
) -> Run:
    try:
        run = approve_plan(run_id)

        run = start_worker_work(
            run_id
        )

        project = load_project(
            run.project_name,
            run.project_source,
        )

        if run.analysis is None:
            raise InvalidRunTransitionError(
                "Cannot run workers without an analysis."
            )

        worker_results, proposed_files = (
            await run_assigned_workers(
                project,
                run.analysis,
            )
        )

        run = complete_worker_work(
            run_id,
            worker_results,
            proposed_files,
        )

        run = start_review(
            run_id
        )

        reviewer_result = await run_reviewer(
            project,
            run.analysis,
            run.worker_results,
            run.proposed_files,
        )

        return complete_review(
            run_id,
            reviewer_result,
        )

    except RunNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Run not found.",
        ) from error

    except InvalidRunTransitionError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except Exception:
        fail_run(run_id)
        raise


@router.post(
    "/{run_id}/approve-final",
    response_model=Run,
)
def approve_run_final_changes(
    run_id: UUID,
) -> Run:
    original_branch: str | None = None
    run_branch: str | None = None
    repository_path = None
    commit_created = False

    try:
        existing_run = get_run(
            run_id
        )

        if (
            existing_run.project_source
            == ProjectSource.GITHUB
        ):
            # Fail before touching the repository if
            # PR authentication is not configured.
            get_github_token()

        run = approve_final_changes(
            run_id
        )

        if (
            run.project_source
            != ProjectSource.GITHUB
        ):
            return run

        if (
            run.github_issue_url is None
            or run.github_repository_url is None
        ):
            raise InvalidRunTransitionError(
                "GitHub run metadata is incomplete."
            )

        project = load_project(
            run.project_name,
            run.project_source,
        )

        repository_path = (
            project.repository_path
        )

        start_applying_changes(
            run.id
        )

        (
            original_branch,
            run_branch,
        ) = create_run_branch(
            repository_path,
            run.id,
        )

        applied_paths = (
            apply_approved_files(
                repository_path,
                run.proposed_files,
            )
        )

        applied_files = [
            path.relative_to(
                repository_path.resolve()
            ).as_posix()
            for path in applied_paths
        ]

        run = complete_applying_changes(
            run.id,
            original_branch=original_branch,
            run_branch=run_branch,
            applied_files=applied_files,
        )

        run = start_repository_tests(
            run.id
        )

        test_result = run_repository_tests(
            repository_path
        )

        run = complete_repository_tests(
            run.id,
            test_result,
        )

        # Failed tests are a normal gated outcome.
        # Never commit or push them.
        if not test_result.passed:
            return run

        issue_location = (
            parse_github_issue_url(
                run.github_issue_url
            )
        )

        issue_title = get_issue_title(
            project.issue
        )

        commit_message = (
            f"Fix issue "
            f"#{issue_location.issue_number}"
        )

        run = start_commit(
            run.id
        )

        commit_sha = create_approved_commit(
            repository_path,
            expected_branch=run_branch,
            approved_files=run.applied_files,
            commit_message=commit_message,
        )

        commit_created = True

        run = complete_commit(
            run.id,
            commit_sha=commit_sha,
            commit_message=commit_message,
        )

        run = start_push(
            run.id
        )

        push_run_branch(
            repository_path,
            branch_name=run_branch,
            expected_repository_url=(
                run.github_repository_url
            ),
        )

        run = complete_push(
            run.id
        )

        run = start_draft_pr(
            run.id
        )

        test_summary = (
            f"exit code "
            f"{test_result.exit_code}; "
            f"{test_result.duration_seconds}s"
        )

        pr_body = build_pull_request_body(
            issue_number=(
                issue_location.issue_number
            ),
            analysis_summary=(
                run.analysis.summary
                if run.analysis is not None
                else "Approved repository changes."
            ),
            test_summary=test_summary,
        )

        pr_result = (
            create_draft_pull_request(
                repository_url=(
                    run.github_repository_url
                ),
                issue_url=(
                    run.github_issue_url
                ),
                head_branch=run_branch,
                base_branch=original_branch,
                title=issue_title,
                body=pr_body,
            )
        )

        return complete_draft_pr(
            run.id,
            pr_number=pr_result.number,
            pr_url=pr_result.url,
        )

    except RunNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except InvalidRunTransitionError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except GitHubPullRequestError as error:
        try:
            fail_run(run_id)
        except Exception:
            pass

        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error

    except Exception:
        # Before a commit exists, Contrigent can safely
        # discard its temporary run branch.
        #
        # After a commit exists, preserve the branch and
        # commit for diagnosis/recovery.
        if (
            not commit_created
            and repository_path is not None
            and original_branch is not None
            and run_branch is not None
        ):
            rollback_run_branch(
                repository_path,
                original_branch,
                run_branch,
            )

        try:
            fail_run(run_id)
        except Exception:
            pass

        raise