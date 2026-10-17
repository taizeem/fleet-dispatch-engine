from django.contrib.gis import admin
from .models import Driver, DriverLocation, Rider, RideRequest


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'id', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'id')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(DriverLocation)
class DriverLocationAdmin(admin.GISModelAdmin):
    list_display = ('driver', 'get_coordinates', 'recorded_at')
    list_filter = ('driver', 'recorded_at')
    search_fields = ('driver__name',)
    readonly_fields = ('id', 'recorded_at')
    gis_widget_kwargs = {
        'attrs': {
            'default_zoom': 13,
        }
    }

    @admin.display(description='Coordinates (Lat, Lon)')
    def get_coordinates(self, obj):
        return f'{obj.location.y:.6f}, {obj.location.x:.6f}'


@admin.register(Rider)
class RiderAdmin(admin.ModelAdmin):
    list_display = ('name', 'id', 'created_at', 'updated_at')
    search_fields = ('name', 'id')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(RideRequest)
class RideRequestAdmin(admin.GISModelAdmin):
    list_display = ('id', 'rider', 'driver', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('rider__name', 'driver__name', 'id')
    readonly_fields = ('id', 'created_at', 'updated_at')
    gis_widget_kwargs = {
        'attrs': {
            'default_zoom': 13,
        }
    }