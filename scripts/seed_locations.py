import json
from datetime import datetime
from pathlib import Path

from app.database import SessionLocal, init_db
from app.models import ContentType, DataSource, Location, Region

DATA_DIR = Path(__file__).resolve().parents[1] / "app" / "data"


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, str) and len(value) == 14:
        return datetime.strptime(value, "%Y%m%d%H%M%S")
    return None


def _parse_float(value):
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return float(value)


def _parse_int(value):
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return int(value)


def seed_file(path: Path, session) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))

    region_name = payload.get("region") or "서울"
    content_type_name = payload.get("contentType") or "기타"
    content_type_id = int(payload.get("contentTypeId") or 0)

    region = session.query(Region).filter(Region.name == region_name).first()
    if not region:
        region = Region(name=region_name)
        session.add(region)
        session.flush()

    content_type = session.query(ContentType).filter(ContentType.id == content_type_id).first()
    if not content_type:
        content_type = ContentType(id=content_type_id, name=content_type_name)
        session.add(content_type)
        session.flush()
    elif content_type.name != content_type_name:
        content_type.name = content_type_name

    data_source = session.query(DataSource).filter(
        DataSource.name == region_name,
        DataSource.source_file == path.name,
    ).first()
    if not data_source:
        data_source = DataSource(
            name=region_name,
            provider="한국관광공사",
            license_type="공공누리",
            source_url="https://api.visitkorea.or.kr",
            source_file=path.name,
            collected_at=datetime.utcnow(),
        )
        session.add(data_source)
        session.flush()

    inserted = 0
    for item in payload.get("items", []):
        external_content_id = str(item.get("contentid") or "").strip()
        if not external_content_id:
            continue

        existing = session.query(Location).filter(
            Location.data_source_id == data_source.id,
            Location.external_content_id == external_content_id,
        ).first()

        location_data = {
            "data_source_id": data_source.id,
            "region_id": region.id,
            "content_type_id": content_type.id,
            "external_content_id": external_content_id,
            "name": _clean(item.get("title")) or "이름 없음",
            "address": _clean(item.get("addr1")),
            "address_detail": _clean(item.get("addr2")),
            "zipcode": _clean(item.get("zipcode")),
            "telephone": _clean(item.get("tel")),
            "longitude": _parse_float(item.get("mapx")),
            "latitude": _parse_float(item.get("mapy")),
            "map_level": _parse_int(item.get("mlevel")),
            "first_image_url": _clean(item.get("firstimage")),
            "second_image_url": _clean(item.get("firstimage2")),
            "category_code_1": _clean(item.get("cat1")),
            "category_code_2": _clean(item.get("cat2")),
            "category_code_3": _clean(item.get("cat3")),
            "area_code": _clean(item.get("areacode")),
            "sigungu_code": _clean(item.get("sigungucode")),
            "legal_region_code": _clean(item.get("lDongRegnCd")),
            "legal_sigungu_code": _clean(item.get("lDongSignguCd")),
            "class_system_1": _clean(item.get("lclsSystm1")),
            "class_system_2": _clean(item.get("lclsSystm2")),
            "class_system_3": _clean(item.get("lclsSystm3")),
            "copyright_code": _clean(item.get("cpyrhtDivCd")),
            "source_created_at": _parse_datetime(item.get("createdtime")),
            "source_modified_at": _parse_datetime(item.get("modifiedtime")),
        }

        if existing:
            for key, value in location_data.items():
                setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(Location(**location_data))
            inserted += 1

    session.commit()
    return inserted


def seed_all() -> None:
    init_db()
    with SessionLocal() as session:
        total_inserted = 0
        for path in sorted(DATA_DIR.glob("*.json")):
            inserted = seed_file(path, session)
            total_inserted += inserted
            print(f"{path.name}: {inserted} new locations")
        print(f"total new locations: {total_inserted}")


if __name__ == "__main__":
    seed_all()
