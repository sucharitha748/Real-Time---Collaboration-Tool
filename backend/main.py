from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import asyncio
import datetime
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple connection manager for WebSocket clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: dict):
        # send JSON-serializable dict to all active clients
        living = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
                living.append(connection)
            except Exception:
                # skip broken connections
                pass
        self.active_connections = living

manager = ConnectionManager()

# In-memory document state (MVP). Could be replaced with DB/file.
document_state = {
    "text": "",
    "last_updated": None,
}

@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # when a new client connects, send current doc state and online count
        await websocket.send_json({
            "type": "init",
            "payload": {
                "text": document_state["text"],
                "last_updated": document_state["last_updated"],
                "online": len(manager.active_connections)
            }
        })
        await manager.broadcast({"type": "presence", "payload": {"online": len(manager.active_connections)}})

        while True:
            msg = await websocket.receive_json()
            # Expecting messages of shape: { type: "update" | "cursor" | "meta", payload: {...} }
            typ = msg.get('type')
            payload = msg.get('payload')

            if typ == 'update':
                # update the server-side document and broadcast
                document_state['text'] = payload.get('text', '')
                document_state['last_updated'] = datetime.datetime.utcnow().isoformat() + 'Z'
                await manager.broadcast({
                    'type': 'update',
                    'payload': {
                        'text': document_state['text'],
                        'last_updated': document_state['last_updated'],
                        'author': payload.get('author')
                    }
                })
            elif typ == 'meta':
                # For things like username change
                await manager.broadcast({
                    'type': 'meta',
                    'payload': payload
                })
            elif typ == 'ping':
                # keepalive/ping
                await websocket.send_json({'type': 'pong'})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast({"type": "presence", "payload": {"online": len(manager.active_connections)}})


@app.post('/save')
async def save_document(request: Request):
    data = await request.json()
    text = data.get('text', '')
    name = data.get('name', 'document')
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f'saved_{name}_{timestamp}.txt'
    os.makedirs('saved', exist_ok=True)
    path = os.path.join('saved', filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return JSONResponse({'status': 'ok', 'path': path})


@app.get('/')
async def root():
    return JSONResponse({'status': 'running'})
