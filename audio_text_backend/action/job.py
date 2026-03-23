"""Job action layer.

Handles job creation (DB write + Pub/Sub publish), job reads, WebSocket
connection management, and job-status DB updates triggered by Pub/Sub push
subscriptions.

Session strategy
----------------
* `create()` — uses `session_scope()` directly so the INSERT is committed
  *before* publishing to Pub/Sub.  This avoids publishing a message for a
  row that might not yet exist in the database.
* `read()` — accepts an injected `AsyncSession` from `Depends(get_session)`
  so read endpoints share a single request-scoped session.
* `update_job_status()` — accepts an injected session from the Pub/Sub push
  endpoint; all DB writes and the subsequent WebSocket broadcast happen inside
  the same request-scoped transaction.
"""

import asyncio
import logging
from typing import Any, overload

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from audio_text_backend import pubsub
from audio_text_backend.errors import NoDataFound
from audio_text_backend.model.transcription_job import JobStatus, TranscriptionJob

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------- create --


async def create(filename: str, url: str, model: str) -> TranscriptionJob:
    """Create a TranscriptionJob row and publish a trigger message to Pub/Sub.

    The DB write is committed inside ``session_scope()`` *before* the Pub/Sub
    publish so the worker always finds an existing row when it starts.
    """
    job = await TranscriptionJob(
        filename=filename,
        url=url,
        status=JobStatus.PENDING,
        whisper_model=model,
    ).create()

    # Committed — now safe to publish.
    await pubsub.publish_job(job.id, job.filename, job.url, model)
    logger.info(f"Job {job.id} created and published to Pub/Sub (model={model})")
    return job


# --------------------------------------------------------------------- read --


@overload
async def read(job_id: str, *, session: AsyncSession) -> TranscriptionJob: ...
@overload
async def read(*, session: AsyncSession, **kwargs: Any) -> list[TranscriptionJob]: ...


async def read(
    job_id: str | None = None,
    *,
    session: AsyncSession,
    **kwargs: Any,
) -> TranscriptionJob | list[TranscriptionJob]:
    if job_id:
        logger.info("Reading job: %s", job_id)
        return await TranscriptionJob.get(id=job_id, session=session)
    logger.info("Reading all jobs with filters: %s", kwargs)
    return await TranscriptionJob.find(session=session, **kwargs)


# ------------------------------------------------- status update (push EP) --


async def update_job_status(
    job_id: str,
    data: dict[str, Any],
    *,
    session: AsyncSession,
) -> None:
    """Update job status from a Pub/Sub status message and broadcast via WS.

    Called by the ``POST /pubsub/status`` push endpoint which supplies the
    request-scoped session.  All DB changes are part of that session's
    transaction and commit/roll-back together with the HTTP response.
    """
    status = data.get("status")
    if not status:
        logger.warning(f"Status message for job {job_id} missing 'status' field")
        return

    try:
        job = await TranscriptionJob.get(id=job_id, session=session)
        await job.update(
            session=session,
            status=status,
            result_text=data.get("result"),
            processing_time_seconds=int(data["processing_time"])
            if data.get("processing_time") is not None
            else None,
            error_message=data.get("error") if status == JobStatus.FAILED else None,
            language=data.get("language"),
            language_probability=data.get("language_probability"),
        )
        logger.info(f"Updated job {job_id} -> status={status}")
    except NoDataFound:
        logger.warning(f"Job {job_id} not found when processing status update")
        return
    except Exception as e:
        logger.error(f"Failed to update job {job_id} status: {e}")
        raise

    # WebSocket broadcast is in-memory — no external side-effects.
    await manager.broadcast(job_id, data)


# --------------------------------------------------- WebSocket connection  --


class JobUpdateManager:
    """Singleton that tracks active WebSocket connections by job_id.

    Status updates arrive via the Pub/Sub push endpoint
    (``POST /api/v1/pubsub/status``) which calls ``broadcast()``.
    There is no Redis dependency.
    """

    _instance: "JobUpdateManager | None" = None

    def __new__(cls) -> "JobUpdateManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self.active_connections: list[WebSocket] = []
            self.job_connections: dict[str, WebSocket] = {}
            self._lock = asyncio.Lock()
            self._initialized = True

    async def connect(self, websocket: WebSocket, job_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            if job_id in self.job_connections:
                old = self.job_connections[job_id]
                self._remove_unsafe(old, job_id)
                logger.debug(f"Replaced existing WS connection for job {job_id}")
            self.active_connections.append(websocket)
            self.job_connections[job_id] = websocket
        logger.debug(f"WS connected for job {job_id} (total={len(self.active_connections)})")

    async def disconnect(self, websocket: WebSocket, job_id: str) -> None:
        async with self._lock:
            self._remove_unsafe(websocket, job_id)
        logger.debug(f"WS disconnected for job {job_id}")

    def _remove_unsafe(self, websocket: WebSocket, job_id: str) -> None:
        """Remove a connection without acquiring the lock (caller must hold it)."""
        self.active_connections = [c for c in self.active_connections if c is not websocket]
        self.job_connections.pop(job_id, None)

    async def broadcast(self, job_id: str, data: dict[str, Any]) -> None:
        """Send a JSON message to the WebSocket client tracking ``job_id``."""
        async with self._lock:
            websocket = self.job_connections.get(job_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(data)
            logger.debug(f"Broadcast to job {job_id}: status={data.get('status')}")
        except Exception as exc:
            logger.warning(f"WS broadcast failed for job {job_id}: {exc}")
            await self.disconnect(websocket, job_id)


# Module-level singleton used by the push endpoint and WebSocket router.
manager = JobUpdateManager()


# -------------------------------------------------- WebSocket entry-point  --


async def establish_connection(job_id: str, websocket: WebSocket) -> None:
    """Accept a WebSocket connection and keep it alive until the client disconnects.

    On connect the current job status is sent immediately.  Subsequent status
    updates arrive via ``manager.broadcast()`` called by the Pub/Sub push
    endpoint.  The loop handles:
    * client ``ping`` messages -> ``pong`` reply
    * 30 s keepalive frames so proxies do not terminate idle connections
    * graceful close on ``WebSocketDisconnect``
    """
    await manager.connect(websocket, job_id)
    try:
        # Send current status immediately.
        try:
            job = await TranscriptionJob.get(id=job_id)
            await websocket.send_json({
                "job_id": job_id,
                "status": job.status,
                "type": "connected",
                "message": "WebSocket connected",
            })
        except NoDataFound:
            await websocket.send_json({"type": "error", "message": f"Job {job_id} not found"})
            return

        # Keep-alive loop — updates pushed via manager.broadcast().
        while True:
            try:
                text = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if text == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "keepalive"})
                except Exception:
                    break  # client gone

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, job_id)
