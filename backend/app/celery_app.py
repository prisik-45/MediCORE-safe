from celery import Celery

from backend.app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "supplier_intelligence",
    broker=settings.queue_url,
    backend=settings.queue_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_connect_timeout": 3,
        "socket_timeout": 10,
    },
    task_soft_time_limit=1500,
    task_time_limit=1800,
    worker_max_tasks_per_child=20,
    worker_max_memory_per_child=750000,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "backend.app.tasks.poll_email_account": {"queue": "ingest"},
    },
    beat_schedule={
        "poll-inbox-every-3-minutes": {
            "task": "backend.app.tasks.poll_inbox",
            "schedule": 180.0,
        }
    },
)
