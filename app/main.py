# app/main.py
# FastAPI 애플리케이션 진입점
#
# lifespan 훅을 사용하는 이유:
#   BM25 인덱스는 MongoDB 전체 문서를 메모리에 로드해 빌드합니다.
#   첫 번째 요청에서 빌드하면 사용자가 12~27초 + BM25 빌드 시간을 기다려야 합니다.
#   서버 시작 시 사전 로드(warm-up)하여 첫 요청부터 정상 속도를 보장합니다.
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.routes import router
from app.config import settings

# 프로젝트 공통 로깅 설정 — 애플리케이션 진입점에서 1회만 설정
# Why: config.py에 두면 import 부작용 발생, 테스트 시 로깅 격리 불가
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행되는 수명 주기 핸들러."""
    # _build_bm25_index()는 MongoDB 전체를 읽는 무거운 동기 작업
    # run_in_executor로 스레드 풀에서 실행해 event loop 블로킹 방지
    import asyncio
    from app.retriever import _build_bm25_index

    logger.info("BM25 인덱스 사전 로드 시작")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _build_bm25_index)
        logger.info("BM25 인덱스 로드 완료, 서버 준비 완료")
    except Exception:
        # Why: BM25 빌드 실패 시에도 vector search만으로 동작 가능 (graceful degradation)
        logger.exception("BM25 인덱스 빌드 실패 — vector search만으로 동작합니다")
    yield


app = FastAPI(
    title="K-IFRS 1115 Chatbot API",
    description="한국 기업회계기준서 제1115호 전문 Q&A 챗봇 백엔드",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: Streamlit(:8501)에서 FastAPI(:8002)로 요청하므로 허용 필수
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    """루트 접속 시 Swagger UI로 리다이렉트합니다."""
    return RedirectResponse(url="/docs")
