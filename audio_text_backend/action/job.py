import asyncio
import json
import logging
from datetime import datetime
from typing import overload

from fastapi import WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis

from audio_text_backend.action.tasks import process_audio
from audio_text_backend.config import Config
from audio_text_backend.model.transcription_job import JobStatus, TranscriptionJob

logger = logging.getLogger(__name__)


def create(filename: str, url: str, mode: str) -> TranscriptionJob:
    """Start audio transcription job."""
    # Create job record in database
    job = TranscriptionJob(filename=filename, url=url, status=JobStatus.PENDING).create()
    # Start background processing with Celery
    task_id = process_audio.delay(job.id, job.filename, mode)
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


async def establish_connection(job_id: str, websocket: WebSocket):
    """Establish WebSocket connection for job updates."""
    try:
        await _connect_websocket(websocket, job_id)
        await _send_connection_confirmation(websocket, job_id)
        await _handle_websocket_lifecycle(websocket, job_id)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job: {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
        await _handle_websocket_error(websocket, job_id, e)
    finally:
        _cleanup_websocket_connection(websocket, job_id)


async def _connect_websocket(websocket: WebSocket, job_id: str):
    """Connect WebSocket and start Redis listener if needed."""
    await manager.connect(websocket, job_id)
    logger.info(f"WebSocket connected for job: {job_id}")


async def _send_connection_confirmation(websocket: WebSocket, job_id: str):
    """Send initial connection confirmation to client."""
    confirmation_message = {
        "type": "connected",
        "job_id": job_id,
        "message": "Connected to job updates",
        "timestamp": datetime.now().isoformat(),
    }

    try:
        await websocket.send_json(confirmation_message)
        logger.debug(f"Sent connection confirmation for job: {job_id}")
    except Exception as e:
        logger.error(f"Failed to send connection confirmation for job {job_id}: {e}")
        raise


async def _handle_websocket_lifecycle(websocket: WebSocket, job_id: str):
    """Handle WebSocket lifecycle including keepalive and client messages."""
    while True:
        try:
            await _process_client_message(websocket, job_id)
        except asyncio.TimeoutError:
            await _send_keepalive_ping(websocket)
        except WebSocketDisconnect:
            logger.info(f"Client disconnected for job: {job_id}")
            break
        except Exception as e:
            logger.error(f"Error processing client message for job {job_id}: {e}")
            # Continue listening for other messages
            await asyncio.sleep(0.1)


async def _process_client_message(websocket: WebSocket, job_id: str):
    """Process incoming client messages with timeout."""
    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

    # Echo back for connection testing
    echo_message = {
        "type": "echo",
        "data": data,
        "job_id": job_id,
        "timestamp": datetime.now().isoformat(),
    }

    await websocket.send_json(echo_message)
    logger.debug(f"Echoed client message for job {job_id}: {data}")


async def _send_keepalive_ping(websocket: WebSocket):
    """Send keepalive ping to maintain connection."""
    ping_message = {
        "type": "ping",
        "timestamp": datetime.now().isoformat(),
        "message": "Connection keepalive",
    }

    try:
        await websocket.send_json(ping_message)
        logger.debug("Sent keepalive ping")
    except Exception as e:
        logger.warning(f"Failed to send keepalive ping: {e}")
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


def _cleanup_websocket_connection(websocket: WebSocket, job_id: str):
    """Clean up WebSocket connection resources."""
    try:
        manager.disconnect(websocket, job_id)
        logger.info(f"Cleaned up WebSocket connection for job: {job_id}")
    except Exception as e:
        logger.error(f"Error during WebSocket cleanup for job {job_id}: {e}")


class RedisConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.job_connections: dict[str, WebSocket] = {}
        self.redis_client = None
        self.pubsub = None
        self.listening = False
        self._listener_task = None

    async def _get_redis_client(self):
        """Get or create async Redis client."""
        if not self.redis_client:
            self.redis_client = await aioredis.from_url(Config.celery.redis_url)
            self.pubsub = self.redis_client.pubsub()
        return self.redis_client

    async def connect(self, websocket: WebSocket, job_id: str):
        await websocket.accept()
        self._add_connection(websocket, job_id)

        # Start listening for updates if not already
        if not self.listening:
            await self.start_listening()

    def _add_connection(self, websocket: WebSocket, job_id: str):
        """Add a new WebSocket connection."""
        self.active_connections.append(websocket)
        self.job_connections[job_id] = websocket

    def disconnect(self, websocket: WebSocket, job_id: str):
        self._remove_connection(websocket, job_id)

    def _remove_connection(self, websocket: WebSocket, job_id: str):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if job_id in self.job_connections:
            del self.job_connections[job_id]

    async def start_listening(self):
        """Start listening for Redis messages."""
        if self.listening:
            return

        await self._initialize_redis_listener()
        self._listener_task = asyncio.create_task(self._listen_for_updates())
        logger.info("Started Redis listener for WebSocket updates")

    async def _initialize_redis_listener(self):
        """Initialize Redis client and pubsub subscription."""
        try:
            await self._get_redis_client()
            await self.pubsub.subscribe("job_updates")
            self.listening = True
        except Exception as e:
            logger.error(f"Failed to start Redis listener: {e}")
            raise e

    async def _listen_for_updates(self):
        """Background task that listens for Redis messages."""
        logger.info("Redis listener started")
        try:
            while self.listening:
                await self._process_redis_messages()
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
            await self._cleanup_connection(job_id, websocket)

    async def _cleanup_connection(self, job_id: str, websocket: WebSocket):
        """Clean up a dead WebSocket connection."""
        try:
            self._remove_connection(websocket, job_id)
        except Exception as e:
            logger.error(f"Error cleaning up connection for job {job_id}: {e}")

    async def stop_listening(self):
        """Stop the Redis listener."""
        logger.info("Stopping Redis listener")
        self.listening = False

        await self._cancel_listener_task()
        await self._cleanup_redis_resources()

    async def _cancel_listener_task(self):
        """Cancel the background listener task."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_redis_resources(self):
        """Clean up Redis client and pubsub resources."""
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe("job_updates")
                await self.pubsub.close()
            except Exception as e:
                logger.error(f"Error closing pubsub: {e}")

        if self.redis_client:
            try:
                await self.redis_client.close()
            except Exception as e:
                logger.error(f"Error closing Redis client: {e}")


manager = RedisConnectionManager()
