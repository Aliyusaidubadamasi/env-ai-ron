from sqlalchemy import Column, Float, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base


class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    region = Column(String(255), nullable=False)
    center_lat = Column(Float, nullable=False)
    center_lng = Column(Float, nullable=False)
    climate_zone = Column(String(255), default="coastal_warm")
    soil_type = Column(String(255), default="loamy")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    images = relationship("ImageAsset", back_populates="site")
    predictions = relationship("LandCoverPrediction", back_populates="site")
    recommendations = relationship("SpeciesRecommendation", back_populates="site")
    blueprints = relationship("PlantingBlueprint", back_populates="site")
    observations = relationship("CitizenObservation", back_populates="site")


class ImageAsset(Base):
    __tablename__ = "image_assets"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_url = Column(String(500), nullable=False)
    image_type = Column(String(100), default="aerial")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    site = relationship("Site", back_populates="images")


class LandCoverPrediction(Base):
    __tablename__ = "land_cover_predictions"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    class_name = Column(String(100), nullable=False)
    confidence = Column(Float, default=0.0)
    mask_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    site = relationship("Site", back_populates="predictions")


class SpeciesRecommendation(Base):
    __tablename__ = "species_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    species_name = Column(String(255), nullable=False)
    native_status = Column(String(50), default="native")
    water_need = Column(String(50), default="moderate")
    pollinator_value = Column(Float, default=0.0)
    carbon_sequestration_score = Column(Float, default=0.0)
    shade_value = Column(Float, default=0.0)
    climate_zone_match = Column(String(100), default="coastal_warm")
    invasive_risk = Column(String(50), default="low")
    reason = Column(Text, default="Recommended for ecological restoration")

    site = relationship("Site", back_populates="recommendations")


class PlantingBlueprint(Base):
    __tablename__ = "planting_blueprints"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    recommended_tree_count = Column(Integer, default=0)
    total_temperature_reduction = Column(Float, default=0.0)
    biodiversity_gain = Column(Float, default=0.0)
    roi_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    site = relationship("Site", back_populates="blueprints")


class CitizenObservation(Base):
    __tablename__ = "citizen_observations"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    user_name = Column(String(255), nullable=True)
    photo_url = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    health_score = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    site = relationship("Site", back_populates="observations")
