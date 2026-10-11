#!/usr/bin/env bash
# Local quick start: trains the segmenter if needed, then serves API + both web apps on :8000
set -e
cd "$(dirname "$0")/backend"
[ -f models/segmenter.joblib ] || python3 -m app.train_segmenter
exec python3 -m uvicorn app.main:app --port 8000
