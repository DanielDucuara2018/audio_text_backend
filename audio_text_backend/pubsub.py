"""Google Cloud Pub/Sub publisher helpers.

Automatically uses the Pub/Sub emulator when the PUBSUB_EMULATOR_HOST
environment variable is set (local development / CI).  In production the
google-cloud-pubsub client picks up Application Default Credentials from
the Cloud Run service account — no additional configuration is needed.
"""

import json
import logging
from concurrent.futures import TimeoutError as FuturesTimeoutError

from google.cloud import pubsub_v1

from audio_text_backend.config import Config

logger = logging.getLogger(__name__)

# Module-level publisher client (thread-safe, reuse across requests).
_publisher: pubsub_v1.PublisherClient | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _topic_path(topic: str) -> str:
    return _get_publisher().topic_path(Config.pubsub.project_id, topic)


# ------------------------------------------------------------------ publish --

# Maps Whisper model names to resource tier used for Cloud Run Job routing.
_MODEL_TIER: dict[str, str] = {
    "tiny": "small",
    "tiny.en": "small",
    "base": "small",
    "base.en": "small",
    "small": "small",
    "small.en": "small",
    "medium": "medium",
    "medium.en": "medium",
    "large": "large",
    "large-v1": "large",
    "large-v2": "large",
    "large-v3": "large",
    "turbo": "large",
}


def _model_tier(model: str) -> str:
    """Return the resource tier (small/medium/large) for a Whisper model name."""
    return _MODEL_TIER.get(model.lower(), "large")


def _publish_sync(topic: str, payload: dict, **attributes: str) -> None:
    """Publish a JSON payload to a Pub/Sub topic (blocking until acknowledged)."""
    publisher = _get_publisher()
    data = json.dumps(payload).encode()
    future = publisher.publish(_topic_path(topic), data, **attributes)
    try:
        message_id = future.result(timeout=10)
        logger.debug(f"Published to {topic}: message_id={message_id}")
    except FuturesTimeoutError:
        logger.error(f"Pub/Sub publish timed out for topic {topic}")
        raise


async def publish_job(job_id: str, filename: str, url: str, model: str) -> None:
    """Publish a transcription job request to the jobs topic.

    Sets the ``model_tier`` message attribute so that production Pub/Sub
    subscriptions with filters can route messages to the correct Cloud Run Job
    (audio-worker-small / audio-worker-medium / audio-worker-large).
    """
    tier = _model_tier(model)
    _publish_sync(
        Config.pubsub.jobs_topic,
        {"job_id": job_id, "filename": filename, "url": url, "model": model},
        model_tier=tier,
    )
    logger.info(f"Published job {job_id} (tier={tier}) to topic '{Config.pubsub.jobs_topic}'")


async def publish_status(
    job_id: str,
    status: str,
    *,
    result: str | None = None,
    language: str | None = None,
    language_probability: float | None = None,
    processing_time: float | None = None,
    message: str | None = None,
    error: str | None = None,
    progress: int | None = None,
) -> None:
    """Publish a job status update to the status topic."""
    payload: dict = {"job_id": job_id, "status": status, "type": "job_update"}
    if result is not None:
        payload["result"] = result
    if language is not None:
        payload["language"] = language
    if language_probability is not None:
        payload["language_probability"] = language_probability
    if processing_time is not None:
        payload["processing_time"] = processing_time
    if message is not None:
        payload["message"] = message
    if error is not None:
        payload["error"] = error
    if progress is not None:
        payload["progress"] = progress

    _publish_sync(Config.pubsub.status_topic, payload)
    logger.info(f"Published status '{status}' for job {job_id}")


# ---------------------------------------------------------- emulator setup ---


def ensure_topics_and_subscriptions() -> None:
    """Create topics and subscriptions if they do not already exist.

    Called once at local-worker startup when PUBSUB_EMULATOR_HOST is set.
    Safe to call repeatedly — creation is idempotent (ignores AlreadyExists).
    """
    from google.api_core.exceptions import AlreadyExists  # noqa: PLC0415

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    project_id = Config.pubsub.project_id

    for topic_id in (Config.pubsub.jobs_topic, Config.pubsub.status_topic):
        topic_path = publisher.topic_path(project_id, topic_id)
        try:
            publisher.create_topic(request={"name": topic_path})
            logger.info(f"Created topic: {topic_path}")
        except AlreadyExists:
            logger.debug(f"Topic already exists: {topic_path}")

    # Pull subscription for local-worker (jobs)
    jobs_sub_path = subscriber.subscription_path(project_id, Config.pubsub.jobs_subscription)
    jobs_topic_path = publisher.topic_path(project_id, Config.pubsub.jobs_topic)
    try:
        subscriber.create_subscription(request={"name": jobs_sub_path, "topic": jobs_topic_path})
        logger.info(f"Created subscription: {jobs_sub_path}")
    except AlreadyExists:
        logger.debug(f"Subscription already exists: {jobs_sub_path}")

    # Pull subscription for status (local monitoring / testing)
    status_sub_path = subscriber.subscription_path(project_id, Config.pubsub.status_subscription)
    status_topic_path = publisher.topic_path(project_id, Config.pubsub.status_topic)
    try:
        subscriber.create_subscription(
            request={"name": status_sub_path, "topic": status_topic_path}
        )
        logger.info(f"Created subscription: {status_sub_path}")
    except AlreadyExists:
        logger.debug(f"Subscription already exists: {status_sub_path}")

    # Push subscription for status → API (local only)
    push_sub_path = subscriber.subscription_path(project_id, "transcription-status-push")
    try:
        subscriber.create_subscription(
            request={
                "name": push_sub_path,
                "topic": status_topic_path,
                "push_config": {
                    "push_endpoint": Config.pubsub.api_push_endpoint,
                },
            }
        )
        logger.info(f"Created push subscription: {push_sub_path}")
    except AlreadyExists:
        logger.debug(f"Push subscription already exists: {push_sub_path}")
