from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import hashlib
import json

DATABASE_URL = "sqlite:///./rooms.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ── Models ──────────────────────────────────────────────────────────────
class Room(Base):
    __tablename__ = "rooms"
    id       = Column(Integer, primary_key=True, index=True)
    name     = Column(String, unique=True, index=True)
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

# Замените ваш код index.html на тот, что будет ниже
@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

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
    
    # --- УЛУЧШЕННАЯ И БЕЗОПАСНАЯ ЛОГИКА АУТЕНТИФИКАЦИИ ---
    db = SessionLocal()
    room = db.get(Room, room_id)
    
    # Если комната не найдена
    if not room:
        await ws.close(code=4004, reason="Room not found")
        db.close()
        return

    # Если у комнаты есть пароль, мы ОБЯЗАТЕЛЬНО ждем его от клиента
    if room.pwd_hash:
        try:
            initial = json.loads(await ws.receive_text())
            client_pwd_hash = hashlib.sha256(initial.get('password', '').encode()).hexdigest()

            if room.pwd_hash != client_pwd_hash:
                await ws.close(code=4000, reason="Incorrect password")
                db.close()
                return
        except (json.JSONDecodeError, KeyError, AttributeError):
            # Если клиент отправил невалидный JSON или вообще не то
            await ws.close(code=4001, reason="Authentication failed")
            db.close()
            return
    else:
        # Если пароля нет, мы все равно должны "потребить" первое сообщение от клиента,
        # чтобы оно не мешало дальнейшему WebRTC-сигналингу.
        await ws.receive_text()

    db.close()
    # -----------------------------------------------------------

    # Регистрируем соединение
    active_connections.setdefault(room_id, set()).add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            # Ретранслируем json-строку всем остальным в комнате
            for client in active_connections.get(room_id, set()):
                if client is not ws:
                    await client.send_text(msg)
    except WebSocketDisconnect:
        # Улучшенная очистка: удаляем пустые комнаты из словаря
        if room_id in active_connections:
            active_connections[room_id].remove(ws)
            if not active_connections[room_id]:
                del active_connections[room_id]
