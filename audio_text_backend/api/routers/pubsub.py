"""Pub/Sub push subscription endpoint.

Cloud Pub/Sub (and the local emulator) deliver status messages here via an
HTTP push subscription.  The endpoint acknowledges the message by returning
HTTP 200; any non-2xx response causes Pub/Sub to retry with exponential
back-off.
"""

import base64
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from audio_text_backend.action.job import update_job_status
from audio_text_backend.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/pubsub",
    tags=["pubsub"],
)


@router.post("/status")
async def receive_status_update(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Receive a job status update pushed by Cloud Pub/Sub.

    Expected envelope format (Pub/Sub push):
    ```json
    {
      "message": {
        "data": "<base64-encoded JSON>",
        "messageId": "...",
        "publishTime": "..."
      },
      "subscription": "projects/.../subscriptions/..."
    }
    ```
    The decoded ``data`` JSON must contain at minimum ``job_id`` and
    ``status`` fields.
    """
    try:
        envelope = await request.json()
        raw_data = envelope.get("message", {}).get("data", "")
        data: dict = json.loads(base64.b64decode(raw_data).decode())
    except Exception as exc:
        logger.error(f"Failed to parse Pub/Sub envelope: {exc}")
        raise HTTPException(status_code=400, detail="Malformed Pub/Sub message")

    job_id = data.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id in message payload")

    logger.info(f"Pub/Sub push received: job_id={job_id} status={data.get('status')}")

    await update_job_status(job_id, data, session=session)

    # Return 200 to acknowledge the message to Pub/Sub.
    return {"status": "ok"}
