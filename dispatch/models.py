import uuid
from django.contrib.gis.db import models
from django.utils import timezone


class DriverStatus(models.TextChoices):
    OFFLINE = 'offline', 'Offline'
    ONLINE = 'online', 'Online'
    BUSY = 'busy', 'Busy'


class RideRequestStatus(models.TextChoices):
    REQUESTED = 'requested', 'Requested'
    ASSIGNED = 'assigned', 'Assigned'
    IN_PROGRESS = 'in_progress', 'In Progress'
    COMPLETED = 'completed', 'Completed'
    CANCELLED = 'cancelled', 'Cancelled'


class Driver(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=DriverStatus.choices,
        default=DriverStatus.OFFLINE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'drivers'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.get_status_display()})'


class DriverLocation(models.Model):
    id = models.BigAutoField(primary_key=True)
    driver = models.ForeignKey(
        Driver,
        on_delete=models.CASCADE,
        related_name='locations',
    )
    location = models.PointField(srid=4326, spatial_index=True)
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'driver_locations'
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['driver', '-recorded_at']),
        ]

    def __str__(self):
        return f'{self.driver.name} at {self.location.y:.5f}, {self.location.x:.5f} ({self.recorded_at})'


class Rider(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'riders'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class RideRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rider = models.ForeignKey(
        Rider,
        on_delete=models.CASCADE,
        related_name='ride_requests',
    )
    driver = models.ForeignKey(
        Driver,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_rides',
    )
    pickup_location = models.PointField(srid=4326, spatial_index=True)
    dropoff_location = models.PointField(srid=4326, spatial_index=True)
    status = models.CharField(
        max_length=20,
        choices=RideRequestStatus.choices,
        default=RideRequestStatus.REQUESTED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ride_requests'
        ordering = ['-created_at']

    def __str__(self):
        return f'Ride {self.id} - {self.rider.name} [{self.get_status_display()}]'