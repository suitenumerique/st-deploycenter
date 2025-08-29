web: bin/scalingo_run_web
worker: celery -A deploycenter.celery_app worker --task-events --beat -l INFO -c $CELERY_CONCURRENCY
postdeploy: python manage.py migrate