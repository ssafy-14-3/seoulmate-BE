import json
import os
from fastapi.middleware.cors import CORSMiddleware
import re
import urllib.error
import urllib.request
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .models import ContentType, Location, Review, Region
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

def _build_chat_messages(
    payload: ChatRequest,
    recommendations: list[ChatRecommendedLocation],
) -> list[dict[str, str]]:
    location_text = "\n".join(
        [
            (
                f"- 장소명: {location.name}\n"
                f"  카테고리: {location.category}\n"
                f"  평균 평점: "
                f"{location.avg_rating if location.avg_rating is not None else '평점 없음'}"
            )
            for location in recommendations
        ]
    )

    system_content = f"""
너는 서울의 관광지와 지역 정보를 안내하는 챗봇이다.

다음 규칙에 따라 답변해라.

1. 사용자의 질문에 친절하고 자연스럽게 답변한다.
2. 답변은 특별한 요청이 없다면 3~5문장 이내로 간결하게 작성한다.
3. 아래에 제공된 추천 장소가 있다면 해당 정보를 우선 활용한다.
4. 제공된 장소 정보에 없는 운영시간, 가격, 휴무일 등의 정보를 임의로 만들어내지 않는다.
5. 정확히 알 수 없는 정보는 확인이 필요하다고 안내한다.
6. 사용자가 장소를 추천해 달라고 하면 장소명과 추천 이유를 함께 설명한다.
7. 이전 대화 이력이 있으면 해당 맥락을 이어서 답변한다.
8. 답변에 불필요한 추론 과정이나 내부 판단 과정을 노출하지 않는다.
9. 서울 관광 및 지역 정보와 무관한 질문에는 간단히 답변하되, 관광 안내 기능을 자연스럽게 소개한다.

현재 검색된 추천 장소 정보:
{location_text or "관련 장소를 찾지 못했습니다."}
""".strip()

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": system_content,
        }
    ]

    for history_item in payload.history:
        if history_item.role not in ("user", "assistant"):
            continue

        messages.append(
            {
                "role": history_item.role,
                "content": history_item.content,
            }
        )

    messages.append(
        {
            "role": "user",
            "content": payload.message,
        }
    )

    return messages

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


def _call_openai(request_body: dict, api_key: str, logger: logging.Logger, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_intent_with_gpt(message: str, model: str, api_key: str, logger: logging.Logger) -> tuple[Optional[dict], str]:
    system = (
        "당신은 사용자의 한국어 질문에서 세 가지 값을 추출하는 도우미입니다: "
        "'area' (예: '종로구' 또는 '홍대입구' 등), "
        "'category' (정확히 하나: 관광지, 레포츠, 문화시설, 쇼핑, 숙박, 여행코스, 축제공연행사), "
        "'preference' (선택사항, 예: '아이와 함께', '데이트', '조용한 곳').\n"
        "응답은 반드시 JSON 객체 하나만 출력하세요. 예: "
        "{\"area\": \"강남구\", \"category\": \"관광지\", \"preference\": \"아이와 함께\"}\n"
        "만약 'area' 또는 'category'를 정확히 판단할 수 없으면 해당 값을 null로 설정하세요. 다른 설명을 붙이지 마세요."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"질문: {message}\n\nJSON으로만 응답해 주세요."},
    ]
    request_body = {"model": model, "messages": messages, "reasoning_effort": "minimal", "max_completion_tokens": 300}
    try:
        payload = _call_openai(request_body, api_key, logger)
    except Exception:
        logger.exception("intent parse OpenAI call failed")
        raise

    choices = payload.get("choices") or []
    if not choices:
        return None, ""

    first = choices[0]
    msg = first.get("message") if isinstance(first, dict) else None
    content = (msg.get("content", "") if isinstance(msg, dict) else "") or ""

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed, content
    except Exception:
        m = re.search(r"\{.*\}", content, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict):
                    return parsed, content
            except Exception:
                pass

    return None, content


def _ask_gpt_recommend(candidates: List[dict], preference: Optional[str], user_message: str, model: str, api_key: str, logger: logging.Logger) -> tuple[Optional[dict], str]:
    cand_text = "\n".join(
        [
            f"- id: {c['id']}\n  name: {c['name']}\n  address: {c.get('address')}\n  avg_rating: {c.get('avg_rating')}\n  review_count: {c.get('review_count')}\n  latest_review: {c.get('latest_review') or ''}"
            for c in candidates
        ]
    )
    system = (
        "당신은 서울의 장소를 추천하는 도우미입니다. 아래에 제공된 후보 목록에서 최대 3개를 선택하세요. "
        "반드시 후보의 'id'만 사용하여 추천하고, 후보 목록에 없는 장소를 생성하거나 추가하지 마세요. "
        "출력은 반드시 JSON으로만 아래 형식으로 반환하세요:\n"
        '{"answer": "<간단한 안내/요약>", "recommendations": [{"location_id": 123, "reason": "추천 이유(1~2문장)"}]}'
        "\n추천 이유는 후보 데이터(리뷰 수, 평균 평점, 최신 리뷰 등)에 기반하여 작성하세요."
    )
    user = (
        f"사용자 질문: {user_message}\n"
        f"선호: {preference or ''}\n\n"
        f"후보 목록:\n{cand_text}\n\n"
        "JSON 형식으로만 응답하세요."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    request_body = {"model": model, "messages": messages, "reasoning_effort": "minimal", "max_completion_tokens": 600}
    try:
        payload = _call_openai(request_body, api_key, logger)
    except Exception:
        logger.exception("recommend OpenAI call failed")
        raise

    choices = payload.get("choices") or []
    if not choices:
        return None, ""

    first = choices[0]
    msg = first.get("message") if isinstance(first, dict) else None
    content = (msg.get("content", "") if isinstance(msg, dict) else "") or ""

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed, content
    except Exception:
        m = re.search(r"\{.*\}", content, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, dict):
                    return parsed, content
            except Exception:
                pass

    return None, content


def _db_top_n(db: Session, n: int = 3) -> List[dict]:
    review_stats = _review_stats_subquery(db)
    rows = (
        db.query(Location, ContentType.name.label("category_name"), review_stats.c.review_count, review_stats.c.avg_rating)
        .join(ContentType, Location.content_type_id == ContentType.id)
        .outerjoin(review_stats, review_stats.c.location_id == Location.id)
        .order_by(func.coalesce(review_stats.c.review_count, 0).desc(), func.coalesce(review_stats.c.avg_rating, 0).desc(), Location.id.asc())
        .limit(n)
        .all()
    )
    result = []
    for row in rows:
        loc = row.Location
        result.append(
            {
                "id": loc.id,
                "name": loc.name,
                "category": row.category_name,
                "address": loc.address,
                "image_url": loc.first_image_url,
                "review_count": int(row.review_count or 0),
                "avg_rating": _rounded(row.avg_rating),
            }
        )
    return result


@app.post("/api/chat", response_model=ChatResponse)
def chat_api(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    logger = logging.getLogger("uvicorn.error")

    # Legacy quick candidates (keyword based)
    quick_candidates = _search_recommended_locations(db, payload.message)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()

    # If API key missing, fallback to DB top-n
    if not api_key:
        logger.error("OPENAI_API_KEY가 설정되지 않았습니다. DB 폴백을 반환합니다.")
        top = _db_top_n(db, 3)
        return ChatResponse(
            reply="챗봇 서버 호출에 실패하여 데이터베이스 상위 결과를 반환합니다.",
            answer=None,
            recommended_locations=[
                ChatRecommendedLocation(**t, reason=f"리뷰 {t['review_count']}건 · 평균 평점 {t['avg_rating']}")
                for t in top
            ],
        )

    # 1) Try to parse intent (area, category, preference)
    try:
        intent, raw = _parse_intent_with_gpt(payload.message, model, api_key, logger)
    except Exception:
        top = _db_top_n(db, 3)
        return ChatResponse(
            reply="챗봇 서버 호출에 실패하여 데이터베이스 상위 결과를 반환합니다.",
            answer=None,
            recommended_locations=[
                ChatRecommendedLocation(**t, reason=f"리뷰 {t['review_count']}건 · 평균 평점 {t['avg_rating']}")
                for t in top
            ],
        )

    # If GPT didn't return JSON intent, treat as legacy reply
    if intent is None:
        return ChatResponse(reply=raw or "", answer=None, recommended_locations=quick_candidates)

    area = (intent.get("area") or "").strip() if intent.get("area") else None
    category = (intent.get("category") or "").strip() if intent.get("category") else None
    preference = (intent.get("preference") or "").strip() if intent.get("preference") else None

    allowed_categories = {"관광지", "레포츠", "문화시설", "쇼핑", "숙박", "여행코스", "축제공연행사"}

    missing_parts = []
    if not area:
        missing_parts.append("지역(예: '종로구')")
    if not category or category not in allowed_categories:
        missing_parts.append("카테고리(관광지/레포츠/문화시설/쇼핑/숙박/여행코스/축제공연행사 중 하나)")
    if missing_parts:
        ask = "정확한 " + " 및 ".join(missing_parts) + "을/를 입력해 주세요."
        return ChatResponse(reply=ask, answer=None, recommended_locations=[])

    # DB search by area + category (limit 10, sorted by review count desc, avg desc)
    review_stats = _review_stats_subquery(db)
    area_pattern = f"%{area}%"
    rows = (
        db.query(Location, ContentType.name.label("category_name"), review_stats.c.review_count, review_stats.c.avg_rating)
        .join(ContentType, Location.content_type_id == ContentType.id)
        .join(Region, Location.region_id == Region.id)
        .outerjoin(review_stats, review_stats.c.location_id == Location.id)
        .filter(ContentType.name == category)
        .filter(
            or_(
                Region.name.ilike(area_pattern),
                Location.address.ilike(area_pattern),
                Location.address_detail.ilike(area_pattern),
            )
        )
        .order_by(func.coalesce(review_stats.c.review_count, 0).desc(), func.coalesce(review_stats.c.avg_rating, 0).desc(), Location.id.asc())
        .limit(10)
        .all()
    )

    if not rows:
        return ChatResponse(reply="해당 지역 및 카테고리에서 장소를 찾을 수 없습니다. 다른 지역 또는 카테고리를 입력해 주세요.", answer=None, recommended_locations=[])

    # If single result, return directly
    if len(rows) == 1:
        row = rows[0]
        loc = row.Location
        item = ChatRecommendedLocation(
            id=loc.id,
            name=loc.name,
            category=row.category_name,
            address=loc.address,
            image_url=loc.first_image_url,
            review_count=int(row.review_count or 0),
            avg_rating=_rounded(row.avg_rating),
            reason="검색 조건과 일치하는 유일한 결과입니다.",
        )
        reply = f"요청하신 조건에 맞는 장소가 하나 있습니다: {loc.name}."
        return ChatResponse(reply=reply, answer=reply, recommended_locations=[item])

    # Multiple results: build candidate list with latest review
    candidates = []
    for row in rows:
        loc = row.Location
        latest_review = db.query(Review).filter(Review.location_id == loc.id).order_by(Review.created_at.desc()).first()
        candidates.append(
            {
                "id": loc.id,
                "name": loc.name,
                "address": loc.address,
                "image_url": loc.first_image_url,
                "review_count": int(row.review_count or 0),
                "avg_rating": _rounded(row.avg_rating),
                "latest_review": (latest_review.content if latest_review else None),
            }
        )

    # Ask GPT to rank/recommend up to 3 among candidates
    try:
        parsed_rec, raw_rec = _ask_gpt_recommend(candidates, preference, payload.message, model, api_key, logger)
    except Exception:
        # fallback to top 3 from DB order
        fallback = candidates[:3]
        return ChatResponse(
            reply="챗봇 서버 호출에 실패하여 데이터베이스 상위 결과를 반환합니다.",
            answer=None,
            recommended_locations=[
                ChatRecommendedLocation(
                    id=item["id"],
                    name=item["name"],
                    category=None,
                    address=item["address"],
                    image_url=item["image_url"],
                    review_count=item["review_count"],
                    avg_rating=item["avg_rating"],
                    reason=f"리뷰 {item['review_count']}건 · 평균 평점 {item['avg_rating']}",
                )
                for item in fallback
            ],
        )

    if not parsed_rec:
        return ChatResponse(reply=raw_rec or "", answer=None, recommended_locations=[
            ChatRecommendedLocation(
                id=c["id"],
                name=c["name"],
                category=None,
                address=c["address"],
                image_url=c["image_url"],
                avg_rating=c["avg_rating"],
                review_count=c["review_count"],
                reason=None,
            )
            for c in candidates[:3]
        ])

    answer_text = parsed_rec.get("answer") or ""
    recs = parsed_rec.get("recommendations") or []

    final_items: List[ChatRecommendedLocation] = []
    allowed_ids = {c["id"] for c in candidates}
    seen = set()
    for r in recs:
        try:
            lid = int(r.get("location_id"))
        except Exception:
            continue
        if lid in seen or lid not in allowed_ids:
            continue
        seen.add(lid)
        cand = next((c for c in candidates if c["id"] == lid), None)
        if not cand:
            continue
        reason = r.get("reason") or ""
        final_items.append(
            ChatRecommendedLocation(
                id=cand["id"],
                name=cand["name"],
                category=None,
                address=cand["address"],
                image_url=cand["image_url"],
                review_count=cand["review_count"],
                avg_rating=cand["avg_rating"],
                reason=reason,
            )
        )
        if len(final_items) >= 3:
            break

    if not final_items:
        fallback = candidates[:3]
        final_items = [
            ChatRecommendedLocation(
                id=item["id"],
                name=item["name"],
                category=None,
                address=item["address"],
                image_url=item["image_url"],
                review_count=item["review_count"],
                avg_rating=item["avg_rating"],
                reason=f"리뷰 {item['review_count']}건 · 평균 평점 {item['avg_rating']}",
            )
            for item in fallback
        ]

    return ChatResponse(reply=answer_text or "", answer=answer_text or None, recommended_locations=final_items)

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
