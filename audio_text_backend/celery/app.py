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
    task_routes={"audio_text_backend.action.tasks.process_audio": {"queue": "audio_processing"}},
)
