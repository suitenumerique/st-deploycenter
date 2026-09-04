web: bin/scalingo_run_web
# No worker is deployed: every @shared_task runs synchronously, either from the
# cron entries in cron.json ("manage.py run_task <task>") or inline. Do NOT call
# .delay()/.apply_async() anywhere — nothing would consume the queue. Re-enable
# this line first if that ever changes.
# worker: celery -A deploycenter.celery_app worker --task-events --beat -l INFO -c $CELERY_CONCURRENCY
postdeploy: python manage.py migrate