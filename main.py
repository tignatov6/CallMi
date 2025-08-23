# Файл: main.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import hashlib
import json
import asyncio
from datetime import datetime, timezone
from config import config

# --- База данных (без изменений) ---
DATABASE_URL = config.DATABASE_URL
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    pwd_hash = Column(String, nullable=True)
    last_activity = Column(DateTime, default=lambda: datetime.now(timezone.utc))

Base.metadata.drop_all(bind=engine)  # Удаляем старые таблицы
Base.metadata.create_all(bind=engine)  # Создаем новые с обновленной схемой

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
async def create_room(payload: RoomCreate, db: Session = Depends(get_db)):
    if db.query(Room).filter(Room.name == payload.name).first():
        raise HTTPException(400, "Комната с таким именем уже существует")
    pwd_hash = hashlib.sha256(payload.password.encode()).hexdigest() if payload.password else None
    room = Room(name=payload.name, pwd_hash=pwd_hash)
    db.add(room); db.commit(); db.refresh(room)
    
    # Уведомляем всех пользователей главного меню о создании новой комнаты
    await manager.notify_main_menu_users_room_list_changed("room_created")
    print(f"🏠 Уведомлены пользователи главного меню о создании комнаты: {room.name}")
    
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
        # Пользователи в главном меню: {peer_id: {"name": str, "ws": WebSocket}}
        self.main_menu_users: dict[str, dict] = {}

    async def connect(self, room_id: int, peer_id: str, name: str, ws: WebSocket):
        await ws.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = {}
        
        # Обновляем время активности комнаты в базе данных
        await self.update_room_activity(room_id)
        
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
    
    async def update_room_activity(self, room_id: int):
        """Обновляем время последней активности комнаты"""
        db = SessionLocal()
        try:
            room = db.get(Room, room_id)
            if room:
                room.last_activity = datetime.now(timezone.utc)
                db.commit()
                print(f"🔄 Обновлена активность комнаты {room.name} (ID: {room_id})")
        finally:
            db.close()
    
    async def cleanup_empty_rooms(self):
        """Удаляем пустые комнаты, неактивные более config.ROOM_CLEANUP_TIMEOUT_SECONDS секунд"""
        db = SessionLocal()
        rooms_deleted = False
        try:
            cutoff_time = datetime.now(timezone.utc).timestamp() - config.ROOM_CLEANUP_TIMEOUT_SECONDS
            
            # Находим все комнаты
            all_rooms = db.query(Room).all()
            
            for room in all_rooms:
                # Проверяем, есть ли кто-то в комнате
                has_users = room.id in self.rooms and len(self.rooms[room.id]) > 0
                
                if not has_users:
                    # Комната пустая, проверяем время неактивности
                    last_activity_timestamp = room.last_activity.timestamp() if room.last_activity else 0
                    
                    if last_activity_timestamp < cutoff_time:
                        print(f"🗑️ Удаляем пустую комнату: {room.name} (ID: {room.id})")
                        db.delete(room)
                        rooms_deleted = True
                        
                        # Удаляем из памяти, если есть
                        if room.id in self.rooms:
                            del self.rooms[room.id]
            
            db.commit()
            
            # Если были удалены комнаты, уведомляем пользователей главного меню
            if rooms_deleted:
                await self.notify_main_menu_users_room_list_changed("room_deleted")
            
        except Exception as e:
            print(f"❌ Ошибка при очистке комнат: {e}")
            db.rollback()
        finally:
            db.close()
    
    def add_main_menu_user(self, peer_id: str, name: str, ws):
        """Добавляем пользователя в главное меню"""
        self.main_menu_users[peer_id] = {"name": name, "ws": ws}
        print(f"🏠 Пользователь {name} добавлен в главное меню")
    
    def remove_main_menu_user(self, peer_id: str):
        """Удаляем пользователя из главного меню"""
        if peer_id in self.main_menu_users:
            user_name = self.main_menu_users[peer_id]["name"]
            del self.main_menu_users[peer_id]
            print(f"🏠 Пользователь {user_name} удален из главного меню")
    
    async def notify_main_menu_users_room_list_changed(self, event_type="room_updated"):
        """Уведомляем всех пользователей главного меню об изменении списка комнат"""
        if self.main_menu_users:
            event_emojis = {
                "room_created": "🏠",
                "room_deleted": "🗑️",
                "room_updated": "🔄"
            }
            emoji = event_emojis.get(event_type, "📢")
            print(f"{emoji} Уведомляем {len(self.main_menu_users)} пользователей о событии: {event_type}")
            
            # Отправляем сигнал об обновлении списка комнат
            message = {"type": "rooms_updated", "event": event_type}
            tasks = []
            
            for peer_id, user_data in list(self.main_menu_users.items()):
                try:
                    tasks.append(user_data["ws"].send_json(message))
                except Exception as e:
                    print(f"❌ Ошибка отправки уведомления {peer_id}: {e}")
                    # Удаляем нерабочие соединения
                    self.remove_main_menu_user(peer_id)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

manager = ConnectionManager()

# Фоновая задача для очистки пустых комнат
async def cleanup_task():
    """Фоновая задача для очистки пустых комнат каждые config.ROOM_CLEANUP_INTERVAL_SECONDS секунд"""
    while True:
        try:
            await asyncio.sleep(config.ROOM_CLEANUP_INTERVAL_SECONDS)  # Проверяем каждые config.ROOM_CLEANUP_INTERVAL_SECONDS секунд
            await manager.cleanup_empty_rooms()
        except Exception as e:
            print(f"❌ Ошибка в фоновой задаче очистки: {e}")

# Запускаем фоновую задачу при старте приложения
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_task())
    print(f"🚀 Фоновая задача очистки комнат запущена")
    print(f"⚙️ Конфигурация: таймаут удаления комнат - {config.ROOM_CLEANUP_TIMEOUT_SECONDS}с, интервал проверки - {config.ROOM_CLEANUP_INTERVAL_SECONDS}с")

# ─── WebSocket для главного меню ──────────────────────────────────
@app.websocket("/main-menu/{peer_id}/{user_name}")
async def main_menu_websocket(ws: WebSocket, peer_id: str, user_name: str):
    await ws.accept()
    
    # Добавляем пользователя в главное меню
    manager.add_main_menu_user(peer_id, user_name, ws)
    
    try:
        while True:
            # Поддерживаем соединение и обрабатываем сообщения
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.remove_main_menu_user(peer_id)
    except Exception as e:
        print(f"❌ Ошибка WebSocket главного меню: {e}")
        manager.remove_main_menu_user(peer_id)

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
            
            # Обработка специальных команд
            if data.get("type") == "refresh_users":
                # Отправляем обновленный список пользователей в комнате
                existing_peers = [{"id": pid, "name": p_data["name"]} for pid, p_data in manager.rooms[room_id].items()]
                await ws.send_json({"type": "room_state", "payload": existing_peers})
                continue
            
            # Ожидаемый формат: {"to_id": "...", "type": "sdp" | "ice", "payload": {...}}
            to_id = data.get("to_id")
            if to_id:
                # Добавляем, от кого это сообщение
                data["from_id"] = peer_id
                await manager.send_to_peer(room_id, to_id, data)
                
    except WebSocketDisconnect:
        await manager.disconnect(room_id, peer_id)
