from celery import Celery

from audio_text_backend.config import Config

celery_app = Celery(
    "audio_text_worker",
    broker=f"redis://{Config.redis.host}:{Config.redis.port}/0",
    backend=f"redis://{Config.redis.host}:{Config.redis.port}/0",
    include=["audio_text_backend.action.tasks"],
)

celery_app.conf.update(
    # Serialization settings
    task_serializer=Config.celery.serialization_format,
    accept_content=[Config.celery.serialization_format],
    result_serializer=Config.celery.serialization_format,
    timezone=Config.celery.timezone,
    enable_utc=Config.celery.enable_utc,
    task_track_started=Config.celery.task_track_started,
    # Worker configuration - reliability and performance
    task_acks_late=Config.celery.task_acks_late,
    worker_prefetch_multiplier=Config.celery.worker_prefetch_multiplier,
    worker_disable_rate_limits=Config.celery.worker_disable_rate_limits,
    worker_max_tasks_per_child=Config.celery.worker_max_tasks_per_child,
    # Task time limits for better resource management
    task_time_limit=Config.celery.task_time_limit,
    task_soft_time_limit=Config.celery.task_soft_time_limit,
    # Enhanced retry and reliability settings
    task_default_retry_delay=Config.celery.task_default_retry_delay,
    task_max_retries=Config.celery.task_max_retries,
    # Auto-scaling configuration
    worker_autoscaler=Config.celery.worker_autoscaler,
    # Task routing removed - queue is specified at task submission time via apply_async(queue=...)
    # This allows dynamic queue selection based on Whisper model size
    # Retry policy is configured per-task in apply_async() call
    broker_connection_retry_on_startup=True,
)
