"""CLI: python -m app.train_segmenter  -> trains and writes models/segmenter.joblib + metrics."""
import json
import time

from .segmentation import train_and_evaluate

if __name__ == "__main__":
    t0 = time.time()
    m = train_and_evaluate()
    print(json.dumps({k: v for k, v in m.items() if k != "per_tile"}, indent=2))
    print(f"done in {time.time() - t0:.0f}s")
