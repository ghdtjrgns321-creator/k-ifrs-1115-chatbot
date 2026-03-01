from pymongo import MongoClient
from langchain_upstage import UpstageEmbeddings
from app.config import settings

# 1. DB 및 컬렉션 연결
client = MongoClient(settings.mongo_uri)
db = client[settings.mongo_db_name]
vector_coll = db["k-ifrs-1115-chatbot"]           # 메인 벡터 저장소
qna_parents_coll = db["kifrs_1115_qna_parents"]   # QNA 전문
findings_parents_coll = db["kifrs_1115_findings_parents"] # 감리사례 전문

# 2. 임베딩 모델 초기화
embeddings = UpstageEmbeddings(
    model="solar-embedding-1-large-passage",
    upstage_api_key=settings.upstage_api_key
)

def get_parent_content(parent_id: str, source_type: str) -> str:
    """PDR: 자식 청크의 parent_id를 가지고 부모 원문을 찾아옵니다."""
    if not parent_id:
        return ""
    
    if source_type == "QNA":
        doc = qna_parents_coll.find_one({"_id": parent_id})
    elif source_type == "감리사례":
        doc = findings_parents_coll.find_one({"_id": parent_id})
    else:
        return ""
        
    return doc.get("full_content", doc.get("content", "")) if doc else ""

def search_all(query: str, limit: int = 20) -> list[dict]:
    """본문, QNA, 감리사례를 한 번에 검색하고 통합된 스키마로 반환합니다."""
    
    # 1. 질문을 벡터로 변환
    query_vector = embeddings.embed_query(query)
    
    # 2. MongoDB Atlas Vector Search (필터 없이 크게 한 번만 당겨옵니다)
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index", 
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": limit * 5,  # 넉넉하게 탐색
                "limit": limit
            }
        },
        {
            "$project": {
                "_id": 0,
                "embedding": 0,
                "score": {"$meta": "vectorSearchScore"} # 유사도 점수 추출
            }
        }
    ]
    
    raw_results = list(vector_coll.aggregate(pipeline))
    unified_results = []
    
    # 3. Python 단에서 소스 분류 및 스키마 통일 (라우팅)
    for doc in raw_results:
        metadata = doc.get("metadata", {})
        parent_id = metadata.get("parent_id")
        
        # 소스 식별 로직
        if parent_id and str(parent_id).startswith("QNA-"):
            source = "QNA"
        elif parent_id and (str(parent_id).startswith("FSS-") or str(parent_id).startswith("KICPA-")):
            source = "감리사례"
        else:
            source = "본문"
            
        # PDR 구조에 따라 부모 원문 가져오기 (본문은 부모가 없으므로 빈 문자열)
        full_content = get_parent_content(parent_id, source) if source != "본문" else doc.get("content", "")
        
        # 석훈님이 기획하신 통합 반환 구조
        unified_doc = {
            "source": source,
            "chunk_id": metadata.get("chunk_id", ""),
            "parent_id": parent_id,
            "content": doc.get("content", ""),
            "full_content": full_content,
            "score": doc.get("score", 0.0),
            "related_paragraphs": metadata.get("related_paragraphs", []),
            "hierarchy": metadata.get("hierarchy", "")
        }
        unified_results.append(unified_doc)
        
    return unified_results

# 간단한 테스트용 코드
if __name__ == "__main__":
    query = "밀어내기 매출 수익인식 어떻게 해?"
    results = search_all(query, limit=5)
    for r in results:
        print(f"[{r['source']}] 점수: {r['score']:.4f} | 계층: {r['hierarchy']}")