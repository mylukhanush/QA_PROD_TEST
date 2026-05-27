import os

from celery import Celery
from dotenv import load_dotenv

from app import create_app


def _build_celery_app() -> Celery:
    # Keep worker config loading consistent with run.py/flask runtime.
    load_dotenv()
    flask_app = create_app()

    broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    worker_concurrency = int(
        os.getenv("CELERY_WORKER_CONCURRENCY", os.getenv("MAX_SUITE_WORKERS", "5"))
    )

    celery = Celery(
        flask_app.import_name,
        broker=broker_url,
        backend=result_backend,
        include=["runner.celery_tasks"],
    )
    celery.conf.update(
        task_track_started=True,
        worker_concurrency=worker_concurrency,
        worker_prefetch_multiplier=1,
    )

    class FlaskTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return super().__call__(*args, **kwargs)

    celery.Task = FlaskTask
    return celery


celery_app = _build_celery_app()
