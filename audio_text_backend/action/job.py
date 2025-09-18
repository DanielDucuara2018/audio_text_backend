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
        self.active_connections.remove(websocket)
        if job_id and job_id in self.job_connections:
            del self.job_connections[job_id]

    async def send_job_update(self, job_id: str, message: dict):
        if job_id in self.job_connections:
            try:
                await self.job_connections[job_id].send_json(message)
            except Exception:
                # Connection closed, clean up
                if job_id in self.job_connections:
                    del self.job_connections[job_id]


manager = ConnectionManager()
