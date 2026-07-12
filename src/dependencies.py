from functools import lru_cache

from src.config import get_settings
from src.services import DataLakeService
from src.storage.database import Database
from src.storage.object_store import ObjectStore


@lru_cache
def get_service() -> DataLakeService:
    settings = get_settings()
    return DataLakeService(settings, ObjectStore(settings), Database(settings))

