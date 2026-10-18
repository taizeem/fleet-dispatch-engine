# Geo-Spatial Fleet Dispatch Engine

A production-grade, distributed geo-spatial dispatch and real-time fleet tracking platform inspired by the core architectures of Uber, Lyft, and Zomato. Built with **Python 3.11**, **Django & GeoDjango**, **PostgreSQL / PostGIS**, **Apache Kafka (KRaft mode)**, **Redis**, **Django Channels (Daphne ASGI)**, and **OSRM (Open Source Routing Machine)**.

---

## Architecture Overview

```
                          [ Driver GPS Pings (every 1-3s) ]
                                          │
                                          ▼
                         [ DRF Ping Ingestion API ]
                                (HTTP 202)
                                          │
                                          ▼
                            [ Apache Kafka Broker ]
                           (topic: driver-locations)
                                          │
                                          ▼
                        [ Kafka Consumer Daemon Worker ]
                         /               │             \
                        /                │              \
                       ▼                 ▼               ▼
          [ Redis GEO Index ]   [ PostGIS Batch Buffer ]  [ Django Channels Layer ]
          (sub-ms coordinates)    (bulk_create every 30s)    (Redis PubSub Backend)
                 │                       │                           │
                 │                       ▼                           ▼
                 │            [ PostgreSQL / PostGIS ]    [ Daphne ASGI WebSockets ]
                 │             (historical routes &        (ws://.../ws/rides/<id>/)
                 │              spatial fallback)                    │
                 ▼                                                   ▼
       [ Dispatch Matching Engine ]                        [ Live Rider Dashboard ]
      - OSRM Street-Network ETAs                           - Leaflet.js Map
      - 15s Time-Bound Offer Cascade                       - Animated Car Marker 🚗
      - 4-Digit Boarding OTP Verification                  - Turn-by-Turn Route Polyline
```

---

## Key Features Built

1. **High-Throughput GPS Ingestion (Kafka)**: Non-blocking DRF producer endpoint returning `202 Accepted` in `< 5ms`, buffering high-frequency driver coordinates in a partitioned Kafka topic.
2. **Sub-Millisecond Geospatial Indexing (Redis GEO)**: `GEOADD` and `GEOSEARCH` indexing driver coordinates for `< 2ms` spatial proximity queries within a 3km radius.
3. **Database Burnout Protection (PostGIS Batch Flusher)**: In-memory consumer buffering with scheduled bulk inserts (`DriverLocation.objects.bulk_create`) every 30 seconds or 500 records, complete with graceful shutdown flusher.
4. **Resilient Geospatial Dispatch Matching**: Redis `GEOSEARCH` primary matcher with automatic spherical fallback to GeoDjango PostGIS (`distance_lte`) if cache is unavailable.
5. **Time-Bound Driver Offer Cascade**: 15-second Redis TTL offer countdown. If declined or timed out, the engine automatically cascades to the next closest candidate driver.
6. **Trip Lifecycle State Machine**: Full progression through `REQUESTED` ➔ `OFFERED` ➔ `ACCEPTED` ➔ `ARRIVED` ➔ `IN_PROGRESS` (with 4-digit rider OTP validation) ➔ `COMPLETED` (automated fare receipt).
7. **Autonomous Multi-Driver Fleet Simulator**: Built-in physics engine calculating geodesic spherical coordinates, initial bearing, destination seeking toward active pickups, and autonomous wandering.
8. **Street-Network Routing & Accurate ETAs (OSRM)**: Turn-by-turn road distance, street-snapped route geometry, and ETA-based candidate ranking.
9. **Real-Time Interactive Dashboard**: Single-page Leaflet.js interface with Esri street tiles, route rendering, animated vehicle tracking, and one-click driver lifecycle buttons.

---

## Tech Stack

* **Backend Framework**: Python 3.11+, Django 5.0 (GeoDjango)
* **API Layer**: Django REST Framework, `djangorestframework-gis`
* **Primary Database**: PostgreSQL 16 with PostGIS 3.4 spatial extension
* **Message Broker**: Apache Kafka 3.7 in KRaft mode (Bitnami)
* **In-Memory Store**: Redis 7 (Geospatial index, state hashes, channel layer)
* **Real-Time WebSockets**: Django Channels 4.1, Daphne ASGI, `channels_redis`
* **Routing Engine**: Open Source Routing Machine (OSRM)
* **Frontend Dashboard**: Leaflet.js 1.9, Esri WorldStreetMap tiles
* **Package Manager & Tooling**: `uv` (fast Python package manager), Docker Compose

---

## Quickstart with Docker Compose

Run the entire distributed system—PostGIS, Redis, Kafka, Daphne Web Server, and Kafka Consumer—with a single command:

```bash
# 1. Clone repository
git clone https://github.com/taizeem/fleet-dispatch-engine.git
cd fleet-dispatch-engine

# 2. Build and launch all containerized services
docker compose up --build -d

# 3. Verify container health
docker compose ps
```

The system will start:
* **Dashboard & HTTP API**: `http://127.0.0.1:8000/dashboard/`
* **WebSocket Server**: `ws://127.0.0.1:8000/ws/rides/{ride_id}/`
* **PostgreSQL / PostGIS**: `127.0.0.1:5435`
* **Redis**: `127.0.0.1:6379`
* **Apache Kafka**: `127.0.0.1:9092`

---

## Interactive Dashboard & Live Movement

1. Open your browser to **`http://127.0.0.1:8000/dashboard/`**.
2. Click **Request Live Ride**:
   * OSRM calculates turn-by-turn route geometry and ETA.
   * Dashed cyan line renders on the street grid.
   * State changes to `OFFERED`.
3. In a separate terminal, launch the autonomous fleet simulator:
   ```bash
   docker compose exec web python manage.py simulate_fleet --drivers=5 --interval=1.0 --speed=50
   ```
4. On the dashboard, click **Accept Ride Offer**:
   * Status turns to `ACCEPTED` and the 4-digit boarding OTP lights up.
   * The vehicle marker **🚗** appears and navigates toward the pickup pin.
5. Click **Mark Arrived at Pickup** ➔ **Start Trip (Verify OTP)** ➔ **Complete Trip at Dropoff** to generate the final receipt.

---

## API Reference

### 1. Ingest GPS Ping
```http
POST /api/v1/drivers/location-ping/
Content-Type: application/json

{
  "driver_id": "a1111111-1111-1111-1111-111111111111",
  "latitude": 40.7580,
  "longitude": -73.9855
}
```
**Response**: `202 Accepted`

### 2. Request Ride
```http
POST /api/v1/rides/request/
Content-Type: application/json

{
  "rider_id": "b2222222-2222-2222-2222-222222222222",
  "pickup_latitude": 40.7580,
  "pickup_longitude": -73.9855,
  "dropoff_latitude": 40.7660,
  "dropoff_longitude": -73.9760
}
```
**Response**: `201 Created` (includes OSRM street polyline, road distance, and ETA)

### 3. Driver Offer Response
```http
POST /api/v1/rides/offer-response/
Content-Type: application/json

{
  "ride_id": "<ride_uuid>",
  "driver_id": "<driver_uuid>",
  "action": "accept"  // or "decline"
}
```

### 4. Trip Lifecycle Progression
* **Driver Arrival**: `POST /api/v1/rides/arrived/` (`ride_id`, `driver_id`)
* **Start Trip**: `POST /api/v1/rides/start-trip/` (`ride_id`, `driver_id`, `otp`)
* **Complete Trip**: `POST /api/v1/rides/complete-trip/` (`ride_id`, `driver_id`)

### 5. WebSocket Stream
```text
ws://127.0.0.1:8000/ws/rides/{ride_id}/
```
**Emitted Events**:
* `connection_established`: Initial handshake confirmation.
* `driver_accepted`: Driver details and security boarding OTP.
* `driver_location`: Real-time streaming coordinates (`latitude`, `longitude`, `timestamp`).
* `driver_arrived`: Notification of arrival at pickup.
* `trip_started`: Trip initiated.
* `trip_completed`: Final fare receipt and driven distance.

---

## Automated Test Suite

The project includes 32 comprehensive unit and integration tests covering spatial geometries, Kafka producer/consumer mocking, Redis GEO buffering, state machine cascades, asynchronous WebSockets, and OSRM routing.

Run all tests:

```bash
# Inside Docker
docker compose exec web python manage.py test dispatch

# Or locally
python manage.py test dispatch
```

```text
Ran 32 tests in 2.145s

OK
```

---

## License
MIT License. Open for educational and production use.
