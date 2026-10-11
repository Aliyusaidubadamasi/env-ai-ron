"""Pixel-level land-cover segmentation: concrete / canopy / bare soil.

MVP model: gradient-boosted trees on colour + texture features (scikit-learn). It trains in
under a minute on CPU, needs no GPU, and gives a measurable baseline.

PRODUCTION PATH: the `Segmenter` interface (predict(image) -> label map) is what the rest of
the platform depends on. Replace `TreeSegmenter` with a PyTorch U-Net / SegFormer / Mask R-CNN
trained on labelled Lagos drone imagery and nothing downstream changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
from scipy import ndimage as ndi
from sklearn.ensemble import HistGradientBoostingClassifier

from . import config

CLASS_NAMES = ("concrete", "canopy", "bare_soil")
MODEL_PATH = config.MODEL_DIR / "segmenter.joblib"
METRICS_PATH = config.MODEL_DIR / "segmenter_metrics.json"


class Segmenter(Protocol):
    def predict(self, image: np.ndarray) -> np.ndarray: ...


def extract_features(image: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8 -> (H*W, F) float32 features."""
    img = image.astype(np.float32)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    total = r + g + b + 1e-6
    bright = total / 3
    exg = 2 * g - r - b                      # excess green: vegetation
    rg = (r - g) / total                     # red-green balance: laterite / rust vs grey
    rb = (r - b) / total
    sat = (img.max(-1) - img.min(-1)) / (img.max(-1) + 1e-6)
    maps = [r, g, b, bright, exg, rg, rb, sat]
    for base in (bright, exg):
        for size in (5, 15):
            m = ndi.uniform_filter(base, size)
            s = np.sqrt(np.maximum(ndi.uniform_filter(base * base, size) - m * m, 0))
            maps += [m, s]
    gx, gy = ndi.sobel(bright, axis=1), ndi.sobel(bright, axis=0)
    maps.append(np.hypot(gx, gy))
    for chan in (rg, sat):
        maps.append(ndi.uniform_filter(chan, 9))
    return np.stack(maps, -1).reshape(-1, len(maps)).astype(np.float32)


class TreeSegmenter:
    def __init__(self, clf: HistGradientBoostingClassifier):
        self.clf = clf

    def predict(self, image: np.ndarray, tile: int = 800, margin: int = 16) -> np.ndarray:
        """Label map for any size image; large rasters are processed in overlapping tiles."""
        h, w = image.shape[:2]
        if h * w <= tile * tile * 1.5:
            return self._predict_block(image)
        out = np.zeros((h, w), np.uint8)
        for y0 in range(0, h, tile):
            for x0 in range(0, w, tile):
                ya, xa = max(0, y0 - margin), max(0, x0 - margin)
                yb, xb = min(h, y0 + tile + margin), min(w, x0 + tile + margin)
                block = self._predict_block(image[ya:yb, xa:xb])
                y1, x1 = min(h, y0 + tile), min(w, x0 + tile)
                out[y0:y1, x0:x1] = block[y0 - ya:y1 - ya, x0 - xa:x1 - xa]
        return out

    def _predict_block(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        pred = self.clf.predict(extract_features(image)).reshape(h, w).astype(np.uint8)
        # remove salt-and-pepper speckle without erasing real small objects
        return ndi.median_filter(pred, size=3)

    def predict_proba(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        return self.clf.predict_proba(extract_features(image)).reshape(h, w, -1)


def load_model() -> TreeSegmenter:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"No trained segmenter at {MODEL_PATH}. Run: python -m app.train_segmenter"
        )
    return TreeSegmenter(joblib.load(MODEL_PATH))


def iou_scores(truth: np.ndarray, pred: np.ndarray, n: int = 3) -> dict[str, float]:
    out = {}
    for k in range(n):
        inter = np.logical_and(truth == k, pred == k).sum()
        union = np.logical_or(truth == k, pred == k).sum()
        out[CLASS_NAMES[k]] = float(inter / union) if union else float("nan")
    return out


def train_and_evaluate(n_train_tiles: int = 6, n_test_tiles: int = 3, samples_per_tile: int = 60_000,
                       seed: int = 7) -> dict:
    """Train on synthetic tiles, evaluate on *different* held-out tiles (different seeds)."""
    from .synthetic import generate_tile

    rng = np.random.default_rng(seed)
    xs, ys = [], []
    for i in range(n_train_tiles):
        t = generate_tile(1000 + i)
        feats = extract_features(t.image)
        lab = t.labels.reshape(-1)
        # class-balanced-ish sampling so rare canopy pixels are not drowned out
        idx = []
        for k in range(3):
            where = np.flatnonzero(lab == k)
            idx.append(rng.choice(where, size=min(samples_per_tile // 3, where.size), replace=False))
        idx = np.concatenate(idx)
        xs.append(feats[idx])
        ys.append(lab[idx])
    X, y = np.concatenate(xs), np.concatenate(ys)

    clf = HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.1, max_leaf_nodes=48, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.1, random_state=seed,
    )
    clf.fit(X, y)
    model = TreeSegmenter(clf)

    per_tile, all_t, all_p = [], [], []
    for i in range(n_test_tiles):
        t = generate_tile(5000 + i)
        pred = model.predict(t.image)
        per_tile.append({"seed": 5000 + i, "pixel_accuracy": float((pred == t.labels).mean()),
                         "iou": iou_scores(t.labels, pred)})
        all_t.append(t.labels.ravel())
        all_p.append(pred.ravel())
    tt, pp = np.concatenate(all_t), np.concatenate(all_p)
    cm = np.zeros((3, 3), np.int64)
    for a in range(3):
        for b in range(3):
            cm[a, b] = np.logical_and(tt == a, pp == b).sum()
    iou = iou_scores(tt, pp)
    metrics = {
        "data": "SYNTHETIC tiles (seeds 1000+ train, 5000+ held-out test). Not real Lagos imagery.",
        "classes": list(CLASS_NAMES),
        "train_tiles": n_train_tiles, "test_tiles": n_test_tiles,
        "train_samples": int(len(y)),
        "heldout_pixel_accuracy": float((tt == pp).mean()),
        "heldout_iou": iou,
        "heldout_mean_iou": float(np.nanmean(list(iou.values()))),
        "confusion_matrix_rows_truth_cols_pred": cm.tolist(),
        "per_tile": per_tile,
    }
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, MODEL_PATH, compress=3)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    return metrics
