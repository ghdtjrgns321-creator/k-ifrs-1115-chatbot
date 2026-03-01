from typing import Annotated, Sequence
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class RAGState(TypedDict):
    # 1. 대화 히스토리 (LangGraph가 자동으로 메시지를 누적)
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # 2. 파이프라인 제어 변수
    standalone_query: str        # 문맥이 반영된 독립형 질문
    retry_count: int             # 재검색 횟수 (무한 루프 방지용)
    
    # 3. 문서 검색 및 평가 파이프라인
    retrieved_docs: list[dict]   # 1차 검색 결과 (Vector + BM25 + RRF)
    reranked_docs: list[dict]    # 2차 검색 결과 (Upstage Reranker + 룰 적용)
    relevant_docs: list[dict]    # 3차 품질 평가 통과 결과 (CRAG - Yes 판정)
    
    # 4. 생성 결과물
    answer: str                  # LLM이 생성한 순수 텍스트 답변
    cited_sources: list[dict]    # 최종 포맷팅에 쓰일 인용 출처 메타데이터