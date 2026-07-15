import json
import os
from fastapi.middleware.cors import CORSMiddleware
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .models import ContentType, Location, Review
from .schemas import (
    CategoryReviewStatsItem,
    ChatRecommendedLocation,
    ChatRequest,
    ChatResponse,
    GlobalReviewListItem,
    GlobalReviewListResponse,
    LocationDetailOut,
    LocationListItem,
    LocationListResponse,
    RatingDistribution,
    ReviewCreate,
    ReviewListResponse,
    ReviewOut,
    ReviewPasswordBody,
    ReviewStatsResponse,
    ReviewUpdate,
    ReviewVerifyResponse,
)



app = FastAPI(title="Seoulmate BE", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": "요청 값이 올바르지 않습니다.",
                "errors": exc.errors(),
            }
        },
    )


def _raise_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _ensure_rating_range(rating: int) -> None:
    if rating < 1 or rating > 5:
        _raise_error(400, "INVALID_RATING", "별점은 1~5 범위여야 합니다.")


def _get_location_or_404(db: Session, location_id: int) -> Location:
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        _raise_error(404, "LOCATION_NOT_FOUND", "해당 장소를 찾을 수 없습니다.")
    return location


def _get_review_or_404(db: Session, review_id: int) -> Review:
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        _raise_error(404, "REVIEW_NOT_FOUND", "해당 리뷰를 찾을 수 없습니다.")
    return review


def _review_stats_subquery(db: Session):
    return (
        db.query(
            Review.location_id.label("location_id"),
            func.count(Review.id).label("review_count"),
            func.avg(Review.rating).label("avg_rating"),
        )
        .group_by(Review.location_id)
        .subquery()
    )


def _rounded(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


@app.get("/api/locations", response_model=LocationListResponse)
def list_locations_api(
    category: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> LocationListResponse:
    review_stats = _review_stats_subquery(db)
    query = (
        db.query(
            Location,
            ContentType.name.label("category_name"),
            review_stats.c.review_count,
            review_stats.c.avg_rating,
        )
        .join(ContentType, Location.content_type_id == ContentType.id)
        .outerjoin(review_stats, review_stats.c.location_id == Location.id)
    )

    if category:
        query = query.filter(ContentType.name == category)
    if q:
        query = query.filter(Location.name.ilike(f"%{q}%"))

    total = query.count()
    skip = (page - 1) * size
    rows = query.order_by(Location.created_at.desc()).offset(skip).limit(size).all()

    items = [
        LocationListItem(
            id=row.Location.id,
            name=row.Location.name,
            category=row.category_name,
            address=row.Location.address,
            image_url=row.Location.first_image_url,
            review_count=int(row.review_count or 0),
            avg_rating=_rounded(row.avg_rating),
        )
        for row in rows
    ]
    return LocationListResponse(total=total, page=page, size=size, items=items)


@app.get("/api/locations/{location_id}", response_model=LocationDetailOut)
def get_location_api(location_id: int, db: Session = Depends(get_db)) -> LocationDetailOut:
    review_stats = _review_stats_subquery(db)
    row = (
        db.query(
            Location,
            ContentType.name.label("category_name"),
            review_stats.c.review_count,
            review_stats.c.avg_rating,
        )
        .join(ContentType, Location.content_type_id == ContentType.id)
        .outerjoin(review_stats, review_stats.c.location_id == Location.id)
        .filter(Location.id == location_id)
        .first()
    )
    if not row:
        _raise_error(404, "LOCATION_NOT_FOUND", "해당 장소를 찾을 수 없습니다.")

    distribution_rows = (
        db.query(Review.rating, func.count(Review.id))
        .filter(Review.location_id == location_id)
        .group_by(Review.rating)
        .all()
    )
    distribution_by_rating = {int(rating): int(count) for rating, count in distribution_rows}
    distribution = [
        RatingDistribution(rating=rating, count=distribution_by_rating.get(rating, 0))
        for rating in range(5, 0, -1)
    ]

    return LocationDetailOut(
        id=row.Location.id,
        name=row.Location.name,
        category=row.category_name,
        address=row.Location.address,
        latitude=row.Location.latitude,
        longitude=row.Location.longitude,
        description=None,
        image_url=row.Location.first_image_url,
        review_count=int(row.review_count or 0),
        avg_rating=_rounded(row.avg_rating),
        distribution=distribution,
    )


@app.get("/api/locations/{location_id}/reviews", response_model=ReviewListResponse)
def list_reviews_api(
    location_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> ReviewListResponse:
    _get_location_or_404(db, location_id)
    query = db.query(Review).filter(Review.location_id == location_id)
    total = query.count()
    skip = (page - 1) * size
    reviews = query.order_by(Review.created_at.desc(), Review.id.desc()).offset(skip).limit(size).all()
    return ReviewListResponse(total=total, page=page, size=size, items=reviews)


@app.get("/api/reviews", response_model=GlobalReviewListResponse)
def list_latest_reviews_api(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> GlobalReviewListResponse:
    query = db.query(Review, Location).join(Location, Review.location_id == Location.id)
    total = query.count()
    skip = (page - 1) * size
    rows = query.order_by(Review.created_at.desc(), Review.id.desc()).offset(skip).limit(size).all()

    items = [
        GlobalReviewListItem(
            id=review.id,
            location_id=review.location_id,
            location_name=location.name,
            location_image_url=location.first_image_url,
            title=review.title,
            content=review.content,
            rating=review.rating,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )
        for review, location in rows
    ]
    return GlobalReviewListResponse(total=total, page=page, size=size, items=items)


@app.post("/api/locations/{location_id}/reviews", response_model=ReviewOut, status_code=201)
def create_review(location_id: int, payload: ReviewCreate, db: Session = Depends(get_db)) -> ReviewOut:
    _get_location_or_404(db, location_id)
    _ensure_rating_range(payload.rating)

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


@app.put("/api/reviews/{review_id}", response_model=ReviewOut)
def update_review(review_id: int, payload: ReviewUpdate, db: Session = Depends(get_db)) -> ReviewOut:
    review = _get_review_or_404(db, review_id)
    _ensure_rating_range(payload.rating)
    if review.password != payload.password:
        _raise_error(401, "PASSWORD_MISMATCH", "비밀번호가 일치하지 않습니다.")

    review.title = payload.title
    review.content = payload.content
    review.rating = payload.rating
    review.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(review)
    return review


@app.delete("/api/reviews/{review_id}", status_code=204)
def delete_review(
    review_id: int,
    payload: ReviewPasswordBody = Body(...),
    db: Session = Depends(get_db),
) -> None:
    review = _get_review_or_404(db, review_id)
    if review.password != payload.password:
        _raise_error(401, "PASSWORD_MISMATCH", "비밀번호가 일치하지 않습니다.")

    db.delete(review)
    db.commit()


@app.post("/api/reviews/{review_id}/verify", response_model=ReviewVerifyResponse)
def verify_review_password(
    review_id: int,
    payload: ReviewPasswordBody,
    db: Session = Depends(get_db),
) -> ReviewVerifyResponse:
    review = _get_review_or_404(db, review_id)
    if review.password != payload.password:
        _raise_error(401, "PASSWORD_MISMATCH", "비밀번호가 일치하지 않습니다.")
    return ReviewVerifyResponse(verified=True)


def _search_recommended_locations(db: Session, message: str) -> list[ChatRecommendedLocation]:
    review_stats = _review_stats_subquery(db)
    normalized = message.strip()
    keywords = [word for word in re.findall(r"[0-9A-Za-z가-힣]+", normalized) if len(word) >= 2]
    if not keywords:
        keywords = [normalized] if normalized else []
    keywords = keywords[:5]

    query = (
        db.query(
            Location.id,
            Location.name,
            ContentType.name.label("category_name"),
            review_stats.c.avg_rating,
            review_stats.c.review_count,
        )
        .join(ContentType, Location.content_type_id == ContentType.id)
        .outerjoin(review_stats, review_stats.c.location_id == Location.id)
    )
    if keywords:
        keyword_conditions = []
        for keyword in keywords:
            pattern = f"%{keyword}%"
            keyword_conditions.append(
                or_(
                    Location.name.ilike(pattern),
                    Location.address.ilike(pattern),
                    ContentType.name.ilike(pattern),
                )
            )
        query = query.filter(or_(*keyword_conditions))

    rows = query.order_by(func.coalesce(review_stats.c.review_count, 0).desc(), Location.id.asc()).limit(5).all()
    return [
        ChatRecommendedLocation(
            id=row.id,
            name=row.name,
            category=row.category_name,
            avg_rating=_rounded(row.avg_rating),
        )
        for row in rows
    ]


def _build_chat_messages(payload: ChatRequest, recommendations: list[ChatRecommendedLocation]) -> list[dict[str, str]]:
    if recommendations:
        context_lines = [
            f"- {item.name} ({item.category or '미분류'}, 평균평점: {item.avg_rating if item.avg_rating is not None else '리뷰 없음'})"
            for item in recommendations
        ]
        context_text = "\n".join(context_lines)
    else:
        context_text = "- 관련 장소 정보를 찾지 못했습니다."

    system_prompt = (
        "너는 서울 지역 여행/장소 추천 도우미다. "
        "아래 장소 데이터만 근거로 추천하고, 없으면 없다고 말해라.\n"
        f"{context_text}"
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in payload.history[-10:]:
        if item.role in {"user", "assistant"}:
            messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": payload.message})
    return messages


@app.post("/api/chat", response_model=ChatResponse)
def chat_api(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    recommendations = _search_recommended_locations(db, payload.message)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        _raise_error(502, "CHAT_UPSTREAM_ERROR", "챗봇 서버 호출에 실패했습니다.")

    request_body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": _build_chat_messages(payload, recommendations),
        "max_tokens": 400,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        _raise_error(502, "CHAT_UPSTREAM_ERROR", "챗봇 서버 호출에 실패했습니다.")

    choices = response_payload.get("choices")
    if not choices:
        _raise_error(502, "CHAT_UPSTREAM_ERROR", "챗봇 서버 호출에 실패했습니다.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    reply = message.get("content") if isinstance(message, dict) else None
    if not reply:
        _raise_error(502, "CHAT_UPSTREAM_ERROR", "챗봇 서버 호출에 실패했습니다.")

    return ChatResponse(reply=reply, recommended_locations=recommendations)


@app.get("/api/stats/reviews", response_model=ReviewStatsResponse)
def review_stats_api(db: Session = Depends(get_db)) -> ReviewStatsResponse:
    rows = (
        db.query(
            ContentType.name.label("category"),
            func.count(Review.id).label("review_count"),
            func.avg(Review.rating).label("avg_rating"),
        )
        .join(Location, Location.content_type_id == ContentType.id)
        .outerjoin(Review, Review.location_id == Location.id)
        .group_by(ContentType.id, ContentType.name)
        .order_by(ContentType.name.asc())
        .all()
    )
    return ReviewStatsResponse(
        by_category=[
            CategoryReviewStatsItem(
                category=row.category,
                review_count=int(row.review_count or 0),
                avg_rating=_rounded(row.avg_rating),
            )
            for row in rows
        ]
    )
