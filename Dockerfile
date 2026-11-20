FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app

# ffmpeg strips location and device data from uploaded videos.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /data/media \
    && chown -R app /data
EXPOSE 8000

# Demo server on Fly.io (fly.toml builds this stage). Fly mounts its disk owned by root, so start as root only to
# hand /data to the app user, then drop to it. One machine runs the scheduler beside the web server.
# shortcut: nothing restarts the scheduler if it crashes; the live setup (docker compose, below) does.
FROM base AS fly
ENV HOME=/home/app
CMD ["sh", "-c", "chown -R app:app /data && exec setpriv --reuid=app --regid=app --init-groups sh -c 'python manage.py migrate --noinput && (python manage.py scheduler &) && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 2 --threads 8 --timeout 300 --access-logfile -'"]

# Live setup (docker compose builds this last stage by default).
FROM base
USER app
# No access log here: nginx already logs every request with the visitor's real address.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 3 --threads 8 --timeout 300"]
