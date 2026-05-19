from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from headroom.api.deps import SettingsDep
from headroom.core.time_window import next_window_start_utc
from headroom.models.job import QueueType
from headroom.schemas.tasks import TaskResponse, TaskSubmit

router = APIRouter(tags=["tasks"])


def _to_response(job) -> TaskResponse:
    return TaskResponse(
        id=job.id,
        batch_id=job.batch_id,
        queue=job.queue,
        status=job.status,
        endpoint=job.endpoint,
        estimated_tokens=job.estimated_tokens,
        actual_tokens=job.actual_tokens,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def submit_task(payload: TaskSubmit, request: Request, settings: SettingsDep) -> TaskResponse:
    if payload.endpoint is not None:
        endpoint = settings.endpoint_by_name(payload.endpoint)
        if endpoint is None:
            raise HTTPException(status_code=400, detail=f"unknown endpoint: {payload.endpoint}")
    else:
        endpoint = settings.endpoint_by_model(payload.model)
        if endpoint is None:
            raise HTTPException(
                status_code=400,
                detail=f"cannot resolve unique endpoint for model {payload.model!r}; specify `endpoint`",
            )

    if payload.estimated_tokens > endpoint.capacity_tps:
        raise HTTPException(
            status_code=400,
            detail=(
                f"estimated_tokens {payload.estimated_tokens} exceeds endpoint "
                f"capacity {endpoint.capacity_tps}"
            ),
        )

    repo = request.app.state.repo
    job = await repo.create(
        queue=payload.queue,
        endpoint=endpoint.name,
        request={
            "model": payload.model,
            "messages": payload.messages,
            "parameters": payload.parameters,
        },
        estimated_tokens=payload.estimated_tokens,
    )

    queue_obj = (
        request.app.state.day_queue
        if payload.queue == QueueType.DAY
        else request.app.state.night_queue
    )
    enqueue_kwargs = dict(
        task_id=str(job.id),
        estimated_tokens=payload.estimated_tokens,
        endpoint=endpoint.name,
    )
    if payload.queue == QueueType.NIGHT:
        scheduled = int(next_window_start_utc(settings.pt_night_window_start_utc).timestamp())
        await queue_obj.enqueue("run_task", scheduled=scheduled, retries=0, **enqueue_kwargs)
    else:
        await queue_obj.enqueue("run_task", retries=0, **enqueue_kwargs)

    return _to_response(job)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, request: Request) -> TaskResponse:
    repo = request.app.state.repo
    job = await repo.get(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return _to_response(job)
