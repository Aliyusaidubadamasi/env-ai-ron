# Env-AI-Ron: urban ecological intelligence (MVP)

Nature-Centred AI for urban planting. The success measure is not how the city looks but how much
cooling, carbon storage, pollinator habitat and health benefit the land produces, and who gets it first.
Principles encoded in the code: **do no harm, be regenerative, be egalitarian.**

## Run it
```bash
pip install -r backend/requirements.txt
./run.sh                      # trains the segmenter once (~1 min), serves on http://localhost:8000
```
* Planner dashboard: http://localhost:8000/planner/ (dev key `dev-planner-key`; set `ENVAIRON_PLANNER_KEYS` for real use)
* Community monitor (PWA): http://localhost:8000/community/ (shows plans a planner has shared)
* API docs: http://localhost:8000/docs
* Tests: `cd backend && python -m pytest tests` (23 tests, ~3 min)
* Production: `docker build -t env-ai-ron .` and run with `ENVAIRON_PLANNER_KEYS=key1,key2`

## What is built (MVP deliverables)
| Deliverable | Where |
|---|---|
| API that accepts imagery and returns an optimised planting blueprint | `POST /api/v1/analyses` (`backend/app/main.py`) |
| CV model, 3 classes (concrete, canopy, bare soil) | `backend/app/segmentation.py`, metrics in `sample_output/segmentation_metrics.json` |
| Spatial optimiser (genetic algorithm + local search) | `backend/app/optimizer.py` |
| Native species recommender, refuses invasive/exotic/thirsty species | `backend/app/species.py` |
| Digital twin: 0 to 20 year canopy, cooling, carbon, habitat | `backend/app/simulation.py`, `frontend/planner/` |
| Planner dashboard (Leaflet), exports PDF, GeoJSON, GeoPackage, Shapefile | `frontend/planner/` |
| Community monitor PWA, geofenced photo check-ins, low-bandwidth | `frontend/community/` |
| Sample ROI report | `sample_output/Env-AI-Ron_sample_report.pdf` |

## Read this before trusting any number
1. **All imagery and GIS layers are synthetic.** `backend/app/synthetic.py` draws a Lagos-like tile with
   ground-truth labels so the whole pipeline can run and be tested. Ward names are fictional.
   Segmentation accuracy (about 95% pixels, 0.89 mean IoU) is measured on *held-out synthetic tiles*,
   so it says nothing about real Lagos imagery yet. Real labelled drone imagery is the first thing to add.
2. **The classifier is gradient-boosted trees on colour and texture**, not a deep network. The `Segmenter`
   interface is the swap point for a PyTorch U-Net / SegFormer / YOLOv8-seg trained on real labels.
3. **Surface heat is a proxy** computed from cover fractions (no thermal band in RGB imagery).
   Use Landsat/ECOSTRESS LST when available.
4. **Cooling and carbon coefficients are planning assumptions** (`config.SIM`), reported with a +/-40% range
   in every output. Calibrate against local temperature loggers before quoting absolute figures.
5. **Species traits and pollinator associations are provisional** and need review by Nigerian botanists
   (FRIN, university herbaria) before real planting.
6. Not in this MVP: classifying *existing* greenery as native vs ornamental, street-tree planting in
   rights-of-way, reinforcement-learning optimiser, PostGIS, SSO. See `docs/ARCHITECTURE.md`.

## Region lock
Uploads whose centre falls outside Lagos State, or larger than 30 km2, are refused: recommendations
elsewhere would not be accurate.
