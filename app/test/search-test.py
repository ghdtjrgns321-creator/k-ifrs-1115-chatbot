import sys
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from langchain_upstage import UpstageEmbeddings

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "kifrs_db")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "k-ifrs-1115-chatbot")

TEST_QUERIES = [
    "A회사는 고객에게 소프트웨어 라이선스와 1년간 기술지원 서비스를 묶어 판매합니다. 이를 하나의 수행의무로 볼 수 있나요, 아니면 구분하여 두 개의 수행의무로 처리해야 하나요?",
    "매출액의 5%를 성과급으로 추가 지급받는 계약에서 변동대가를 어떻게 추정하고 제약해야 하나요?",
    "A회사는 온라인 플랫폼을 운영하며 B회사의 상품을 중개합니다. 최종 가격 결정권은 A사에 있고 재고 위험은 B사가 부담합니다. 본인인가요, 대리인인가요?",
    "건설 계약 중에 고객이 추가 공사를 요청했습니다. 이것이 별개의 계약으로 처리되는 경우와 기존 계약 변경으로 처리되는 경우의 차이는 무엇인가요?",
]

def test_hybrid_search():
    print("🔍 MongoDB Atlas 하이브리드 검색 (Vector + Keyword) 테스트를 시작합니다...\n")

    query_embeddings = UpstageEmbeddings(model="solar-embedding-1-large-query")
    client = MongoClient(MONGO_URI)
    collection = client[DB_NAME][COLLECTION_NAME]

    if collection.count_documents({}) == 0:
        print("❌ 컬렉션이 비어 있습니다. 05번 적재 스크립트를 먼저 실행해 주세요.")
        return

    for query_idx, query in enumerate(TEST_QUERIES):
        print(f"{'='*70}")
        print(f"[질문 {query_idx + 1}/{len(TEST_QUERIES)}] {query}")
        print(f"{'='*70}")

        query_vector = query_embeddings.embed_query(query)

        #  1. Vector Search (무거운 임베딩 배열만 제외하고 다 가져오기)
        vector_pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index", 
                    "path": "embedding", 
                    "queryVector": query_vector,
                    "numCandidates": 100,
                    "limit": 10
                }
            },
            {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}}
        ]
        vector_results = list(collection.aggregate(vector_pipeline))

        #  2. Keyword Search
        keyword_pipeline = [
            {
                "$search": {
                    "index": "keyword_index",
                    "text": {
                        "query": query,
                        "path": "text" 
                    }
                }
            },
            {"$limit": 10},
            {"$project": {"embedding": 0, "score": {"$meta": "searchScore"}}}
        ]
        keyword_results = list(collection.aggregate(keyword_pipeline))

        #  3. RRF 융합
        fused_scores = {}

        for rank, doc in enumerate(vector_results):
            chunk_id = doc.get("chunk_id", f"v_{rank}") # 메타데이터 직접 접근!
            rrf_score = 1.0 / (rank + 1 + 60)
            fused_scores[chunk_id] = {
                "doc": doc, "vector_rank": rank+1, "keyword_rank": 999, "rrf_score": rrf_score
            }

        for rank, doc in enumerate(keyword_results):
            chunk_id = doc.get("chunk_id", f"k_{rank}")
            rrf_score = 1.0 / (rank + 1 + 60)
            
            if chunk_id in fused_scores:
                fused_scores[chunk_id]["rrf_score"] += rrf_score
                fused_scores[chunk_id]["keyword_rank"] = rank+1
            else:
                fused_scores[chunk_id] = {
                    "doc": doc, "vector_rank": 999, "keyword_rank": rank+1, "rrf_score": rrf_score
                }

        #  4. 도메인 가중치 적용 및 정렬
        final_results = []
        for chunk_id, data in fused_scores.items():
            doc = data["doc"]
            weight = float(doc.get("weight_score", 1.0))
            
            final_score = data["rrf_score"] * weight

            data["final_score"] = final_score
            data["weight"] = weight
            final_results.append(data)

        final_results.sort(key=lambda x: x["final_score"], reverse=True)

        #  5. 결과 출력
        print("\n [Hybrid + Re-ranking 적용 후 Top 3]")
        for idx, item in enumerate(final_results[:3]):
            doc = item["doc"]
            v_rank = item['vector_rank'] if item['vector_rank'] != 999 else "-"
            k_rank = item['keyword_rank'] if item['keyword_rank'] != 999 else "-"
            
            print(
                f"\n🏆 [Top {idx+1}] 최종 점수: {item['final_score']:.5f} "
                f"(Vector {v_rank}위, Keyword {k_rank}위)"
            )
            print(f"  ▶ 조항 ID  : {doc.get('chunk_id')}")
            print(f"  ▶ 카테고리 : {doc.get('category')} (가중치: {item['weight']})")
            print(f"  ▶ 계층경로 : {doc.get('hierarchy')}")
            
            content_preview = doc.get('text', '').replace('\n', ' ')
            print(f"  ▶ 본문미리보기: {content_preview[:120]}...")

    client.close()

if __name__ == "__main__":
    test_hybrid_search()