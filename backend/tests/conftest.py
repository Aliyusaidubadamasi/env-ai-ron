import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="envairon-test-")
os.environ["ENVAIRON_DATA_DIR"] = _tmp          # isolate store + demo data from the real data dir
os.environ.pop("ENVAIRON_PLANNER_KEYS", None)   # dev key is used in tests

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.security import analysis_limiter, upload_limiter
    analysis_limiter.hits.clear(); upload_limiter.hits.clear()
    yield
