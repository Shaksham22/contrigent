from uuid import UUID

from contrigent_api.models.project_context import (
    ProjectSource,
)
from contrigent_api.services.pull_request_documentation_runner import (
    run_pull_request_documentation,
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
    ensure_expected_run_branch,
    push_run_branch,
    rollback_run_branch,
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
    GitHubProjectDownloadError,
    get_authenticated_github_user,
    get_or_download_github_project,
    parse_github_issue_url,
)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from contrigent_api.models.run_record import Run
from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
)
from contrigent_api.services.issue_analysis_runner import (
    analyze_project,
    replan_after_review,
)
from contrigent_api.services.issue_analysis_runner import (
    analyze_project,
    replan_after_review,
    replan_after_test_failure,
)

from contrigent_api.services.run_memory_store import (
    InvalidRunTransitionError,
    RunNotFoundError,
    approve_plan,
    attach_analysis,
    finish_analysis_without_worker_work,
    complete_worker_work,
    create_run,
    fail_run,
    get_run,
    start_worker_work,
    start_revision_worker_work,
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
    start_worker_work,
    start_test_revision_worker_work,
    start_revision_worker_work,
    record_candidate_test_result,
    complete_review,
)

from contrigent_api.services.worker_runner import (
    build_project_with_proposed_files,
    merge_proposed_files,
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

    max_review_rounds: int = Field(
        default=2,
        ge=1,
        le=10,
    )

    max_testing_rounds: int = Field(
        default=2,
        ge=1,
        le=10,
    )


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
        max_review_rounds=(
            request.max_review_rounds
        ),
        max_testing_rounds=(
            request.max_testing_rounds
        ),
    )
    original_branch: str | None = None
    run_branch: str | None = None
    repository_path = None

    try:
        if (
        project.project_source
        == ProjectSource.GITHUB
    ):
            repository_path = (
                project.repository_path
            )

            (
                original_branch,
                run_branch,
            ) = create_run_branch(
                repository_path,
                run.id,
                base_remote="upstream",
            )

            run.original_branch = (
                original_branch
            )

            run.run_branch = (
                run_branch
            )
        analysis, _usage = (
            await analyze_project(
                project
            )
        )

        run = attach_analysis(
            run.id,
            analysis,
        )

        if (
            analysis.feasibility
            != Feasibility.FEASIBLE
            or not analysis.worker_assignments
        ):
            return finish_analysis_without_worker_work(
                run.id
            )

        return run

    except Exception:
        if (
            repository_path is not None
            and original_branch is not None
            and run_branch is not None
        ):
            try:
                rollback_run_branch(
                    repository_path,
                    original_branch,
                    run_branch,
                )
            except Exception:
                pass

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
        run = approve_plan(
            run_id
        )

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

        previous_reviewer_result = None

        while True:
            # Real GitHub candidates must pass
            # deterministic Docker validation before
            # they are allowed to reach the Reviewer.
            if (
                project.project_source
                == ProjectSource.GITHUB
            ):
                while True:
                    candidate_test_result = (
                        run_repository_tests(
                            project.repository_path,
                            proposed_files=(
                                run.proposed_files
                            ),
                        )
                    )

                    run = (
                        record_candidate_test_result(
                            run_id,
                            candidate_test_result,
                        )
                    )

                    if (
                        candidate_test_result.passed
                    ):
                        break

                    if (
                        run.testing_rounds_completed
                        >= run.max_testing_rounds
                    ):
                        return fail_run(
                            run_id
                        )

                    if run.analysis is None:
                        raise InvalidRunTransitionError(
                            "Cannot remediate tests "
                            "without an analysis."
                        )

                    current_worker_results = (
                        dict(
                            run.worker_results
                        )
                    )

                    current_proposed_files = (
                        list(
                            run.proposed_files
                        )
                    )

                    (
                        revised_analysis,
                        _usage,
                    ) = (
                        await replan_after_test_failure(
                            project,
                            run.analysis,
                            current_worker_results,
                            current_proposed_files,
                            candidate_test_result,
                        )
                    )

                    revision_project = (
                        build_project_with_proposed_files(
                            project,
                            current_proposed_files,
                        )
                    )

                    run = (
                        start_test_revision_worker_work(
                            run_id,
                            revised_analysis,
                        )
                    )

                    (
                        revised_worker_results,
                        revised_proposed_files,
                    ) = await run_assigned_workers(
                        revision_project,
                        revised_analysis,
                        candidate_test_result,
                    )

                    final_proposed_files = (
                        merge_proposed_files(
                            project,
                            current_proposed_files,
                            revised_proposed_files,
                        )
                    )

                    run = complete_worker_work(
                        run_id,
                        revised_worker_results,
                        final_proposed_files,
                    )

            run = start_review(
                run_id
            )

            reviewer_result = (
                await run_reviewer(
                    project,
                    run.analysis,
                    run.worker_results,
                    run.proposed_files,
                    previous_reviewer_result=(
                        previous_reviewer_result
                    ),
                    candidate_test_result=(
                        run.candidate_test_result
                    ),
                )
            )

            if (
                reviewer_result.recommendation
                == "approve"
            ):
                return complete_review(
                    run_id,
                    reviewer_result,
                )

            another_review_is_allowed = (
                run.review_rounds_completed
                + 1
                < run.max_review_rounds
            )

            # A Reviewer revision changes the
            # candidate. Therefore another Docker
            # round must be available before we
            # allow automatic remediation.
            another_test_is_allowed = (
                project.project_source
                != ProjectSource.GITHUB
                or (
                    run.testing_rounds_completed
                    < run.max_testing_rounds
                )
            )

            if (
                not another_review_is_allowed
                or not another_test_is_allowed
            ):
                return complete_review(
                    run_id,
                    reviewer_result,
                )

            if run.analysis is None:
                raise InvalidRunTransitionError(
                    "Cannot revise reviewed work "
                    "without an analysis."
                )

            current_worker_results = dict(
                run.worker_results
            )

            current_proposed_files = list(
                run.proposed_files
            )

            (
                revised_analysis,
                _usage,
            ) = await replan_after_review(
                project,
                run.analysis,
                current_worker_results,
                current_proposed_files,
                reviewer_result,
                run.candidate_test_result,
            )

            revision_project = (
                build_project_with_proposed_files(
                    project,
                    current_proposed_files,
                )
            )

            run = start_revision_worker_work(
                run_id,
                revised_analysis,
                reviewer_result,
            )

            (
                revised_worker_results,
                revised_proposed_files,
            ) = await run_assigned_workers(
                revision_project,
                revised_analysis,
            )

            final_proposed_files = (
                merge_proposed_files(
                    project,
                    current_proposed_files,
                    revised_proposed_files,
                )
            )

            run = complete_worker_work(
                run_id,
                revised_worker_results,
                final_proposed_files,
            )

            previous_reviewer_result = (
                reviewer_result
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
        fail_run(
            run_id
        )
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

        original_branch = (
            run.original_branch
        )

        run_branch = (
            run.run_branch
        )

        if (
            original_branch is None
            or run_branch is None
        ):
            raise InvalidRunTransitionError(
                "GitHub run branch information "
                "is missing."
            )

        ensure_expected_run_branch(
            repository_path,
            run_branch,
        )

        original_branch = (
            run.original_branch
        )

        run_branch = (
            run.run_branch
        )

        if (
            original_branch is None
            or run_branch is None
        ):
            raise InvalidRunTransitionError(
                "GitHub run branch information "
                "is missing."
            )

        ensure_expected_run_branch(
            repository_path,
            run_branch,
        )

        start_applying_changes(
            run.id
        )
        applied_paths = apply_approved_files(
            repository_path,
            run.proposed_files,
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
        fork_owner = (
            get_authenticated_github_user()
        )

        run = start_push(
            run.id
        )

        push_run_branch(
            repository_path,
            branch_name=run_branch,
            expected_upstream_url=(
                run.github_repository_url
            ),
            expected_fork_owner=(
                fork_owner
            ),
        )

        run = complete_push(
            run.id
        )

        run = start_draft_pr(
            run.id
        )

        pr_documentation = (
            run_pull_request_documentation(
            project=project,
            run=run,
            issue_number=(
                issue_location.issue_number
                ),
            )
        )
        



        
        pr_result = (
            create_draft_pull_request(
                repository_url=(
                    run.github_repository_url
                ),
                issue_url=(
                    run.github_issue_url
                ),
                head_owner=fork_owner,
                head_branch=run_branch,
                base_branch=original_branch,
                title=(
                    pr_documentation.title
                ),
                body=(
                    pr_documentation.body
                ),
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