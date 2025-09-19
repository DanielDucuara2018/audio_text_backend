from celery import Celery

from audio_text_backend.config import Config

celery_app = Celery(
    "audio_text_worker",
    broker=Config.celery.celery_broker_url,
    backend=Config.celery.celery_result_backend,
    include=["audio_text_backend.action.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Enhanced retry and reliability settings
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
    # Dead letter queue for failed tasks
    task_routes={
        "audio_text_backend.action.tasks.process_audio": {
            "queue": "audio_processing",
            "retry": True,
            "retry_policy": {
                "max_retries": 3,
                "interval_start": 0,
                "interval_step": 60,
                "interval_max": 300,
            },
        }
    },
)
