from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import hashlib, secrets, json

DATABASE_URL = "sqlite:///./rooms.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ── Models ──────────────────────────────────────────────────────────────
class Room(Base):
    __tablename__ = "rooms"
    id       = Column(Integer, primary_key=True, index=True)
    name     = Column(String, unique=True)
    pwd_hash = Column(String, nullable=True)        # sha256 || None

Base.metadata.create_all(bind=engine)

# ── Schemas ─────────────────────────────────────────────────────────────
class RoomCreate(BaseModel):
    name: str
    password: str | None = None

class RoomPublic(BaseModel):
    id: int
    name: str
    has_password: bool

# ── FastAPI app ─────────────────────────────────────────────────────────
app = FastAPI()
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── REST: создание / список комнат ─────────────────────────────────────
@app.post("/api/rooms", response_model=RoomPublic)
def create_room(payload: RoomCreate, db: Session = Depends(get_db)):
    if db.query(Room).filter(Room.name == payload.name).first():
        raise HTTPException(400, "Комната с таким именем уже существует")
    pwd_hash = hashlib.sha256(payload.password.encode()).hexdigest() if payload.password else None
    room = Room(name=payload.name, pwd_hash=pwd_hash)
    db.add(room); db.commit(); db.refresh(room)
    return RoomPublic(id=room.id, name=room.name, has_password=bool(pwd_hash))

@app.get("/api/rooms", response_model=list[RoomPublic])
def list_rooms(db: Session = Depends(get_db)):
    rooms = db.query(Room).all()
    return [RoomPublic(id=r.id, name=r.name, has_password=bool(r.pwd_hash)) for r in rooms]

# ── WebSocket-сигналинг ────────────────────────────────────────────────
active_connections: dict[int, set[WebSocket]] = {}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(ws: WebSocket, room_id: int):
    await ws.accept()
    # аутентификация паролем (если требуется)
    initial = json.loads(await ws.receive_text())
    if 'password' in initial:
        db: Session = SessionLocal()
        room = db.get(Room, room_id)
        db.close()
        if room and room.pwd_hash and room.pwd_hash != hashlib.sha256(initial['password'].encode()).hexdigest():
            await ws.close(code=4000)
            return
    # регистрируем соединение
    active_connections.setdefault(room_id, set()).add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            # просто ретранслируем json-строку всем остальным в комнате
            for client in active_connections[room_id]:
                if client is not ws:
                    await client.send_text(msg)
    except WebSocketDisconnect:
        active_connections[room_id].remove(ws)
