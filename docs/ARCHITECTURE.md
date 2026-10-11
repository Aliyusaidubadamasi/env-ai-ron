# Architecture and path to production

## Data flow
```
JPEG/PNG/GeoTIFF + GeoJSON (soil, zoning, wards/health) + DEM GeoTIFF
   -> prepare_image (resample to 2.5 m/px, snap to 20 m cells)
   -> Segmenter -> land-cover map (concrete / canopy / bare soil)
   -> ecology.build_eco_state: heat proxy, ecological voids, equity score, plantable mask
   -> species.recommend_ranked per site context (soil, flood, tight plot), diversity split
   -> optimizer (GA + swap local search) on cooling, carbon, pollinator, equity (+ ward fairness cap)
   -> simulation.project: yearly 0-20 canopy, cooling, carbon, habitat
   -> blueprint GeoJSON/GPKG/SHP, overlays, PDF report
```

## Why the optimiser is not a simple ranking
* Cooling saturates (diminishing returns when trees are piled together).
* Pollinator connectivity rewards stepping stones near habitat.
* Equity rewards both depth (most vulnerable cells) and reach (number of vulnerable blocks within ~100 m).
* A fairness penalty stops any single ward taking over 30% of sites.
Scores are normalised so 1.0 means "as good as a plan that chases that goal alone".

## Do-no-harm rules (enforced and tested)
Never plant over existing canopy (>35%), roads, drainage channels or non-bare cells; never recommend a
non-native, invasive or high-water species; no species above its share cap; flood-prone cells only get
flood-tolerant species.

## Security
API-key auth on planner routes (constant-time compare), unguessable 128-bit analysis ids validated before
file access, magic-byte upload sniffing, size caps, decompression-bomb limit, per-IP rate limits, strict CSP
and security headers, EXIF stripped from community photos, unpublished analyses return 404 to the public.

## Low-bandwidth design
Community API returns compact point GeoJSON (5-decimal coordinates, short keys) behind gzip; phone shrinks
photos to <=640 px JPEG (~40-70 KB) before upload; server stores WebP thumbnails; service worker caches the
app shell and last-seen plan; PDF report is ~0.35 MB.

## Production roadmap
| MVP | Production |
|---|---|
| JSON files in `data/store` | PostgreSQL + PostGIS tables (analyses, sites, observations); S3/GCS objects for rasters |
| Tree-based segmenter | PyTorch U-Net / SegFormer on GPU, native vs ornamental classes, YOLOv8 for crowns |
| In-process analysis | Celery/Cloud Run job queue with GPU workers; tiled COG processing for city-scale rasters |
| Genetic algorithm | GA plus RL or MILP refinement, street-tree workflow |
| API keys | OIDC/SSO, role-based access, audit log |
| Synthetic demo data | Real drone/Sentinel/Planet imagery, municipal GIS, LST, health data, community photo model |
