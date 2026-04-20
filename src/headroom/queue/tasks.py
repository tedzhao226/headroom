from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog

from headroom.models.job import JobStatus
from headroom.services.provider import LLMRequest

logger = structlog.get_logger()


async def run_task(
    ctx: dict,
    *,
    task_id: str,
    estimated_tokens: int,
    endpoint: str,
    **_: object,
) -> dict:
    """SAQ job body.

    `before_process` has already gated capacity (and time window, for night jobs)
    and marked the job `running`. This function only calls the provider and
    writes the result row. `after_process` releases tokens and reconciles usage.
    """
    repo = ctx["repo"]
    provider = ctx["provider"]
    job_id = UUID(task_id)

    job = await repo.get(job_id)
    if job is None:
        raise LookupError(f"job {task_id} missing from repo")

    request = LLMRequest(
        model=job.request["model"],
        messages=job.request["messages"],
        parameters=job.request.get("parameters", {}),
    )

    try:
        response = await provider.call(request)
    except Exception as exc:
        logger.warning("run_task_failed", task_id=task_id, error=str(exc))
        await repo.update_status(
            job_id,
            JobStatus.FAILED,
            error=str(exc),
            completed_at=datetime.now(timezone.utc),
        )
        raise

    await repo.update_status(
        job_id,
        JobStatus.COMPLETE,
        result={
            "output": response["output"],
            "actual_token_count": response["actual_token_count"],
        },
        actual_tokens=response["actual_token_count"],
        completed_at=datetime.now(timezone.utc),
    )
    return dict(response)
