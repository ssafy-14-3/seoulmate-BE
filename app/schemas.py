from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    rating: int
    password: str = Field(min_length=4, max_length=20)


class ReviewUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    rating: int
    password: str = Field(min_length=4, max_length=20)


class ReviewPasswordBody(BaseModel):
    password: str = Field(min_length=4, max_length=20)


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


class LocationListItem(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    address: Optional[str] = None
    image_url: Optional[str] = None
    avg_rating: Optional[float] = None
    review_count: int = 0


class LocationListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[LocationListItem]


class LocationDetailOut(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    avg_rating: Optional[float] = None
    review_count: int = 0
    distribution: list[RatingDistribution] = Field(default_factory=list)


class ReviewListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[ReviewOut]


class GlobalReviewListItem(BaseModel):
    id: int
    location_id: int
    location_name: str
    location_image_url: Optional[str] = None
    title: str
    content: str
    rating: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class GlobalReviewListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[GlobalReviewListItem]


class ReviewVerifyResponse(BaseModel):
    verified: bool


class ChatHistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatHistoryItem] = Field(default_factory=list)


class ChatRecommendedLocation(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    avg_rating: Optional[float] = None


class ChatResponse(BaseModel):
    reply: str
    recommended_locations: list[ChatRecommendedLocation] = Field(default_factory=list)


class CategoryReviewStatsItem(BaseModel):
    category: str
    review_count: int
    avg_rating: Optional[float] = None


class ReviewStatsResponse(BaseModel):
    by_category: list[CategoryReviewStatsItem]
