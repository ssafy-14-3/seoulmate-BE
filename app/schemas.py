from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReviewCreate(BaseModel):
    title: str
    content: str
    rating: int
    password: str


class ReviewOut(BaseModel):
    id: int
    location_id: int
    title: str
    content: str
    rating: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RatingDistribution(BaseModel):
    rating: int
    count: int


class LocationOut(BaseModel):
    id: int
    name: str
    address: Optional[str] = None
    address_detail: Optional[str] = None
    zipcode: Optional[str] = None
    telephone: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    map_level: Optional[int] = None
    first_image_url: Optional[str] = None
    second_image_url: Optional[str] = None
    review_count: int = 0
    avg_rating: Optional[float] = None
    distribution: list[RatingDistribution] = []

    class Config:
        from_attributes = True
