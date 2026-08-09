from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from contrigent_api.models.run_record import Run
from contrigent_api.services.issue_analysis_runner import analyze_sample_project
from contrigent_api.services.run_memory_store import (
    InvalidRunTransitionError,
    RunNotFoundError,
    approve_plan,
    attach_analysis,
    create_run,
    get_run,
)


router = APIRouter(
    prefix="/runs",
    tags=["runs"],
)


class CreateRunRequest(BaseModel):
    sample_project_name: str


@router.post("", response_model=Run)
async def start_run(request: CreateRunRequest) -> Run:
    run = create_run(request.sample_project_name)

    try:
        analysis, _usage = await analyze_sample_project(request.sample_project_name)

        return attach_analysis(
            run.id,
            analysis,
        )

    except Exception:
        run.status = "failed"
        raise


@router.get("/{run_id}", response_model=Run)
def read_run(run_id: UUID) -> Run:
    try:
        return get_run(run_id)

    except RunNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="Run not found.",
        ) from error


@router.post("/{run_id}/approve-plan", response_model=Run)
def approve_run_plan(run_id: UUID) -> Run:
    try:
        return approve_plan(run_id)

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