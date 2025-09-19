import asyncio

from fastapi import WebSocket


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.job_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, job_id: str = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        if job_id:
            self.job_connections[job_id] = websocket

    def disconnect(self, websocket: WebSocket, job_id: str = None):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if job_id and job_id in self.job_connections:
            del self.job_connections[job_id]

    async def send_job_update(self, job_id: str, message: dict):
        """Send update to specific job WebSocket connection."""
        if job_id in self.job_connections:
            try:
                await self.job_connections[job_id].send_json(message)
            except Exception:
                # Connection closed, clean up
                if job_id in self.job_connections:
                    del self.job_connections[job_id]

    def send_job_update_sync(self, job_id: str, message: dict):
        """Sync version for use in Celery tasks."""
        if job_id in self.job_connections:
            # Create new event loop if none exists (for Celery worker)
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            if loop.is_running():
                # If loop is already running, schedule the coroutine
                asyncio.create_task(self.send_job_update(job_id, message))
            else:
                # If no loop is running, run it
                loop.run_until_complete(self.send_job_update(job_id, message))


manager = ConnectionManager()
