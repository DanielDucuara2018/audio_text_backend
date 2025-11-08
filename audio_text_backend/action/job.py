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


def create(filename: str, url: str, mode: str) -> TranscriptionJob:
    """Start audio transcription job."""
    # Create job record in database
    job = TranscriptionJob(filename=filename, url=url, status=JobStatus.PENDING).create()
    # Start background processing with Celery
    task_id = process_audio.delay(
        job.id, job.filename, mode
    )  # TODO check if it can be added to DB TranscriptionJob
    logger.info(f"Started Celery task {task_id} for job {job.id}")
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

    async def __aenter__(self):
        """Async context manager entry - ensure Redis client is ready."""
        await self._get_redis_client()
        self._context_count += 1
        logger.info(f"JobUpdateManager context entered (active contexts: {self._context_count})")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - clean up resources only when last context exits."""
        self._context_count = max(0, self._context_count - 1)
        logger.info(f"JobUpdateManager context exiting (remaining contexts: {self._context_count})")

        if self._context_count == 0:
            logger.info("Last context exiting - cleaning up all resources")
            await self._close_all_websockets()
            await self.stop_listening()
            await self._cleanup_redis_resources()
            logger.info("All resources cleaned up successfully")
        else:
            logger.info(
                f"Context exited but {self._context_count} contexts still active - keeping resources"
            )

        return False  # Don't suppress exceptions

    async def _get_redis_client(self):
        """Get or create async Redis client."""
        if not self.redis_client:
            self.redis_client = await aioredis.from_url(
                f"redis://{Config.redis.host}:{Config.redis.port}/0"
            )
            self.pubsub = self.redis_client.pubsub()
        return self.redis_client

    async def connect(self, websocket: WebSocket, job_id: str):
        """Connect WebSocket and start Redis listener if needed."""
        await websocket.accept()
        self._add_connection(websocket, job_id)

        # Start listening only if not already started
        if not self._listener_task or self._listener_task.done():
            await self._start_listening()

    def _add_connection(self, websocket: WebSocket, job_id: str):
        """Add a new WebSocket connection."""
        # Handle existing connection for same job_id
        if job_id in self.job_connections:
            logger.warning(f"Replacing existing connection for job {job_id}")
            old_websocket = self.job_connections[job_id]
            self.remove_connection(old_websocket, job_id, delete_job=False)

        self.active_connections.append(websocket)
        self.job_connections[job_id] = websocket
        logger.debug(
            f"Added WebSocket connection for job {job_id}. Total connections: {len(self.active_connections)}"
        )

    async def _start_listening(self):
        """Start listening for Redis messages."""
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

            if job_id and job_id in self.job_connections:
                await self._send_websocket_update(job_id, data)
                self._update_db_job_status(job_id, data)
            else:
                logger.debug(f"No WebSocket connection found for job: {job_id}")

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
        except Exception as ws_error:
            logger.warning(f"WebSocket send failed for job {job_id}: {ws_error}")
            # Only remove from tracking - let FastAPI handle the connection closure
            self.remove_connection(websocket, job_id)

    def _update_db_job_status(self, job_id: str, data: dict[str, Any]):
        """Update the job status in the database."""
        status = data["status"]
        try:
            job = TranscriptionJob.get(id=job_id)
            job = job.update(
                status=status,
                result_text=data.get("text"),
                processing_time_seconds=data.get("processing_time"),
                error=f"{data.get('message')} {data.get('error')}" if status == "failed" else None,
            )  # TODO Update other fields as needed
            logger.info(f"Updated job {job_id} status to {job.status}")
        except Exception as e:
            logger.error(f"Failed to update job {job_id} status to {job.status}: {e}")

    async def disconnect(self, websocket: WebSocket, job_id: str):
        """Disconnect and remove a WebSocket connection from tracking.

        Note: WebSocket closure is handled by the FastAPI router layer.
        This method only removes the connection from internal tracking.
        """
        self.remove_connection(websocket, job_id)
        logger.debug(
            f"Removed WebSocket tracking for job {job_id}. Remaining connections: {len(self.active_connections)}"
        )

    def remove_connection(self, websocket: WebSocket, job_id: str, *, delete_job: bool = True):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if delete_job and job_id in self.job_connections:
            del self.job_connections[job_id]

    async def _close_all_websockets(self):
        """Clear all WebSocket connection tracking during shutdown.

        Note: This only clears internal tracking. Individual WebSocket connections
        are managed by their respective FastAPI router contexts.
        """
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
            manager.remove_connection(websocket, job_id)
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
            manager.remove_connection(websocket, job_id)
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
        manager.remove_connection(websocket, job_id)
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
