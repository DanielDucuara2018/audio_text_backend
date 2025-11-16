import asyncio
import json
import logging
from datetime import datetime
from typing import Any, overload

from fastapi import WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis

from audio_text_backend.action.tasks import process_audio
from audio_text_backend.config import Config
from audio_text_backend.model.transcription_job import JobStatus, TranscriptionJob
from audio_text_backend.utils import idun

logger = logging.getLogger(__name__)


async def create(filename: str, url: str, model: str) -> TranscriptionJob:
    """Start audio transcription job.

    Args:
        filename: Name of the audio file to transcribe
        url: URL/path to the audio file
        model: Whisper model to use (tiny, base, small, medium, large-v2, large-v3)

    Returns:
        TranscriptionJob instance with job details

    """
    # Create job record in database
    job = TranscriptionJob(
        filename=filename, url=url, status=JobStatus.PENDING, whisper_model=model
    ).create()

    async with JobUpdateManager() as manager:
        # Add job to Redis-backed tracking (shared across all Cloud Run instances)
        await manager._add_job_to_redis(job.id)
        await manager._start_listening()

    # Get queue configuration for the selected model
    queue_config = Config.celery.queues.get(model, Config.celery.queues.get("default"))
    queue_name = queue_config.queue_name

    logger.info(f"Job {job.id}: Routing to queue '{queue_name}' for model '{model}'")

    # Start background processing with Celery using dynamic queue routing
    task = process_audio.apply_async(
        args=[job.id, job.filename, model],
        queue=queue_name,
        retry=True,
        retry_policy={
            "max_retries": queue_config.retry_policy_max_retries,
            "interval_start": queue_config.retry_policy_interval_start,
            "interval_step": queue_config.retry_policy_interval_step,
            "interval_max": queue_config.retry_policy_interval_max,
        },
    )

    logger.info(f"Started Celery task {task.id} for job {job.id} on queue '{queue_name}'")
    return job


@overload
def read(job_id: str) -> TranscriptionJob: ...
@overload
def read(**kwargs) -> list[TranscriptionJob]: ...
def read(job_id: str | None = None, **kwargs) -> TranscriptionJob | list[TranscriptionJob]:
    if job_id:
        logger.info("Reading event: %s", job_id)
        return TranscriptionJob.get(id=job_id)
    else:
        logger.info("Reading all events")
        return TranscriptionJob.find(**kwargs)


class JobUpdateManager:
    _instance = None

    # Redis keys for distributed state (shared across all Cloud Run instances)
    REDIS_ACTIVE_JOBS_KEY = "audio_text:active_jobs"  # Set of job IDs being tracked

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if JobUpdateManager._instance is self and not hasattr(self, "active_connections"):
            self.active_connections: list[WebSocket] = []
            self.job_connections: dict[str, WebSocket] = {}
            self.redis_client = None
            self.pubsub = None
            self._listener_task = None
            self._context_count = 0
            self._active_job_ids: set[str] = set()
            self._job_lock = asyncio.Lock()
            self._listener_lock = asyncio.Lock()
            self._context_lock = asyncio.Lock()
            self._connection_lock = asyncio.Lock()

    async def __aenter__(self):
        """Async context manager entry - ensure Redis client is ready."""
        await self._get_redis_client()
        async with self._context_lock:
            self._context_count += 1
            logger.info(
                f"JobUpdateManager context entered (active contexts: {self._context_count})"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - clean up resources only when last context exits."""
        async with self._context_lock:
            self._context_count = max(0, self._context_count - 1)
            logger.info(
                f"JobUpdateManager context exiting (remaining contexts: {self._context_count})"
            )
            context_count = self._context_count

        if context_count == 0:
            # Check if there are still pending/processing jobs that need listening
            pending_jobs = await self._get_pending_jobs()

            if pending_jobs:
                logger.info(
                    f"Last context exiting but {len(pending_jobs)} jobs still pending/processing - "
                    f"keeping listener alive: {pending_jobs}"
                )
                await self._close_all_websockets()
                # Don't stop listener or cleanup Redis - jobs still need updates
            else:
                logger.info("Last context exiting with no pending jobs - cleaning up all resources")
                await self._close_all_websockets()
                await self.stop_listening()
                await self._cleanup_redis_resources()
                logger.info("All resources cleaned up successfully")
        else:
            logger.info(
                f"Context exited but {context_count} contexts still active - keeping resources"
            )

        return False  # Don't suppress exceptions

    async def _get_redis_client(self):
        """Get or create async Redis client."""
        if not self.redis_client:
            async with self._listener_lock:
                if not self.redis_client:
                    self.redis_client = await aioredis.from_url(
                        f"redis://{Config.redis.host}:{Config.redis.port}/0"
                    )
                    self.pubsub = self.redis_client.pubsub()
        return self.redis_client

    async def connect(self, websocket: WebSocket, job_id: str):
        """Connect WebSocket and start Redis listener if needed."""
        await websocket.accept()
        await self._add_connection(websocket, job_id)
        await self._start_listening()

    async def _add_connection(self, websocket: WebSocket, job_id: str):
        """Add a new WebSocket connection."""
        async with self._connection_lock:
            # Handle existing connection for same job_id
            if job_id in self.job_connections:
                logger.warning(f"Replacing existing connection for job {job_id}")
                old_websocket = self.job_connections[job_id]
                self._remove_connection_unsafe(old_websocket, job_id, delete_job=False)

            self.active_connections.append(websocket)
            self.job_connections[job_id] = websocket
            logger.debug(
                f"Added WebSocket connection for job {job_id}. Total connections: {len(self.active_connections)}"
            )

    async def _start_listening(self):
        """Start listening for Redis messages."""
        async with self._listener_lock:
            if self._listener_task and not self._listener_task.done():
                logger.debug("Redis listener already running")
                return

            await self._subscribe_redis_channel()
            self._listener_task = asyncio.create_task(self._listen_for_updates())
            logger.info("Started Redis listener for WebSocket updates")

    async def _subscribe_redis_channel(self):
        """Initialize Redis client and pubsub subscription."""
        try:
            await self.pubsub.subscribe(Config.redis.pub_sub_channel)
        except Exception as e:
            logger.error(f"Failed to start Redis listener: {e}")
            raise e

    async def _listen_for_updates(self):
        """Background task that listens for Redis messages."""
        logger.info("Redis listener started")
        try:
            while True:
                await self._process_redis_messages()
        except asyncio.CancelledError:
            logger.info("Redis listener cancelled")
            raise  # Re-raise to properly handle cancellation
        except Exception as e:
            logger.error(f"Fatal error in Redis listener: {e}")
        finally:
            logger.info("Redis listener stopped")

    async def _process_redis_messages(self):
        """Process incoming Redis messages with timeout handling."""
        try:
            message = await self.pubsub.get_message(timeout=1.0)

            if message is not None and message["type"] == "message":
                await self._handle_redis_message(message)

            # Small delay to prevent tight loop
            await asyncio.sleep(0.01)

        except asyncio.TimeoutError:
            # Timeout is expected, continue listening
            pass
        except Exception as e:
            logger.error(f"Error in Redis listener loop: {e}")
            await asyncio.sleep(1)  # Wait before retrying

    async def _handle_redis_message(self, message):
        """Handle a single Redis message and forward to WebSocket."""
        try:
            data = json.loads(message["data"])
            job_id = data.get("job_id")

            logger.debug(f"Received Redis message for job {job_id}: {data}")

            await self._update_db_job_status(job_id, data)
            if job_id in self.job_connections:
                await self._send_websocket_update(job_id, data)
            else:
                logger.debug(f"No WebSocket connection for job {job_id}, DB updated only")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode Redis message: {e}")
        except Exception as e:
            logger.error(f"Error processing Redis message: {e}")

    async def _send_websocket_update(self, job_id: str, data: dict):
        """Send update to WebSocket connection for a specific job."""
        websocket = self.job_connections[job_id]
        try:
            await websocket.send_json(data)
            logger.info(f"Sent WebSocket update for job {job_id}: {data.get('message', '')}")

            # Close WebSocket if job reached terminal state
            status = data.get("status")
            if status in ["completed", "failed"]:
                logger.info(f"Job {job_id} reached terminal state '{status}' - closing WebSocket")
                await websocket.close(code=1000, reason=f"Job {status}")
                await self.remove_connection(websocket, job_id)
        except Exception as ws_error:
            logger.warning(f"WebSocket send failed for job {job_id}: {ws_error}")
            # Only remove from tracking - let FastAPI handle the connection closure
            await self.remove_connection(websocket, job_id)

    async def _update_db_job_status(self, job_id: str, data: dict[str, Any]):
        """Update the job status in the database."""
        status = data["status"]
        try:
            job = TranscriptionJob.get(id=job_id)
            job = job.update(
                status=status,
                result_text=data.get("result"),
                processing_time_seconds=data.get("processing_time"),
                error=f"{data.get('message')} {data.get('error')}" if status == "failed" else None,
                language=data.get("language"),
                language_probability=data.get("language_probability"),
            )
            logger.info(f"Updated job {job_id} status to {job.status}")

            # Remove from active tracking if job reached terminal state
            if status in ["completed", "failed"]:
                await self._remove_from_active_jobs(job_id, status)
        except Exception as e:
            logger.error(f"Failed to update job {job_id} status to {status}: {e}")

    async def disconnect(self, websocket: WebSocket, job_id: str):
        """Disconnect and remove a WebSocket connection from tracking.

        Note: WebSocket closure is handled by the FastAPI router layer.
        This method only removes the connection from internal tracking.
        """
        await self.remove_connection(websocket, job_id)
        logger.debug(
            f"Removed WebSocket tracking for job {job_id}. Remaining connections: {len(self.active_connections)}"
        )

    async def _remove_from_active_jobs(self, job_id: str, status: str):
        """Thread-safe removal of job from active tracking."""
        async with self._job_lock:
            self._active_job_ids.discard(job_id)
            logger.debug(f"Removed job {job_id} from active tracking (status: {status})")

        # Also remove from Redis (shared state across all instances)
        await self._remove_job_from_redis(job_id)

    async def _add_job_to_redis(self, job_id: str):
        """Add job to Redis-backed tracking (distributed across Cloud Run instances)."""
        try:
            await self.redis_client.sadd(self.REDIS_ACTIVE_JOBS_KEY, job_id)
            # Also add to local cache
            async with self._job_lock:
                self._active_job_ids.add(job_id)
            logger.info(f"Added job {job_id} to distributed tracking (Redis + local cache)")
        except Exception as e:
            logger.error(f"Failed to add job {job_id} to Redis tracking: {e}")
            # Fallback: at least add to local cache
            async with self._job_lock:
                self._active_job_ids.add(job_id)

    async def _remove_job_from_redis(self, job_id: str):
        """Remove job from Redis-backed tracking (distributed)."""
        try:
            await self.redis_client.srem(self.REDIS_ACTIVE_JOBS_KEY, job_id)
            logger.debug(f"Removed job {job_id} from distributed tracking (Redis)")
        except Exception as e:
            logger.warning(f"Failed to remove job {job_id} from Redis tracking: {e}")

    def _remove_connection_unsafe(
        self, websocket: WebSocket, job_id: str, *, delete_job: bool = True
    ):
        """Remove a WebSocket connection (internal, no lock - caller must hold lock)."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if delete_job and job_id in self.job_connections:
            del self.job_connections[job_id]

    async def remove_connection(
        self, websocket: WebSocket, job_id: str, *, delete_job: bool = True
    ):
        """Remove a WebSocket connection (thread-safe)."""
        async with self._connection_lock:
            self._remove_connection_unsafe(websocket, job_id, delete_job=delete_job)

    async def _close_all_websockets(self):
        """Clear all WebSocket connection tracking during shutdown.

        Note: This only clears internal tracking. Individual WebSocket connections
        are managed by their respective FastAPI router contexts.
        """
        async with self._connection_lock:
            if not self.active_connections:
                return

            logger.info(
                f"Clearing tracking for {len(self.active_connections)} WebSocket connections during shutdown"
            )

            # Clear all connection tracking
            self.active_connections.clear()
            self.job_connections.clear()
            logger.info("All WebSocket connection tracking cleared")

    async def stop_listening(self):
        """Stop the Redis listener."""
        logger.info("Stopping Redis listener")
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                logger.debug("Redis listener task cancelled successfully")
            finally:
                self._listener_task = None

    async def _cleanup_redis_resources(self):
        """Clean up Redis client and pubsub resources."""
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe(Config.redis.pub_sub_channel)
                await self.pubsub.close()
            except Exception as e:
                logger.error(f"Error closing pubsub: {e}")

        if self.redis_client:
            try:
                await self.redis_client.close()
                self.redis_client = None
                self.pubsub = None
            except Exception as e:
                logger.error(f"Error closing Redis client: {e}")

    async def _get_pending_jobs(self) -> set[str]:
        """Get set of job IDs that are pending or processing.

        Returns:
            Set of job IDs that still need Redis listener updates (from Redis + DB)

        """
        try:
            # Query database for jobs in pending or processing state
            pending_jobs = TranscriptionJob.find(status=[JobStatus.PENDING, JobStatus.PROCESSING])
            job_ids_db = {job.id for job in pending_jobs}

            # Get jobs from Redis (shared across all Cloud Run instances)
            job_ids_redis = await self.redis_client.smembers(self.REDIS_ACTIVE_JOBS_KEY)
            job_ids_redis = {
                job_id.decode() if isinstance(job_id, bytes) else job_id for job_id in job_ids_redis
            }

            # Also include jobs from local cache
            async with self._job_lock:
                job_ids_local = self._active_job_ids.copy()

            # Union of all sources (most comprehensive view)
            all_job_ids = job_ids_db | job_ids_redis | job_ids_local

            logger.debug(
                f"Found {len(all_job_ids)} pending/processing jobs "
                f"(DB: {len(job_ids_db)}, Redis: {len(job_ids_redis)}, Local: {len(job_ids_local)})"
            )
            return all_job_ids
        except Exception as e:
            logger.error(f"Error querying pending jobs: {e}")
            # Fallback to local cache only if distributed state fails
            async with self._job_lock:
                return self._active_job_ids.copy()


async def establish_connection(job_id: str, websocket: WebSocket):
    """Establish WebSocket connection for job updates using context manager.

    Note: WebSocket lifecycle (accept/close) is managed by FastAPI router.
    This function handles business logic: Redis pub/sub and connection tracking.
    """
    # Generate unique ID for this connection to track it in logs
    connection_id = idun("websocket")
    logger.info(f"[{connection_id}] WebSocket handler starting for job: {job_id}")

    async with JobUpdateManager() as manager:
        try:
            await manager.connect(websocket, job_id)
            logger.info(f"[{connection_id}] WebSocket connected for job: {job_id}")

            await _send_connection_confirmation(websocket, job_id, connection_id)
            await _handle_websocket_lifecycle(websocket, job_id, manager, connection_id)
        except WebSocketDisconnect:
            logger.info(f"[{connection_id}] WebSocket disconnected for job: {job_id}")
        except Exception as e:
            logger.error(f"[{connection_id}] WebSocket error for job {job_id}: {e}")
            await _handle_websocket_error(websocket, job_id, e)
        finally:
            # Only remove from tracking - FastAPI router handles connection closure
            await manager.remove_connection(websocket, job_id)
            logger.info(
                f"[{connection_id}] WebSocket connection tracking cleanup completed for job: {job_id}"
            )


async def _send_connection_confirmation(websocket: WebSocket, job_id: str, connection_id: str):
    """Send initial connection confirmation to client."""
    confirmation_message = {
        "type": "connected",
        "job_id": job_id,
        "connection_id": connection_id,  # Include connection ID for debugging
        "message": "Connected to job updates",
        "timestamp": datetime.now().isoformat(),
    }

    try:
        await websocket.send_json(confirmation_message)
        logger.debug(f"[{connection_id}] Sent connection confirmation for job: {job_id}")
    except Exception as e:
        logger.error(
            f"[{connection_id}] Failed to send connection confirmation for job {job_id}: {e}"
        )
        raise


async def _handle_websocket_lifecycle(
    websocket: WebSocket, job_id: str, manager: "JobUpdateManager", connection_id: str
):
    """Handle WebSocket lifecycle including keepalive and client messages."""
    consecutive_ping_failures = 0
    max_ping_failures = 3  # Disconnect after 3 failed pings

    logger.info(f"[{connection_id}] Starting lifecycle loop for job: {job_id}")

    while True:
        try:
            await _process_client_message(websocket, job_id, connection_id)
            consecutive_ping_failures = 0
        except asyncio.TimeoutError:
            consecutive_ping_failures = await _handle_timeout_with_ping(
                websocket,
                job_id,
                consecutive_ping_failures,
                max_ping_failures,
                manager,
                connection_id,
            )
            if consecutive_ping_failures >= max_ping_failures:
                logger.info(f"[{connection_id}] Max ping failures reached, exiting lifecycle loop")
                break
        except WebSocketDisconnect:
            logger.info(f"[{connection_id}] Client disconnected for job: {job_id}")
            await manager.remove_connection(websocket, job_id)
            break
        except Exception as e:
            consecutive_ping_failures = await _handle_error_with_message(
                websocket,
                job_id,
                consecutive_ping_failures,
                max_ping_failures,
                manager,
                e,
                connection_id,
            )
            if consecutive_ping_failures >= max_ping_failures:
                logger.info(f"[{connection_id}] Max errors reached, exiting lifecycle loop")
                break

    logger.info(f"[{connection_id}] Lifecycle loop ended for job: {job_id}")


async def _handle_timeout_with_ping(
    websocket: WebSocket,
    job_id: str,
    consecutive_ping_failures: int,
    max_ping_failures: int,
    manager: "JobUpdateManager",
    connection_id: str,
) -> int:
    """Handle timeout by sending ping and tracking failures."""
    try:
        await _send_keepalive_ping(websocket, connection_id)
        consecutive_ping_failures = 0
    except Exception as ping_error:
        consecutive_ping_failures = await _handle_error_with_message(
            websocket,
            job_id,
            consecutive_ping_failures,
            max_ping_failures,
            manager,
            ping_error,
            connection_id,
        )
    return consecutive_ping_failures


async def _handle_error_with_message(
    websocket: WebSocket,
    job_id: str,
    consecutive_ping_failures: int,
    max_ping_failures: int,
    manager: "JobUpdateManager",
    error: Exception,
    connection_id: str,
) -> int:
    """Handle errors during message processing."""
    consecutive_ping_failures += 1
    logger.warning(
        f"[{connection_id}] message failed for job {job_id} "
        f"({consecutive_ping_failures}/{max_ping_failures}): {error}"
    )

    if consecutive_ping_failures >= max_ping_failures:
        logger.info(f"[{connection_id}] Connection dead for job {job_id} - closing")
        await manager.remove_connection(websocket, job_id)
    else:
        # Small delay to prevent tight loop on repeated errors
        await asyncio.sleep(0.1)

    return consecutive_ping_failures


async def _process_client_message(websocket: WebSocket, job_id: str, connection_id: str):
    """Process incoming client messages with timeout."""
    # Reduced timeout to detect disconnects faster
    data = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)

    # Echo back for connection testing
    echo_message = {
        "type": "echo",
        "data": data,
        "job_id": job_id,
        "connection_id": connection_id,
        "timestamp": datetime.now().isoformat(),
    }

    await websocket.send_json(echo_message)
    logger.debug(f"[{connection_id}] Echoed client message for job {job_id}: {data}")


async def _send_keepalive_ping(websocket: WebSocket, connection_id: str):
    """Send keepalive ping to maintain connection."""
    ping_message = {
        "type": "ping",
        "connection_id": connection_id,
        "timestamp": datetime.now().isoformat(),
        "message": "Connection keepalive",
    }

    try:
        await websocket.send_json(ping_message)
        logger.debug(f"[{connection_id}] Sent keepalive ping")
    except Exception as e:
        logger.warning(f"[{connection_id}] Failed to send keepalive ping: {e}")
        raise


async def _handle_websocket_error(websocket: WebSocket, job_id: str, error: Exception):
    """Handle WebSocket errors and send error message to client if possible."""
    error_message = {
        "type": "error",
        "job_id": job_id,
        "message": "WebSocket connection error",
        "error": str(error),
        "timestamp": datetime.now().isoformat(),
    }

    try:
        await websocket.send_json(error_message)
    except Exception as send_error:
        logger.error(f"Failed to send error message for job {job_id}: {send_error}")
