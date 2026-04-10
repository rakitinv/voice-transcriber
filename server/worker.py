"""
Celery worker entry point.

Usage:
    celery -A worker worker --loglevel=info --queues=asr,diarization,llm,cleanup
"""

from workers.celery_app import celery_app

if __name__ == "__main__":
    celery_app.start()
