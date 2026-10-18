import logging
import redis
from typing import Optional, Tuple, List, Dict, Any
from django.conf import settings

logger = logging.getLogger(__name__)


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
        pipeline.geoadd(settings.REDIS_LOCATIONS_KEY, (longitude, latitude, driver_id))

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
        results = self.client.geopos(settings.REDIS_LOCATIONS_KEY, driver_id)
        if results and results[0]:
            return results[0]
        return None

    def find_nearby_drivers(self, longitude: float, latitude: float, radius_km: float = 3.0, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Uses Redis geospatial search to find the closest drivers within radius_km sorted ASC by distance.
        Returns a list of dicts: [{'driver_id': str, 'distance_km': float, 'coordinates': (lon, lat)}]
        """
        try:
            # Use modern GEOSEARCH (Redis 6.2+)
            raw_results = self.client.geosearch(
                name=settings.REDIS_LOCATIONS_KEY,
                longitude=longitude,
                latitude=latitude,
                radius=radius_km,
                unit='km',
                sort='ASC',
                count=limit,
                withdist=True,
                withcoord=True,
            )
        except (AttributeError, redis.ResponseError):
            # Fallback for Redis < 6.2
            raw_results = self.client.georadius(
                name=settings.REDIS_LOCATIONS_KEY,
                longitude=longitude,
                latitude=latitude,
                radius=radius_km,
                unit='km',
                sort='ASC',
                count=limit,
                withdist=True,
                withcoord=True,
            )

        results = []
        for item in raw_results:
            driver_id = item[0]
            distance = float(item[1])
            coords = item[2]  # (lon, lat)
            results.append({
                'driver_id': driver_id,
                'distance_km': distance,
                'coordinates': coords,
            })
        return results

    def remove_driver(self, driver_id: str) -> None:
        self.client.zrem(settings.REDIS_LOCATIONS_KEY, driver_id)
        self.client.delete(f'{settings.REDIS_DRIVER_KEY_PREFIX}{driver_id}:state')