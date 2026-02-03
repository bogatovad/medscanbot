from celery import Celery
from celery.schedules import crontab

from app.config import settings

app = Celery("tasks", broker=settings.CELERY_BROKER)

app.autodiscover_tasks([
    "app.workers",
])

