import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])

# Active connections keyed by job_id
_connections: dict[str, list[WebSocket]] = {}


async def broadcast(job_id: str, message: dict) -> None:
    """Send a JSON message to all subscribers of a job_id."""
    payload = json.dumps(message)
    sockets = _connections.get(job_id, [])
    dead = []
    for ws in sockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        sockets.remove(ws)


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()

    # Register this connection
    _connections.setdefault(job_id, []).append(websocket)

    # Send a hello so the client knows the channel is live
    await websocket.send_text(json.dumps({
        "event": "connected",
        "job_id": job_id,
        "message": f"Connected to job stream: {job_id}",
    }))

    try:
        while True:
            # Keep connection alive; real events are pushed via broadcast()
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        pass
    finally:
        sockets = _connections.get(job_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
