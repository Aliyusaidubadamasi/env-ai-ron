FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 ENVAIRON_ENV=production
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend
WORKDIR /srv/backend
RUN python -m app.train_segmenter
EXPOSE 8000
# ENVAIRON_PLANNER_KEYS must be supplied at run time (comma-separated keys).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
