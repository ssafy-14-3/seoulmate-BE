import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import ContentType, DataSource, Location, Region, Review


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.close()
        cls.db_path = tmp.name
        cls.engine = create_engine(f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False})
        cls.TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

        def override_get_db():
            db = cls.TestSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def setUp(self) -> None:
        db = self.TestSessionLocal()
        try:
            db.query(Review).delete()
            db.query(Location).delete()
            db.query(ContentType).delete()
            db.query(Region).delete()
            db.query(DataSource).delete()
            db.commit()

            data_source = DataSource(name="서울", source_file="test.json")
            region = Region(name="서울")
            content_type = ContentType(id=12, name="관광지")
            db.add_all([data_source, region, content_type])
            db.flush()

            location = Location(
                data_source_id=data_source.id,
                region_id=region.id,
                content_type_id=content_type.id,
                external_content_id="1001",
                name="경복궁",
                address="서울 종로구 사직로 161",
                first_image_url="https://example.com/img.jpg",
                latitude=37.5794,
                longitude=126.9770,
            )
            db.add(location)
            db.flush()

            review = Review(
                location_id=location.id,
                title="좋아요",
                content="정말 멋진 곳입니다.",
                rating=5,
                password="1234",
            )
            db.add(review)
            db.commit()

            self.location_id = location.id
            self.review_id = review.id
        finally:
            db.close()

    def test_locations_list_endpoint(self) -> None:
        response = self.client.get("/api/locations")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["name"], "경복궁")
        self.assertEqual(payload["items"][0]["category"], "관광지")
        self.assertEqual(payload["items"][0]["review_count"], 1)
        self.assertNotIn("password", payload["items"][0])

    def test_locations_search_with_q(self) -> None:
        db = self.TestSessionLocal()
        try:
            data_source = db.query(DataSource).first()
            region = db.query(Region).first()
            content_type = db.query(ContentType).first()
            location = Location(
                data_source_id=data_source.id,
                region_id=region.id,
                content_type_id=content_type.id,
                external_content_id="2002",
                name="경복궁 생과방",
                address="서울 종로구 사직로 161",
                first_image_url="https://example.com/annex.jpg",
            )
            db.add(location)
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/locations?q=경복궁&page=1&size=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["size"], 10)
        self.assertEqual(len(payload["items"]), 2)

        empty_response = self.client.get("/api/locations?q=없는장소&page=1&size=10")
        self.assertEqual(empty_response.status_code, 200)
        empty_payload = empty_response.json()
        self.assertEqual(empty_payload["total"], 0)
        self.assertEqual(empty_payload["items"], [])

    def test_location_detail_endpoint(self) -> None:
        response = self.client.get(f"/api/locations/{self.location_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], self.location_id)
        self.assertEqual(payload["review_count"], 1)
        self.assertEqual(len(payload["distribution"]), 5)
        self.assertEqual(payload["distribution"][0]["rating"], 5)
        self.assertEqual(payload["distribution"][0]["count"], 1)

    def test_review_crud_and_verify_endpoints(self) -> None:
        create_response = self.client.post(
            f"/api/locations/{self.location_id}/reviews",
            json={
                "title": "야경 최고",
                "content": "밤에 보면 더 예뻐요.",
                "rating": 4,
                "password": "5678",
            },
        )
        self.assertEqual(create_response.status_code, 201)
        created_review_id = create_response.json()["id"]
        self.assertNotIn("password", create_response.json())

        verify_response = self.client.post(
            f"/api/reviews/{created_review_id}/verify",
            json={"password": "5678"},
        )
        self.assertEqual(verify_response.status_code, 200)
        self.assertEqual(verify_response.json(), {"verified": True})

        update_fail_response = self.client.put(
            f"/api/reviews/{created_review_id}",
            json={
                "title": "수정 실패",
                "content": "비밀번호 틀림",
                "rating": 4,
                "password": "0000",
            },
        )
        self.assertEqual(update_fail_response.status_code, 401)
        self.assertEqual(update_fail_response.json()["detail"]["code"], "PASSWORD_MISMATCH")

        update_ok_response = self.client.put(
            f"/api/reviews/{created_review_id}",
            json={
                "title": "수정 성공",
                "content": "비밀번호 확인 완료",
                "rating": 5,
                "password": "5678",
            },
        )
        self.assertEqual(update_ok_response.status_code, 200)
        self.assertEqual(update_ok_response.json()["title"], "수정 성공")
        self.assertIsNotNone(update_ok_response.json()["updated_at"])

        delete_fail_response = self.client.request(
            "DELETE",
            f"/api/reviews/{created_review_id}",
            json={"password": "0000"},
        )
        self.assertEqual(delete_fail_response.status_code, 401)
        self.assertEqual(delete_fail_response.json()["detail"]["code"], "PASSWORD_MISMATCH")

        delete_ok_response = self.client.request(
            "DELETE",
            f"/api/reviews/{created_review_id}",
            json={"password": "5678"},
        )
        self.assertEqual(delete_ok_response.status_code, 204)

    def test_review_list_endpoint(self) -> None:
        response = self.client.get(f"/api/locations/{self.location_id}/reviews")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["id"], self.review_id)
        self.assertNotIn("password", payload["items"][0])

    def test_global_latest_reviews_endpoint(self) -> None:
        db = self.TestSessionLocal()
        try:
            data_source = db.query(DataSource).first()
            region = db.query(Region).first()
            content_type = db.query(ContentType).first()
            location2 = Location(
                data_source_id=data_source.id,
                region_id=region.id,
                content_type_id=content_type.id,
                external_content_id="3003",
                name="서울한양도성 백악구간",
                address="서울 종로구 북악산로",
                first_image_url="https://example.com/castle.jpg",
            )
            db.add(location2)
            db.flush()

            created_same = datetime(2026, 7, 14, 20, 30, 0)
            created_latest = datetime(2026, 7, 14, 21, 10, 0)

            first_review = db.query(Review).filter(Review.id == self.review_id).first()
            first_review.created_at = created_same

            same_time_newer_id_review = Review(
                location_id=location2.id,
                title="산책하기 좋은 장소",
                content="경치는 좋지만 일부 구간은 경사가 있습니다.",
                rating=4,
                password="5678",
                created_at=created_same,
            )
            latest_review = Review(
                location_id=self.location_id,
                title="야간 개장 최고",
                content="수문장 교대식이 인상 깊었습니다.",
                rating=5,
                password="9999",
                created_at=created_latest,
            )
            db.add_all([same_time_newer_id_review, latest_review])
            db.commit()

            first_review_id = first_review.id
            second_review_id = same_time_newer_id_review.id
            latest_review_id = latest_review.id
        finally:
            db.close()

        response = self.client.get("/api/reviews?page=1&size=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["size"], 10)
        self.assertEqual(len(payload["items"]), 3)
        self.assertEqual(payload["items"][0]["id"], latest_review_id)
        self.assertEqual(payload["items"][1]["id"], second_review_id)
        self.assertEqual(payload["items"][2]["id"], first_review_id)
        self.assertEqual(payload["items"][1]["location_name"], "서울한양도성 백악구간")
        self.assertIn("location_image_url", payload["items"][1])
        self.assertNotIn("password", payload["items"][1])

    def test_global_latest_reviews_validation_error(self) -> None:
        response = self.client.get("/api/reviews?page=0&size=10")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "VALIDATION_ERROR")

        response = self.client.get("/api/reviews?page=1&size=51")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "VALIDATION_ERROR")

    def test_stats_reviews_endpoint(self) -> None:
        response = self.client.get("/api/stats/reviews")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["by_category"]), 1)
        self.assertEqual(payload["by_category"][0]["category"], "관광지")
        self.assertEqual(payload["by_category"][0]["review_count"], 1)

    def test_chat_endpoint_without_api_key(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            response = self.client.post("/api/chat", json={"message": "경복궁 추천해줘", "history": []})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["code"], "CHAT_UPSTREAM_ERROR")

    def test_chat_endpoint_success(self) -> None:
        class MockOpenAIResponse:
            def __init__(self, body: dict) -> None:
                self._body = body

            def read(self) -> bytes:
                return json.dumps(self._body).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_body = {"choices": [{"message": {"content": "경복궁을 추천해요."}}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            with patch("urllib.request.urlopen", return_value=MockOpenAIResponse(mock_body)):
                response = self.client.post("/api/chat", json={"message": "경복궁 추천해줘", "history": []})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reply"], "경복궁을 추천해요.")
        self.assertGreaterEqual(len(payload["recommended_locations"]), 1)
        self.assertEqual(payload["recommended_locations"][0]["name"], "경복궁")

    def test_removed_legacy_endpoint(self) -> None:
        response = self.client.get("/locations")
        self.assertEqual(response.status_code, 404)

    def test_review_create_invalid_rating(self) -> None:
        response = self.client.post(
            f"/api/locations/{self.location_id}/reviews",
            json={
                "title": "별점 범위 테스트",
                "content": "별점이 잘못됨",
                "rating": 6,
                "password": "1234",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "INVALID_RATING")

    def test_review_update_not_found(self) -> None:
        response = self.client.put(
            "/api/reviews/99999",
            json={
                "title": "수정",
                "content": "없음",
                "rating": 3,
                "password": "1234",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "REVIEW_NOT_FOUND")

    def test_verify_review_not_found(self) -> None:
        response = self.client.post("/api/reviews/99999/verify", json={"password": "1234"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "REVIEW_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
