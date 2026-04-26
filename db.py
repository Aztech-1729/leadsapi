from motor.motor_asyncio import AsyncIOMotorClient
import config

_client = None
_db = None

def get_db():
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(config.MONGO_URI)
        _db = _client[config.DB_NAME]
    return _db
