# Env-AI-Ron Architecture Overview

## Purpose
Env-AI-Ron is a nature-centred urban ecological intelligence platform designed to help cities identify heat-prone, biodiversity-poor zones and propose regenerative planting strategies using ecological data, AI, and GIS.

## System Layers

### 1. Data Ingestion Layer
- Aerial imagery, drone imagery, and satellite captures
- GeoTIFF, JPEG, GeoJSON, Shapefile inputs
- Public health and zoning metadata

### 2. Processing Layer
- FastAPI backend service
- Geospatial preprocessing with GeoPandas and Rasterio
- Semantic segmentation for land cover classification
- Planting optimization using weighted ecological scoring

### 3. Intelligence Layer
- U-Net / DeepLabV3+ segmentation model
- Candidate site scoring using heat reduction, carbon, biodiversity, and health equity
- Native species recommender filtered for local regional suitability

### 4. Simulation Layer
- Digital twin model for 5, 10, and 20-year ecological impact
- Canopy growth forecast
- temperature reduction estimation
- biodiversity index projections

### 5. Presentation Layer
- Planner dashboard for municipal users
- Community monitor for neighborhood-level engagement
- Mapbox GL overlays and downloadable GIS-ready outputs

## Technology Stack
- Backend: FastAPI, SQLAlchemy, PostGIS
- AI/ML: PyTorch, segmentation-models-pytorch
- Geospatial: GeoPandas, Rasterio, GDAL
- Frontend: Next.js + Mapbox
- Storage: AWS S3 or GCP Cloud Storage
- Databases: PostgreSQL with PostGIS

## MVP Goals
- detect concrete, canopy, bare soil from aerial imagery
- produce an optimized planting blueprint for a sample Lagos site
- display recommendations in a web map
- deliver sample ecological ROI summary
