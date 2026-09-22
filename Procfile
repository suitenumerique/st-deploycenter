web: bin/scalingo_run_web
# Consumes the task queue and runs the periodic scheduler (see worker.py and
# docs/deployment.md, "Background tasks"). Every scheduled job runs here: the
# app declares no platform cron.
worker: python worker.py
postdeploy: python manage.py migrate
