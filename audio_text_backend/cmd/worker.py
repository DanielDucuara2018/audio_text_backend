"""Cloud Run Job entrypoint for audio transcription.

Triggered by a per-tier Pub/Sub push subscription that calls the Cloud Run
Jobs execution endpoint.  On startup the worker pulls exactly **one** message
from the corresponding pull subscription (``transcription-jobs-sub-{tier}``),
processes it, and exits.

The pull subscription is managed by Terraform and persists independently of
the push subscription used to trigger the job — so the message payload is
always available when the container starts.

Environment variables
---------------------
AUDIO_TEXT_WORKER_TIER_ENV  — ``small`` | ``medium`` | ``large``  (required)

Exit codes
----------
0   — job completed (or no message available within deadline).
≠ 0 — job failed; Pub/Sub retries via the push subscription with exponential
      back-off up to the configured retry limit.
"""

import asyncio
import json
import logging
import sys

from google.cloud import pubsub_v1

from audio_text_backend import db
from audio_text_backend.cmd.job import JobPayload, process_job
from audio_text_backend.config import Config, bootstrap_configuration

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)


_TIER_TO_SUBSCRIPTION = {
    "small": lambda: Config.pubsub.jobs_subscription_small,
    "medium": lambda: Config.pubsub.jobs_subscription_medium,
    "large": lambda: Config.pubsub.jobs_subscription_large,
}


def _pull_one_message() -> (
    tuple[pubsub_v1.subscriber.message.Message, JobPayload, pubsub_v1.SubscriberClient, str] | None
):
    tier = Config.worker.tier.lower()
    if tier not in _TIER_TO_SUBSCRIPTION:
        raise RuntimeError(
            f"AUDIO_TEXT_WORKER_TIER_ENV must be one of {list(_TIER_TO_SUBSCRIPTION)}; got '{tier}'"
        )

    subscription_name = _TIER_TO_SUBSCRIPTION[tier]()
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(Config.pubsub.project_id, subscription_name)

    logger.info("[worker] Pulling message from %s", subscription_path)
    try:
        response = subscriber.pull(
            request={"subscription": subscription_path, "max_messages": 1},
            timeout=30,
        )
    except Exception as exc:
        logger.error(
            "[worker] Failed to pull from subscription %s: %s",
            subscription_path,
            exc,
            exc_info=True,
        )
        raise

    if not response.received_messages:
        logger.warning("[worker] No message available — spurious trigger, exiting 0")
        return None

    received = response.received_messages[0]
    try:
        payload = JobPayload(**json.loads(received.message.data.decode()))
    except Exception as exc:
        logger.error("Failed to decode Pub/Sub message %s: %s", received, exc, exc_info=True)
        # Malformed message — nack so it can be retried / dead-lettered.
        subscriber.modify_ack_deadline(
            request={
                "subscription": subscription_path,
                "ack_ids": [received.ack_id],
                "ack_deadline_seconds": 0,
            }
        )
        raise RuntimeError(f"Failed to decode Pub/Sub message: {exc}") from exc

    return received, payload, subscriber, subscription_path


async def _run() -> None:
    bootstrap_configuration()
    await db.init()

    pulled = _pull_one_message()
    if pulled is None:
        return  # spurious trigger

    received, payload, subscriber, subscription_path = pulled

    try:
        await process_job(payload)
    except Exception:
        # Nack: return the message to the subscription so the push trigger
        # retries the execution via its retry policy.
        subscriber.modify_ack_deadline(
            request={
                "subscription": subscription_path,
                "ack_ids": [received.ack_id],
                "ack_deadline_seconds": 0,
            }
        )
        raise  # non-zero exit
    else:
        subscriber.acknowledge(
            request={"subscription": subscription_path, "ack_ids": [received.ack_id]}
        )


def main() -> None:
    try:
        asyncio.run(_run())
    except Exception:
        logger.exception("[worker] Unhandled exception — exiting 1")
        logging.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
