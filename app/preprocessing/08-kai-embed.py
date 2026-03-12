import io
import sys
# Windows cp949 환경에서 이모지 출력 시 UnicodeEncodeError 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
import time
import os
from pymongo import MongoClient
from app.config import settings
from app.embeddings import embed_texts_sync

sys.stdout.reconfigure(encoding="utf-8")

CHILD_COLLECTION  = settings.mongo_collection_name
PARENT_COLLECTION = "k-ifrs-1115-kai-parents"

INPUT_FILE = "data/web/kai-1115.json"


def load_kai_to_atlas():
    if not os.path.exists(INPUT_FILE):
        print(f"파일을 찾을 수 없습니다: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]

    parent_docs = []
    child_docs = []

    for item in raw_items:
        edu_id = item["id"]
        content = item["content"]
        metadata = item["metadata"]
        hierarchy = metadata.get("hierarchy", "")

        # Parent: 원본 전체 저장
        parent_docs.append({
            "_id": edu_id,
            "content": content,
            "metadata": metadata,
        })

        # Child: 전체를 1개 청크로 임베딩 (3단 분할 불필요)
        contextual_text = f"[문맥: {hierarchy}]\n{content}"
        child_meta = {
            **metadata,
            "parent_id": edu_id,
            "chunk_type": "full",
            "chunk_id": f"{edu_id}_F",
        }
        child_docs.append({"text": contextual_text, "metadata": child_meta})

    # STEP 1. Parent 컬렉션
    parent_coll = db[PARENT_COLLECTION]
    print("1. 기존 KAI Parent 데이터를 삭제합니다...")
    p_del = parent_coll.delete_many({})
    print(f"   -> {p_del.deleted_count}개 삭제 완료.")

    print(f"2. 새로운 Parent {len(parent_docs)}개를 저장합니다...")
    parent_coll.insert_many(parent_docs)
    print("   -> Parent 적재 완료!")

    # STEP 2. Child 컬렉션 — EDU- 접두어만 선택 삭제 (본문/QNA/감리 보호)
    child_coll = db[CHILD_COLLECTION]
    print("\n3. 기존 Child 컬렉션에서 EDU- 데이터만 삭제합니다...")
    c_del = child_coll.delete_many({"parent_id": {"$regex": "^EDU-"}})
    print(f"   -> {c_del.deleted_count}개 삭제 완료.")

    print(f"\n4. 총 {len(child_docs)}개의 Child 청크 벡터 임베딩을 시작합니다...")

    success_count = 0
    for i, doc in enumerate(child_docs):
        try:
            vector = embed_texts_sync(
                [doc["text"]], settings.embed_passage_model
            )[0]
            mongo_doc = {
                "text": doc["text"],
                "embedding": vector,
                **doc["metadata"],
            }
            child_coll.insert_one(mongo_doc)
            success_count += 1
            print(f"   -> [{success_count}/{len(child_docs)}] {doc['metadata']['parent_id']} 적재 완료")
            time.sleep(0.05)
        except Exception as e:
            print(f"\n[SKIP] {doc['metadata']['parent_id']} 적재 실패: {e}")

    # STEP 3. 결과 보고서
    print(f"\n{'='*55}")
    print(f"KAI 교육자료 적재 최종 보고서")
    print(f"{'='*55}")
    print(f"Parent: {len(parent_docs)}개 저장")
    print(f"Child:  {success_count}/{len(child_docs)}개 임베딩 완료")
    print(f"{'='*55}")

    client.close()


if __name__ == "__main__":
    load_kai_to_atlas()
