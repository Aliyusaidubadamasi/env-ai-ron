# Env-AI-Ron API Specification

## Base URL
- Development: http://localhost:8000

## Endpoints

### GET /health
Returns health status for the backend service.

### POST /api/v1/upload-image
Accepts a file upload with an image or GeoTIFF payload.

Request:
- multipart/form-data
- file: uploaded image

Response:
```json
{
  "message": "Image uploaded successfully",
  "filename": "sample.tif",
  "content_type": "image/tiff",
  "size_bytes": 1048576,
  "status": "queued_for_analysis"
}
```

### GET /api/v1/sites/{site_id}
Returns site metadata.

### POST /api/v1/sites/{site_id}/analyze
Starts a land-cover analysis job for a given site.

### GET /api/v1/sites/{site_id}/recommendations
Returns species recommendations and ecological rationale.

### POST /api/v1/sites/{site_id}/optimize
Generates a planting blueprint based on ecological weights.

### GET /api/v1/sites/{site_id}/simulation
Returns 5, 10, and 20-year projected ecological impact.

### POST /api/v1/observations
Records community-sourced tree health observations.

### GET /api/v1/species
Returns native species matched by region and soil preference.
