# Файл: main.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import hashlib
import json
import asyncio

# --- База данных (без изменений) ---
DATABASE_URL = "sqlite:///./rooms.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    pwd_hash = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

class RoomCreate(BaseModel):
    name: str
    password: str | None = None

class RoomPublic(BaseModel):
    id: int
    name: str
    has_password: bool

# --- FastAPI app и REST API (почти без изменений) ---
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def read_root():
    # Убедитесь, что файл называется index.html и лежит в папке static
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

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


# ─── НОВЫЙ МЕНЕДЖЕР СОЕДИНЕНИЙ ──────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        # Структура: {room_id: {peer_id: {"name": str, "ws": WebSocket}}}
        self.rooms: dict[int, dict[str, dict]] = {}

    async def connect(self, room_id: int, peer_id: str, name: str, ws: WebSocket):
        await ws.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        
        # 1. Отправляем новому участнику список всех, кто уже в комнате
        existing_peers = [{"id": pid, "name": p_data["name"]} for pid, p_data in self.rooms[room_id].items()]
        await ws.send_json({"type": "room_state", "payload": existing_peers})

        # 2. Сообщаем всем остальным о новом участнике
        await self.broadcast(room_id, {"type": "new_peer", "payload": {"id": peer_id, "name": name}}, exclude_id=peer_id)
        
        # 3. Добавляем нового участника в комнату
        self.rooms[room_id][peer_id] = {"name": name, "ws": ws}

    async def disconnect(self, room_id: int, peer_id: str):
        if room_id in self.rooms and peer_id in self.rooms[room_id]:
            del self.rooms[room_id][peer_id]
            if not self.rooms[room_id]: # Если комната пуста, удаляем ее
                del self.rooms[room_id]
            else:
                # Сообщаем оставшимся, что участник вышел
                await self.broadcast(room_id, {"type": "peer_left", "payload": {"id": peer_id}})

    async def send_to_peer(self, room_id: int, peer_id: str, message: dict):
        if room_id in self.rooms and peer_id in self.rooms[room_id]:
            await self.rooms[room_id][peer_id]["ws"].send_json(message)

    async def broadcast(self, room_id: int, message: dict, exclude_id: str | None = None):
        if room_id in self.rooms:
            tasks = []
            for peer_id, peer_data in self.rooms[room_id].items():
                if peer_id != exclude_id:
                    tasks.append(peer_data["ws"].send_json(message))
            await asyncio.gather(*tasks)

manager = ConnectionManager()

# ─── ОБНОВЛЕННЫЙ WebSocket-сигналинг ──────────────────────────────────
@app.websocket("/ws/{room_id}/{peer_id}/{user_name}")
async def websocket_endpoint(ws: WebSocket, room_id: int, peer_id: str, user_name: str):
    # Аутентификация по паролю (если он есть)
    db = SessionLocal()
    room = db.get(Room, room_id)
    if not room:
        await ws.accept()
        await ws.close(code=4004, reason="Комната не найдена")
        db.close()
        return
    
    if room.pwd_hash:
        # Пароль теперь передается как query-параметр для простоты
        # ws://.../ws/1/peer123/MyName?password=mypass
        try:
            pwd = ws.query_params.get('password', '')
            client_pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()
            if room.pwd_hash != client_pwd_hash:
                await ws.accept()
                await ws.close(code=4000, reason="Неправильный пароль")
                db.close()
                return
        except Exception:
            await ws.accept()
            await ws.close(code=4001, reason="Ошибка аутентификации")
            db.close()
            return
    db.close()

    # Если аутентификация прошла успешно, подключаем пользователя
    await manager.connect(room_id, peer_id, user_name, ws)

    try:
        while True:
            # Ожидаем сообщения для ретрансляции
            data = await ws.receive_json()
            # Ожидаемый формат: {"to_id": "...", "type": "sdp" | "ice", "payload": {...}}
            to_id = data.get("to_id")
            if to_id:
                # Добавляем, от кого это сообщение
                data["from_id"] = peer_id
                await manager.send_to_peer(room_id, to_id, data)
                
    except WebSocketDisconnect:
        await manager.disconnect(room_id, peer_id)
