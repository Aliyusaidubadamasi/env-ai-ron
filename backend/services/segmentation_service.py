from typing import Any


class SegmentationService:
    """Placeholder segmentation service for urban land cover inference."""

    def __init__(self) -> None:
        self.classes = ["concrete", "existing_canopy", "bare_soil"]

    def predict(self, image_path: str) -> dict[str, Any]:
        return {
            "image_path": image_path,
            "classes": self.classes,
            "predictions": {
                "concrete": 0.46,
                "existing_canopy": 0.31,
                "bare_soil": 0.23,
            },
            "status": "mock_prediction",
        }
