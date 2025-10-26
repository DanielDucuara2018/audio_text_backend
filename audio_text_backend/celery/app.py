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
    # Task routing for different queues
    task_routes={
        "audio_text_backend.action.tasks.process_audio": {
            "queue": Config.celery.queue_name,
            "routing_key": Config.celery.routing_key,
            "retry": True,
            "retry_policy": {
                "max_retries": Config.celery.retry_policy_max_retries,
                "interval_start": Config.celery.retry_policy_interval_start,
                "interval_step": Config.celery.retry_policy_interval_step,
                "interval_max": Config.celery.retry_policy_interval_max,
            },
        }
    },
)

# Explicit queue definitions for better control (string-based)
# celery_app.conf.task_queues = [
#     Config.celery.queue_name,
#     'default',  # Default queue for other tasks
# ]
