import redis
from typing import Optional, Tuple
from django.conf import settings


class RedisClientService:
    _instance: Optional['RedisClientService'] = None

    @classmethod
    def get_instance(cls) -> 'RedisClientService':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.pool = redis.ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
            max_connections=20,
        )
        self.client = redis.Redis(connection_pool=self.pool)

    def update_driver_location(self, driver_id: str, longitude: float, latitude: float, timestamp_iso: Optional[str] = None) -> None:
        pipeline = self.client.pipeline()
        # GEOADD key longitude latitude member
        pipeline.geoadd(settings.REDIS_LOCATIONS_KEY, (longitude, latitude, driver_id))

        # Store last ping timestamp and state in a driver hash with a 24h TTL
        driver_meta_key = f'{settings.REDIS_DRIVER_KEY_PREFIX}{driver_id}:state'
        meta_data = {
            'longitude': str(longitude),
            'latitude': str(latitude),
        }
        if timestamp_iso:
            meta_data['last_ping'] = timestamp_iso
        pipeline.hset(driver_meta_key, mapping=meta_data)
        pipeline.expire(driver_meta_key, 86400)

        pipeline.execute()

    def get_driver_location(self, driver_id: str) -> Optional[Tuple[float, float]]:
        # GEOPOS key member -> returns list of (lon, lat) tuples
        results = self.client.geopos(settings.REDIS_LOCATIONS_KEY, driver_id)
        if results and results[0]:
            return results[0]  # (longitude, latitude)
        return None

    def remove_driver(self, driver_id: str) -> None:
        self.client.zrem(settings.REDIS_LOCATIONS_KEY, driver_id)
        self.client.delete(f'{settings.REDIS_DRIVER_KEY_PREFIX}{driver_id}:state')