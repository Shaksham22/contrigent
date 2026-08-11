from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from contrigent_api.models.run_record import Run
from contrigent_api.services.issue_analysis_runner import (
    analyze_sample_project,
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
)
from contrigent_api.services.sample_project_reader import (
    load_sample_project,
)
from contrigent_api.services.worker_runner import (
    run_assigned_workers,
)


router = APIRouter(
    prefix="/runs",
    tags=["runs"],
)


class CreateRunRequest(BaseModel):
    sample_project_name: str


@router.post("", response_model=Run)
async def start_run(
    request: CreateRunRequest,
) -> Run:
    run = create_run(
        request.sample_project_name
    )

    try:
        analysis, _usage = (
            await analyze_sample_project(
                request.sample_project_name
            )
        )

        return attach_analysis(
            run.id,
            analysis,
        )

    except Exception:
        fail_run(run.id)
        raise


@router.get(
    "/{run_id}",
    response_model=Run,
)
def read_run(
    run_id: UUID,
) -> Run:
    try:
        return get_run(run_id)

    except RunNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Run not found.",
        ) from error


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

        sample_project = load_sample_project(
            run.sample_project_name
        )

        if run.analysis is None:
            raise InvalidRunTransitionError(
                "Cannot run workers without an analysis."
            )

        worker_results, proposed_files = (
            await run_assigned_workers(
                sample_project,
                run.analysis,
            )
        )

        return complete_worker_work(
            run_id,
            worker_results,
            proposed_files,
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