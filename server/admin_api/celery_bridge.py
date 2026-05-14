"""Indirection for Celery ``send_task`` so unit tests can mock without importing ``workers.*`` (S3 side effects)."""

from __future__ import annotations


def send_pipeline_task(
    name: str,
    *,
    args: list | None = None,
    kwargs: dict | None = None,
    queue: str,
) -> None:
    from workers.celery_app import celery_app

    celery_app.send_task(
        name,
        args=args or [],
        kwargs=kwargs or {},
        queue=queue,
    )
