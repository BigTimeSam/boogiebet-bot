FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as an unprivileged user: a code-execution bug in the bot or a dependency
# then lands as UID 10001, not root. Copy with ownership so /app is writable.
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
USER appuser

# Writable, appuser-owned dir for the persistence file; a named volume mounts
# here in compose so state survives container recreation.
RUN mkdir -p /home/appuser/data

CMD ["python", "bot/main.py"]
