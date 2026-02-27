import sys

# Windows 터미널의 기본 인코딩(CP949)이 이모지/한글을 깨뜨리는 것을 방지합니다.
sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from dotenv import load_dotenv
from langchain_upstage import UpstageEmbeddings
from langchain_chroma import Chroma

load_dotenv()

# K-IFRS 1115호 핵심 5단계 모델 주제를 커버하는 다중 테스트 케이스
# 단일 케이스만 테스트하면 Re-ranking 효과를 편향되게 평가할 수 있어서 다양하게 구성
TEST_QUERIES = [
    # 수행의무 식별 (5단계 중 2단계)
    "A회사는 고객에게 소프트웨어 라이선스와 1년간 기술지원 서비스를 묶어 판매합니다. 이를 하나의 수행의무로 볼 수 있나요, 아니면 구분하여 두 개의 수행의무로 처리해야 하나요?",
    # 변동대가 추정 및 제약
    "매출액의 5%를 성과급으로 추가 지급받는 계약에서 변동대가를 어떻게 추정하고 제약해야 하나요?",
    # 본인/대리인 구분
    "A회사는 온라인 플랫폼을 운영하며 B회사의 상품을 중개합니다. 최종 가격 결정권은 A사에 있고 재고 위험은 B사가 부담합니다. 본인인가요, 대리인인가요?",
    # 계약 변경 처리
    "건설 계약 중에 고객이 추가 공사를 요청했습니다. 이것이 별개의 계약으로 처리되는 경우와 기존 계약 변경으로 처리되는 경우의 차이는 무엇인가요?",
]


def test_rag_search():
    print("🔍 ChromaDB 독립 검색 테스트를 시작합니다...")

    # 1. 검색 시에는 반드시 '-query' 모델을 사용합니다 (passage와 혼용 시 품질 급락)
    query_embeddings = UpstageEmbeddings(model="solar-embedding-1-large-query")

    # 2. Docker에서 돌아가고 있는 ChromaDB(8100 포트) 클라이언트 연결
    chroma_client = chromadb.HttpClient(host="localhost", port=8100)

    # 3. 04번 스크립트에서 적재한 'kifrs_1115' 컬렉션을 불러옵니다.
    vector_db = Chroma(
        client=chroma_client,
        collection_name="kifrs_1115",
        embedding_function=query_embeddings,
    )

    # 컬렉션에 실제로 데이터가 있는지 먼저 확인합니다.
    collection = chroma_client.get_collection("kifrs_1115")
    print(f"📦 컬렉션 내 청크 수: {collection.count()}")
    if collection.count() == 0:
        print("❌ 컬렉션이 비어 있습니다. 먼저 04-embed-chroma.py를 실행해 주세요.")
        return

    # 4. 다중 테스트 쿼리를 순회하며 각각 검색 품질을 평가합니다.
    for query_idx, query in enumerate(TEST_QUERIES):
        print(f"\n{'='*60}")
        print(f"[쿼리 {query_idx + 1}/{len(TEST_QUERIES)}] {query}")
        print("="*60)

        # 5. 유사도 검색 실행
        # k=10으로 넉넉하게 가져온 뒤 Re-ranking을 적용합니다.
        # k=5면 Re-ranking 전/후 차이가 거의 없어서 효과 검증이 어렵습니다.
        raw_results = vector_db.similarity_search_with_score(query, k=10)

        reranked_results = []
        for doc, raw_distance in raw_results:
            # 메타데이터에서 04번 스크립트가 심어둔 가중치를 꺼냅니다 (없으면 기본값 1.0)
            weight = float(doc.metadata.get("weight_score", 1.0))

            # 🌟 Re-ranking 핵심 공식:
            # ChromaDB는 거리가 짧을수록 유사도가 높습니다.
            # 가중치가 높은 조항(예: 적용지침B=1.2)은 거리를 더 많이 줄여서 순위를 올립니다.
            adjusted_distance = raw_distance / weight

            reranked_results.append({
                "doc": doc,
                "raw_distance": raw_distance,
                "weight": weight,
                "adjusted_distance": adjusted_distance,
            })

        # 조정된 거리(adjusted_distance) 기준 오름차순 정렬 (낮을수록 상위)
        reranked_results.sort(key=lambda x: x["adjusted_distance"])

        print("\n🚀 [Re-ranking 적용 후 Top 3]")
        for idx, item in enumerate(reranked_results[:3]):
            doc = item["doc"]
            print(
                f"\n🏆 [Top {idx+1}] "
                f"보정거리: {item['adjusted_distance']:.4f} / "
                f"원본거리: {item['raw_distance']:.4f}"
            )
            print(f"  ▶ 조항 ID  : {doc.metadata.get('chunk_id')}")
            print(f"  ▶ 카테고리 : {doc.metadata.get('category')} (가중치: {item['weight']})")
            print(f"  ▶ 계층경로 : {doc.metadata.get('hierarchy')}")
            content_preview = doc.page_content.replace("\n", " ")
            print(f"  ▶ 본문미리보기: {content_preview[:120]}...")


if __name__ == "__main__":
    test_rag_search()
