from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog

from headroom.core.time_window import is_within_window, next_window_start_utc
from headroom.models.job import JobStatus

logger = structlog.get_logger()


class WindowClosed(Exception):
    """Raised to skip a night job whose window has closed."""


async def before_process(ctx: dict) -> None:
    job = ctx["job"]
    gates = ctx["gates"]
    settings = ctx["settings"]
    repo = ctx["repo"]
    queue_name = job.queue.name  # 'day' or 'night'

    kwargs = job.kwargs or {}
    task_id = kwargs["task_id"]
    estimated_tokens = kwargs["estimated_tokens"]
    endpoint_name = kwargs["endpoint"]
    reschedule_count = kwargs.get("reschedule_count", 0)

    gate = gates[endpoint_name]

    if queue_name == "night":
        now_utc = datetime.now(timezone.utc).time()
        if not is_within_window(
            now_utc,
            settings.pt_night_window_start_utc,
            settings.pt_night_window_end_utc,
        ):
            if reschedule_count >= settings.max_reschedules:
                await repo.update_status(
                    UUID(task_id),
                    JobStatus.FAILED,
                    error="max reschedules reached",
                    completed_at=datetime.now(timezone.utc),
                )
                logger.warning("night_job_max_reschedules", task_id=task_id)
                raise WindowClosed(f"task {task_id}: max reschedules reached")

            new_kwargs = {**kwargs, "reschedule_count": reschedule_count + 1}
            scheduled = int(
                next_window_start_utc(settings.pt_night_window_start_utc).timestamp()
            )
            night_queue = ctx["night_queue"]
            await night_queue.enqueue(
                job.function,
                scheduled=scheduled,
                retries=0,
                timeout=job.timeout,
                **new_kwargs,
            )
            logger.info(
                "night_job_rescheduled",
                task_id=task_id,
                reschedule_count=reschedule_count + 1,
                scheduled=scheduled,
            )
            raise WindowClosed(f"task {task_id}: window closed, rescheduled")

    await gate.wait_for_capacity(estimated_tokens)
    gate.reserve(estimated_tokens)
    ctx["tokens_reserved"] = True
    ctx["gate_ref"] = gate
    ctx["estimated_tokens"] = estimated_tokens

    await repo.update_status(
        UUID(task_id),
        JobStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        saq_job_id=job.key,
    )


async def after_process(ctx: dict) -> None:
    if not ctx.get("tokens_reserved"):
        return

    gate = ctx["gate_ref"]
    estimated_tokens = ctx["estimated_tokens"]
    job = ctx["job"]

    await gate.release(estimated_tokens)
    ctx["tokens_reserved"] = False

    if job.status == "complete" and isinstance(job.result, dict):
        actual = job.result.get("actual_token_count")
        if isinstance(actual, int):
            await gate.report_actual_usage(actual, estimated_tokens)
