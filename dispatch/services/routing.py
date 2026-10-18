import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, List
from django.conf import settings
from dispatch.services.simulator import haversine_distance

logger = logging.getLogger(__name__)

DEFAULT_OSRM_URL = 'http://router.project-osrm.org'


class RoutingService:
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or getattr(settings, 'OSRM_BASE_URL', DEFAULT_OSRM_URL)).rstrip('/')

    def get_driving_route(self, start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> Dict[str, Any]:
        """
        Queries OSRM driving profile.
        Returns: {
            'distance_km': float,
            'duration_minutes': float,
            'duration_seconds': float,
            'coordinates': List[[lat, lon]],  # Formatted for Leaflet [lat, lon]
            'strategy': 'OSRM_NETWORK' | 'HAVERSINE_FALLBACK'
        }
        """
        # OSRM expects coordinates in {lon},{lat};{lon},{lat} order
        url = f'{self.base_url}/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson'

        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'FleetDispatchEngine/1.0'}
            )
            with urllib.request.urlopen(req, timeout=2.5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get('code') == 'Ok' and data.get('routes'):
                        primary_route = data['routes'][0]
                        distance_meters = float(primary_route['distance'])
                        duration_sec = float(primary_route['duration'])

                        # GeoJSON coordinates are in [lon, lat] -> convert to Leaflet [lat, lon]
                        raw_coords = primary_route['geometry']['coordinates']
                        leaflet_coords = [[pt[1], pt[0]] for pt in raw_coords]

                        return {
                            'distance_km': round(distance_meters / 1000.0, 2),
                            'duration_minutes': round(duration_sec / 60.0, 1),
                            'duration_seconds': round(duration_sec, 1),
                            'coordinates': leaflet_coords,
                            'strategy': 'OSRM_NETWORK',
                        }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception) as exc:
            logger.warning('OSRM routing request failed (%s). Falling back to Haversine calculation.', exc)

        # Fallback Calculation: Great-circle distance + average city speed (30 km/h)
        dist_m = haversine_distance(start_lat, start_lon, end_lat, end_lon)
        dist_km = round(dist_m / 1000.0, 2)
        # 30 km/h is 500 meters per minute
        estimated_minutes = round(max(dist_m / 500.0, 1.0), 1)

        return {
            'distance_km': dist_km,
            'duration_minutes': estimated_minutes,
            'duration_seconds': round(estimated_minutes * 60.0, 1),
            'coordinates': [[start_lat, start_lon], [end_lat, end_lon]],
            'strategy': 'HAVERSINE_FALLBACK',
        }