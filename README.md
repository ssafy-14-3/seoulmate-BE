# seoulmate-BE

공공데이터 기반 지역 정보 공유 커뮤니티(LocalHub) 백엔드 서버

## 기술 스택

- FastAPI
- SQLite + SQLAlchemy ORM
- OpenAI API (챗봇)

## 설치

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## 실행

```bash
# 데이터 시딩
python -m scripts.seed_locations

# 서버 시작
uvicorn app.main:app --reload
```

API Docs: http://localhost:8000/docs

## 배포

Render: `python -m scripts.seed_locations && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Netlify: 프론트엔드 배포 서비스
