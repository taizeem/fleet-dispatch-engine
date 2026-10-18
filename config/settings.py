import os
import platform
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env', override=False)

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'insecure-dev-key-change-in-prod')
DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() in ('true', '1', 't')

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'daphne',
    'channels',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    'rest_framework',
    'rest_framework_gis',
    'dispatch',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': os.getenv('POSTGRES_DB', 'dispatch_db'),
        'USER': os.getenv('POSTGRES_USER', 'dispatch_user'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'supersecret_dispatch_pass'),
        'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.getenv('POSTGRES_PORT', '5435'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', '127.0.0.1:9092')
KAFKA_LOCATION_TOPIC = os.getenv('KAFKA_LOCATION_TOPIC', 'driver-locations')
KAFKA_CONSUMER_GROUP = os.getenv('KAFKA_CONSUMER_GROUP', 'dispatch-location-consumer-group')

# Redis Configuration
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_LOCATIONS_KEY = 'drivers:locations'
REDIS_DRIVER_KEY_PREFIX = 'driver:'

# Redis Channel Layer for Django Channels WebSockets
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.pubsub.RedisPubSubChannelLayer',
        'CONFIG': {
            'hosts': [f'redis://{REDIS_HOST}:{REDIS_PORT}/0'],
        },
    },
}

# Batch DB Flusher Settings
BATCH_FLUSH_INTERVAL_SECONDS = 30.0
BATCH_FLUSH_SIZE = 500

if platform.system() == 'Windows':
    osgeo4w_path = Path(r'C:\OSGeo4W')
    if osgeo4w_path.exists():
        bin_path = str(osgeo4w_path / 'bin')
        if bin_path not in os.environ['PATH']:
            os.environ['PATH'] = bin_path + ';' + os.environ['PATH']
        gdal_dlls = list((osgeo4w_path / 'bin').glob('gdal*.dll'))
        if gdal_dlls:
            GDAL_LIBRARY_PATH = str(gdal_dlls[0])
        geos_dll = osgeo4w_path / 'bin' / 'geos_c.dll'
        if geos_dll.exists():
            GEOS_LIBRARY_PATH = str(geos_dll)