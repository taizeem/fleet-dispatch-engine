import signal
import sys
import time
import random
from django.core.management.base import BaseCommand
from dispatch.models import Driver, DriverStatus, RideRequest, RideRequestStatus
from dispatch.kafka_producer import KafkaProducerService
from dispatch.services.simulator import SimulatedVehicle

DEFAULT_CENTER_LAT = 40.7580
DEFAULT_CENTER_LON = -73.9855


class Command(BaseCommand):
    help = 'Simulates a live fleet of moving drivers, always including drivers assigned to active rides.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True

    def add_arguments(self, parser):
        parser.add_argument('--drivers', type=int, default=5, help='Number of background simulated drivers')
        parser.add_argument('--interval', type=float, default=1.5, help='Ping interval in seconds')
        parser.add_argument('--speed', type=float, default=45.0, help='Average driving speed in km/h')
        parser.add_argument('--center-lat', type=float, default=DEFAULT_CENTER_LAT)
        parser.add_argument('--center-lon', type=float, default=DEFAULT_CENTER_LON)

    def handle_shutdown(self, signum, frame):
        self.stdout.write(self.style.WARNING('\nStopping fleet simulator cleanly...'))
        self.running = False

    def handle(self, *args, **options):
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

        num_drivers = options['drivers']
        interval = options['interval']
        avg_speed = options['speed']
        center_lat = options['center_lat']
        center_lon = options['center_lon']

        vehicles = {}
        producer = KafkaProducerService.get_instance()

        # 1. Spawn background roving fleet
        for i in range(1, num_drivers + 1):
            driver_name = f'Sim Driver {i:02d}'
            driver, _ = Driver.objects.get_or_create(
                name=driver_name,
                defaults={'status': DriverStatus.ONLINE},
            )
            if driver.status == DriverStatus.OFFLINE:
                driver.status = DriverStatus.ONLINE
                driver.save(update_fields=['status'])

            init_lat = center_lat + random.uniform(-0.008, 0.008)
            init_lon = center_lon + random.uniform(-0.008, 0.008)
            vehicles[str(driver.id)] = SimulatedVehicle(
                driver=driver,
                initial_lat=init_lat,
                initial_lon=init_lon,
                speed_kmh=avg_speed,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'Fleet Simulator running with dynamic active ride detection ({interval}s interval)...'
            )
        )

        last_step_time = time.time()

        try:
            while self.running:
                now = time.time()
                elapsed = now - last_step_time
                last_step_time = now

                # 2. Automatically detect any driver assigned to an active ride and simulate them
                active_rides = RideRequest.objects.filter(
                    status__in=[
                        RideRequestStatus.OFFERED,
                        RideRequestStatus.ACCEPTED,
                        RideRequestStatus.ARRIVED,
                        RideRequestStatus.IN_PROGRESS,
                    ]
                ).select_related('driver', 'offered_driver')

                for ride in active_rides:
                    target_driver = ride.driver or ride.offered_driver
                    if target_driver and str(target_driver.id) not in vehicles:
                        # Position driver ~600m from pickup to simulate incoming trip
                        init_lat = ride.pickup_location.y + 0.005
                        init_lon = ride.pickup_location.x + 0.005
                        vehicles[str(target_driver.id)] = SimulatedVehicle(
                            driver=target_driver,
                            initial_lat=init_lat,
                            initial_lon=init_lon,
                            speed_kmh=avg_speed,
                        )
                        self.stdout.write(
                            self.style.NOTICE(
                                f'Attached active assigned driver: {target_driver.name} ({target_driver.id})'
                            )
                        )

                # 3. Step physics and stream pings to Kafka
                for driver_id, vehicle in list(vehicles.items()):
                    ping_data = vehicle.step(delta_seconds=elapsed)
                    producer.publish_ping(driver_id=driver_id, payload=ping_data)

                time.sleep(interval)

        finally:
            producer.flush(timeout=3.0)
            self.stdout.write(self.style.SUCCESS('Fleet simulator stopped.'))