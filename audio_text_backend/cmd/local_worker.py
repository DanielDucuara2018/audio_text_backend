"""Local development worker that simulates Cloud Run Jobs.

Pulls job messages from the Pub/Sub emulator's jobs subscription and runs
transcription in-process, mirroring the Cloud Run Job execution model exactly.

On startup it creates all required topics and subscriptions in the emulator
(idempotent — safe to restart without side-effects).

The Pub/Sub emulator pushes status messages to the API's
``POST /api/v1/pubsub/status`` endpoint, so the full production data flow
is exercised locally without any code changes.

Usage (via docker-compose)
--------------------------
The service is started automatically by ``docker-compose up``.  The
``PUBSUB_EMULATOR_HOST`` environment variable must be set so the
google-cloud-pubsub client targets the emulator instead of Google Cloud.
"""

import asyncio
import json
import logging
from concurrent.futures import Future as ConcurrentFuture

from google.cloud import pubsub_v1

from audio_text_backend import db
from audio_text_backend import pubsub as pubsub_module
from audio_text_backend.cmd.job import JobPayload, process_job
from audio_text_backend.config import Config, bootstrap_configuration

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


async def _process_job(payload: dict) -> None:
    """Async job processing — delegates to shared ``process_job`` in ``cmd.job``."""
    await process_job(JobPayload(**payload))


def _make_callback(loop: asyncio.AbstractEventLoop):
    """Return a Pub/Sub streaming-pull callback that dispatches to the async event loop."""

    def callback(message: pubsub_v1.subscriber.message.Message) -> None:
        try:
            payload: dict = json.loads(message.data.decode())
        except Exception as exc:
            logger.error(f"[local-worker] Failed to decode message: {exc}")
            message.nack()
            return

        logger.debug(f"[local-worker] Received message: {payload.get('job_id')}")
        future: ConcurrentFuture = asyncio.run_coroutine_threadsafe(_process_job(payload), loop)
        try:
            future.result(timeout=900)  # 15-minute hard limit per job
            message.ack()
        except Exception as exc:
            logger.error(
                f"[local-worker] Processing failed for job {payload.get('job_id')}: {exc}",
                exc_info=True,
            )
            message.nack()

    return callback


async def _run_worker() -> None:
    bootstrap_configuration()
    await db.init()

    # Create topics and subscriptions in the emulator (idempotent).
    pubsub_module.ensure_topics_and_subscriptions()

    loop = asyncio.get_running_loop()
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(
        Config.pubsub.project_id, Config.pubsub.jobs_subscription
    )

    streaming_pull = subscriber.subscribe(
        subscription_path,
        callback=_make_callback(loop),
    )

    logger.info(f"[local-worker] Listening on {subscription_path}")

    # Keep the event loop alive so coroutines dispatched from the gRPC callback
    # thread via run_coroutine_threadsafe() can execute.
    stop_future: asyncio.Future = loop.create_future()

    def _on_pull_done(f: ConcurrentFuture) -> None:
        exc = f.exception()
        if exc:
            logger.error(f"[local-worker] Streaming pull terminated unexpectedly: {exc}")
        loop.call_soon_threadsafe(stop_future.set_result, None)

    streaming_pull.add_done_callback(_on_pull_done)

    try:
        await stop_future
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("[local-worker] Cancelling streaming pull...")
        streaming_pull.cancel()
        try:
            streaming_pull.result(timeout=5)
        except Exception:
            pass


def main() -> None:
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
