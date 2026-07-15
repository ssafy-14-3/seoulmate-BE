from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .database import Base


class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(255), nullable=True)
    license_type = Column(String(255), nullable=True)
    source_url = Column(Text, nullable=True)
    source_file = Column(String(255), nullable=False)
    collected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "source_file", name="uq_data_source_name_file"),
    )

    locations = relationship("Location", back_populates="data_source")


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)

    locations = relationship("Location", back_populates="region")


class ContentType(Base):
    __tablename__ = "content_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    locations = relationship("Location", back_populates="content_type")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=False, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False, index=True)
    content_type_id = Column(Integer, ForeignKey("content_types.id"), nullable=False, index=True)
    external_content_id = Column(String(100), nullable=False)

    name = Column(String(255), nullable=False, index=True)
    address = Column(Text, nullable=True)
    address_detail = Column(Text, nullable=True)
    zipcode = Column(String(20), nullable=True)
    telephone = Column(String(50), nullable=True)

    longitude = Column(Float, nullable=True)
    latitude = Column(Float, nullable=True)
    map_level = Column(Integer, nullable=True)

    first_image_url = Column(Text, nullable=True)
    second_image_url = Column(Text, nullable=True)

    category_code_1 = Column(String(20), nullable=True)
    category_code_2 = Column(String(20), nullable=True)
    category_code_3 = Column(String(20), nullable=True)

    area_code = Column(String(20), nullable=True)
    sigungu_code = Column(String(20), nullable=True)
    legal_region_code = Column(String(20), nullable=True)
    legal_sigungu_code = Column(String(20), nullable=True)

    class_system_1 = Column(String(20), nullable=True)
    class_system_2 = Column(String(20), nullable=True)
    class_system_3 = Column(String(20), nullable=True)
    copyright_code = Column(String(20), nullable=True)

    source_created_at = Column(DateTime, nullable=True)
    source_modified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("data_source_id", "external_content_id", name="uq_location_data_source_external_id"),
    )

    data_source = relationship("DataSource", back_populates="locations")
    region = relationship("Region", back_populates="locations")
    content_type = relationship("ContentType", back_populates="locations")
    reviews = relationship("Review", back_populates="location", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False)
    password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
    )

    location = relationship("Location", back_populates="reviews")
