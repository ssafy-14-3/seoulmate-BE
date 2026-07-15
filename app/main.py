from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .models import Location, Review
from .schemas import LocationOut, RatingDistribution, ReviewCreate, ReviewOut

app = FastAPI(title="Seoulmate BE", version="0.1.0")


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/locations", response_model=list[LocationOut])
def list_locations(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[LocationOut]:
    skip = (page - 1) * size
    locations = (
        db.query(Location)
        .order_by(Location.created_at.desc())
        .offset(skip)
        .limit(size)
        .all()
    )

    result: list[LocationOut] = []
    for location in locations:
        review_stats = (
            db.query(
                func.count(Review.id).label("review_count"),
                func.avg(Review.rating).label("avg_rating"),
            )
            .filter(Review.location_id == location.id)
            .one()
        )

        distribution = []
        for rating in range(5, 0, -1):
            count = (
                db.query(func.count(Review.id))
                .filter(Review.location_id == location.id, Review.rating == rating)
                .scalar()
            )
            distribution.append(RatingDistribution(rating=rating, count=count or 0))

        result.append(
            LocationOut(
                id=location.id,
                name=location.name,
                address=location.address,
                address_detail=location.address_detail,
                zipcode=location.zipcode,
                telephone=location.telephone,
                longitude=location.longitude,
                latitude=location.latitude,
                map_level=location.map_level,
                first_image_url=location.first_image_url,
                second_image_url=location.second_image_url,
                review_count=int(review_stats.review_count or 0),
                avg_rating=round(float(review_stats.avg_rating), 2) if review_stats.avg_rating is not None else None,
                distribution=distribution,
            )
        )
    return result


@app.get("/locations/{location_id}", response_model=LocationOut)
def get_location(location_id: int, db: Session = Depends(get_db)) -> LocationOut:
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    review_stats = (
        db.query(
            func.count(Review.id).label("review_count"),
            func.avg(Review.rating).label("avg_rating"),
        )
        .filter(Review.location_id == location.id)
        .one()
    )

    distribution = []
    for rating in range(5, 0, -1):
        count = (
            db.query(func.count(Review.id))
            .filter(Review.location_id == location.id, Review.rating == rating)
            .scalar()
        )
        distribution.append(RatingDistribution(rating=rating, count=count or 0))

    return LocationOut(
        id=location.id,
        name=location.name,
        address=location.address,
        address_detail=location.address_detail,
        zipcode=location.zipcode,
        telephone=location.telephone,
        longitude=location.longitude,
        latitude=location.latitude,
        map_level=location.map_level,
        first_image_url=location.first_image_url,
        second_image_url=location.second_image_url,
        review_count=int(review_stats.review_count or 0),
        avg_rating=round(float(review_stats.avg_rating), 2) if review_stats.avg_rating is not None else None,
        distribution=distribution,
    )


@app.get("/locations/{location_id}/reviews", response_model=list[ReviewOut])
def list_reviews(location_id: int, db: Session = Depends(get_db)) -> list[ReviewOut]:
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    reviews = db.query(Review).filter(Review.location_id == location_id).order_by(Review.created_at.desc()).all()
    return reviews


@app.post("/locations/{location_id}/reviews", response_model=ReviewOut, status_code=201)
def create_review(location_id: int, payload: ReviewCreate, db: Session = Depends(get_db)) -> ReviewOut:
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    review = Review(
        location_id=location_id,
        title=payload.title,
        content=payload.content,
        rating=payload.rating,
        password=payload.password,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review
