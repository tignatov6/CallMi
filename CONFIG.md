# CallMi Configuration Guide

## Environment Variables

CallMi can be configured using environment variables. You can set these directly in your system environment or create a `.env` file in the project root.

### Creating a .env file

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your preferred values:
   ```bash
   # Example .env file
   ROOM_CLEANUP_TIMEOUT_SECONDS=30
   ROOM_CLEANUP_INTERVAL_SECONDS=15
   DEBUG=true
   ```

### Available Configuration Options

#### Room Management
- `ROOM_CLEANUP_TIMEOUT_SECONDS` (default: 15) - Seconds after which empty rooms are deleted
- `ROOM_CLEANUP_INTERVAL_SECONDS` (default: 10) - How often to check for empty rooms

#### Database
- `DATABASE_URL` (default: "sqlite:///./rooms.db") - Database connection string

#### Auto-refresh Intervals
- `ROOM_LIST_REFRESH_INTERVAL` (default: 30) - Room list refresh interval in seconds
- `USER_LIST_REFRESH_INTERVAL` (default: 10) - User list refresh interval in seconds

#### WebSocket Settings
- `WEBSOCKET_TIMEOUT` (default: 60) - WebSocket connection timeout in seconds

#### Security
- `ENABLE_PASSWORD_PROTECTION` (default: true) - Enable/disable room password protection

#### Server Settings
- `HOST` (default: "127.0.0.1") - Server host address
- `PORT` (default: 8000) - Server port
- `DEBUG` (default: false) - Enable debug mode
- `LOG_LEVEL` (default: "INFO") - Logging level

### Example Configurations

#### Development Setup
```bash
# .env for development
DEBUG=true
LOG_LEVEL=DEBUG
ROOM_CLEANUP_TIMEOUT_SECONDS=10  # Faster cleanup for testing
ROOM_CLEANUP_INTERVAL_SECONDS=5
```

#### Production Setup
```bash
# .env for production
DEBUG=false
LOG_LEVEL=WARNING
HOST=0.0.0.0
PORT=80
ROOM_CLEANUP_TIMEOUT_SECONDS=300  # 5 minutes
ROOM_CLEANUP_INTERVAL_SECONDS=60  # Check every minute
DATABASE_URL=postgresql://user:password@localhost/callmi
```

#### Testing Setup
```bash
# .env for testing
ROOM_CLEANUP_TIMEOUT_SECONDS=5   # Very fast cleanup for tests
ROOM_CLEANUP_INTERVAL_SECONDS=2
DATABASE_URL=sqlite:///./test_rooms.db
```

### Loading Configuration

The configuration is automatically loaded when the application starts:

1. **System environment variables** are checked first
2. **`.env` file** is loaded if it exists (requires `python-dotenv`)
3. **Default values** are used as fallback

Configuration precedence (highest to lowest):
1. System environment variables
2. .env file variables  
3. Default values in config.py

### Usage in Code

Access configuration values through the global config object:

```python
from config import config

# Use configuration values
print(f"Room cleanup timeout: {config.ROOM_CLEANUP_TIMEOUT_SECONDS} seconds")
print(f"Database URL: {config.DATABASE_URL}")
```

### Logging Configuration Values

The application logs the current configuration on startup:

```
🚀 Фоновая задача очистки комнат запущена
⚙️ Конфигурация: таймаут удаления комнат - 15с, интервал проверки - 10с
```

This helps verify that your configuration is loaded correctly.