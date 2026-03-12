import re
from pymongo import MongoClient
from rank_bm25 import BM25Okapi
from app.config import settings
from app.embeddings import embed_query_sync

# ── 상수 ────────────────────────────────────────────────────────────────────────
QNA_PARENT_COLL = "k-ifrs-1115-qna-parents"
FINDINGS_PARENT_COLL = "k-ifrs-1115-findings-parents"
KAI_PARENT_COLL = "k-ifrs-1115-kai-parents"

VECTOR_TOP_K = 100  # 후보 풀 확장
RRF_K = 60  # RRF 논문 권장값
QNA_SUPPLEMENT = 15  # QNA 보조 최대 추가 수
FINDINGS_SUPPLEMENT = 15  # 감리사례 보조 최대 추가 수
KAI_SUPPLEMENT = 5  # 교육자료 보조 최대 추가 수


# ── Lazy 초기화 ──────────────────────────────────────────────────────────────────
_db = None
_bm25: BM25Okapi | None = None
_bm25_corpus: list[dict] | None = None


def _get_db():
    global _db
    if _db is None:
        client = MongoClient(settings.mongo_uri)
        _db = client[settings.mongo_db_name]
    return _db


def _generate_hypothetical_doc(query: str) -> str:
    """HyDE: 질문에 대한 가상 K-IFRS 조항 텍스트를 생성합니다.

    grade 통과 문서가 부족할 때 폴백으로만 호출됩니다.
    실패 시 원본 쿼리로 폴백하여 파이프라인이 중단되지 않습니다.
    """
    from app.agents import hyde_agent
    from app.prompts import HYDE_PROMPT

    try:
        result = hyde_agent.run_sync(HYDE_PROMPT.format(query=query))
        return result.output.strip() if result.output else query
    except Exception:
        return query


# ── 개별 검색 함수 ───────────────────────────────────────────────────────────────


def _search_vector(query_vector: list, limit: int) -> list[dict]:
    """Atlas Vector Search: 전체 컬렉션에서 의미 유사도 검색."""
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": limit * 5,
                "limit": limit,
            }
        },
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(_get_db()[settings.mongo_collection_name].aggregate(pipeline))


def _tokenize_ko(text: str) -> list[str]:
    """한국어 텍스트를 BM25용 토큰 리스트로 변환합니다."""
    tokens: list[str] = []
    for word in re.findall(r"[가-힣]+", text):
        if len(word) == 1:
            tokens.append(word)
        else:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    tokens.extend(t.lower() for t in re.findall(r"[a-zA-Z0-9]+", text))
    return tokens


def _build_bm25_index() -> None:
    """MongoDB 전체 문서로 BM25 인덱스를 빌드합니다. 최초 1회만 실행됩니다."""
    global _bm25, _bm25_corpus
    db = _get_db()
    docs = list(db[settings.mongo_collection_name].find({}, {"embedding": 0}))
    _bm25_corpus = docs
    corpus = [_tokenize_ko(doc.get("text", "")) for doc in docs]
    _bm25 = BM25Okapi(corpus)


def _search_keyword(query: str, limit: int) -> list[dict]:
    """로컬 BM25 키워드 검색."""
    global _bm25, _bm25_corpus
    if _bm25 is None:
        _build_bm25_index()

    query_tokens = _tokenize_ko(query)
    if not query_tokens:
        return []

    scores = _bm25.get_scores(query_tokens)
    ranked_indices = sorted(
        (i for i in range(len(scores)) if scores[i] > 0),
        key=lambda i: scores[i],
        reverse=True,
    )[:limit]

    results = []
    for idx in ranked_indices:
        doc = dict(_bm25_corpus[idx])
        doc["score"] = float(scores[idx])
        results.append(doc)
    return results


# ── RRF 융합 ─────────────────────────────────────────────────────────────────────


def _parse_chunk_num(chunk_id: str) -> tuple[str, int] | None:
    """청크 ID에서 섹션 prefix와 번호를 분리합니다."""
    m = re.match(r"^([\w]+-[A-Z]{0,2})(\d+)$", chunk_id)
    return (m.group(1), int(m.group(2))) if m else None


def _apply_window_boost(fused: dict, window: int = 3, boost: float = 0.15) -> None:
    """같은 섹션(prefix)의 ±window 이내 청크가 동반되면 rrf_score를 부스팅합니다."""
    prefix_map: dict[str, list[tuple[int, str]]] = {}
    for cid in fused:
        parsed = _parse_chunk_num(cid)
        if parsed:
            prefix, num = parsed
            prefix_map.setdefault(prefix, []).append((num, cid))

    for prefix, items in prefix_map.items():
        if len(items) < 2:
            continue
        for num_i, cid_i in items:
            cluster_count = sum(
                1
                for num_j, _ in items
                if num_j != num_i and abs(num_j - num_i) <= window
            )
            if cluster_count >= 1:
                fused[cid_i]["rrf_score"] += boost * cluster_count


def _fuse_rrf(v_results: list[dict], k_results: list[dict], final_k: int) -> list[dict]:
    """RRF로 벡터 + 키워드 결과를 융합하고 도메인 가중치를 적용합니다."""
    v_score_map = {
        doc.get("chunk_id", f"v_{i}"): doc.get("score", 0.0)
        for i, doc in enumerate(v_results)
    }

    fused: dict[str, dict] = {}

    for rank, doc in enumerate(v_results):
        chunk_id = doc.get("chunk_id", f"v_{rank}")
        fused[chunk_id] = {
            "doc": doc,
            "rrf_score": 1.0 / (rank + 1 + RRF_K),
            "vector_score": doc.get("score", 0.0),
        }

    for rank, doc in enumerate(k_results):
        chunk_id = doc.get("chunk_id", f"k_{rank}")
        rrf = 1.0 / (rank + 1 + RRF_K)
        if chunk_id in fused:
            fused[chunk_id]["rrf_score"] += rrf
        else:
            fused[chunk_id] = {
                "doc": doc,
                "rrf_score": rrf,
                "vector_score": v_score_map.get(chunk_id, 0.0),
            }

    _apply_window_boost(fused)

    ranked = []
    for data in fused.values():
        weight = float(data["doc"].get("weight_score", 1.0))
        ranked.append({**data, "final_score": data["rrf_score"] * weight})

    ranked.sort(key=lambda x: x["final_score"], reverse=True)

    for item in ranked[:final_k]:
        item["doc"]["vector_score"] = item["vector_score"]

    return [item["doc"] for item in ranked[:final_k]]


# ── PDR Lookup ───────────────────────────────────────────────────────────────────


def _classify_source(parent_id: str | None, category: str = "") -> str:
    """parent_id 접두어와 category로 문서 출처를 결정합니다."""
    if parent_id:
        if str(parent_id).startswith("QNA-"):
            return "QNA"
        if str(parent_id).startswith(("FSS-", "KICPA-")):
            return "감리사례"
        if str(parent_id).startswith("EDU-"):
            return "교육자료"
    return category if category else "본문"


def _get_parent_content(parent_id: str, source: str) -> str:
    """PDR 패턴: Child 청크의 parent_id로 부모 원문 전체를 조회합니다."""
    db = _get_db()
    if source == "QNA":
        doc = db[QNA_PARENT_COLL].find_one({"_id": parent_id})
    elif source == "감리사례":
        doc = db[FINDINGS_PARENT_COLL].find_one({"_id": parent_id})
    elif source == "교육자료":
        doc = db[KAI_PARENT_COLL].find_one({"_id": parent_id})
    else:
        return ""
    return doc.get("content", "") if doc else ""


def _docs_from_fused(fused_docs: list[dict]) -> list[dict]:
    """RRF 융합 결과를 RAG 통합 스키마로 변환합니다 (PDR 포함)."""
    results = []
    for doc in fused_docs:
        parent_id = doc.get("parent_id")
        source = _classify_source(parent_id, doc.get("category", ""))
        results.append(
            {
                "source": source,
                "chunk_id": doc.get("chunk_id", ""),
                "parent_id": parent_id,
                "category": doc.get("category", ""),
                "chunk_type": doc.get("chunk_type", ""),
                "content": doc.get("text", ""),
                "full_content": _get_parent_content(parent_id, source)
                if source != "본문"
                else "",
                "title": doc.get("title", ""),
                "case_group_title": doc.get("case_group_title", ""),
                "score": doc.get("score", 0.0),
                "vector_score": doc.get("vector_score", 0.0),
                "related_paragraphs": doc.get("related_paragraphs", []),
                "hierarchy": doc.get("hierarchy", ""),
            }
        )
    return results


# ── 핀포인트 문서 직접 조회 ──────────────────────────────────────────────────


def _expand_paragraph_range(ref: str) -> list[str]:
    """'B77~B79' → ['B77', 'B78', 'B79']. 20개 초과 범위는 무시."""
    stripped = ref.strip()
    # 소수점 범위: "한129.1~5" → 한129.1, 한129.2, ..., 한129.5
    m_dot = re.match(r"^(.+?)(\d+)\.(\d+)\s*[~～\-]\s*(\d+)$", stripped)
    if m_dot:
        prefix, base = m_dot.group(1), m_dot.group(2)
        start, end = int(m_dot.group(3)), int(m_dot.group(4))
        if start <= end and (end - start) <= 20:
            return [f"{prefix}{base}.{n}" for n in range(start, end + 1)]
    m = re.match(
        r"^([A-Za-z\uac00-\ud7a3]*)(\d+)\s*[~～\-]\s*[A-Za-z\uac00-\ud7a3]*(\d+)$",
        stripped,
    )
    if m:
        prefix, start, end = m.group(1), int(m.group(2)), int(m.group(3))
        if start <= end and (end - start) <= 20:
            return [f"{prefix}{n}" for n in range(start, end + 1)]
    return [ref.strip()]


def _parse_doc_ids_from_text(text: str) -> dict[str, list[str]]:
    """decision_tree 텍스트에서 문서 ID를 파싱하여 유형별로 분류합니다.

    Why: precedents/red_flags 텍스트에는 [QNA-SSI-36917], [IE 사례 2, 3] 등의
    참조가 하드코딩되어 있는데, 이를 파싱해서 MongoDB에서 원문을 직접 가져오기 위함.
    """
    ids: dict[str, list[str]] = {
        "qna": [],
        "findings": [],
        "edu": [],
        "ie_cases": [],
        "paragraphs": [],
    }
    seen: set[str] = set()

    # (문단 XX) 패턴에서 기준서 문단 번호 추출
    # "문단 59, 87" 같은 콤마 구분도 처리: 첫 번호 + 후속 콤마 번호까지 캡처
    for m in re.finditer(
        r"문단\s+([A-Z]*\d+(?:[A-Z])?(?:\s*[~～\-]\s*[A-Z]*\d+(?:[A-Z])?)?)"
        r"((?:\s*,\s*[A-Z]*\d+(?:[A-Z])?(?:\s*[~～\-]\s*[A-Z]*\d+(?:[A-Z])?)?)*)",
        text,
    ):
        first_ref = m.group(1)
        rest = m.group(2)  # ", 87, 90" 등
        all_refs = [first_ref]
        if rest:
            all_refs.extend(r.strip() for r in rest.split(",") if r.strip())
        for ref in all_refs:
            for p in _expand_paragraph_range(ref):
                if p not in seen:
                    seen.add(p)
                    ids["paragraphs"].append(p)

    # [XXX] 패턴에서 괄호 내용 추출
    brackets = re.findall(r"\[([^\]]+)\]", text)

    for bracket in brackets:
        # "연계" 접미사 제거
        clean = re.sub(r"\s*연계$", "", bracket).strip()
        if not clean:
            continue

        # BC 문단 참조 (본문 컬렉션 chunk_id: 1115-BC285)
        bc_match = re.match(r"^BC(\d+[A-Z]*)$", clean)
        if bc_match:
            bc_id = f"BC{bc_match.group(1)}"
            if bc_id not in seen:
                seen.add(bc_id)
                ids["paragraphs"].append(bc_id)
            continue

        # IE 사례 패턴을 먼저 처리 (콤마가 사례 번호 구분자일 수 있으므로)
        if clean.startswith("IE 사례"):
            # QNA/FSS 등 명시적 ID를 먼저 추출하여 제거
            named_refs = re.findall(
                r"(QNA-[\w-]+|FSS-CASE-[\w-]+|KICPA-CASE-[\w-]+|EDU-[\w-]+)",
                clean,
            )
            for sub in named_refs:
                _add_ref(sub, ids, seen)

            # named_refs를 제거한 나머지에서 IE 사례 번호만 추출
            ie_only = clean
            for ref in named_refs:
                ie_only = ie_only.replace(ref, "")

            # "IE 사례 20, 21" → 숫자(+알파벳접미사) 추출
            # 5자리 이상 숫자는 QNA/FSS ID 잔재일 수 있으므로 제외
            for num in re.findall(r"(\d+[A-Z]?(?:-[A-Z])?)", ie_only):
                # 순수 숫자가 5자리 이상이면 QNA 번호 잔재 → 스킵
                digits = re.match(r"(\d+)", num).group(1)
                if len(digits) >= 5:
                    continue
                key = f"IE_{num}"
                if key not in seen:
                    seen.add(key)
                    ids["ie_cases"].append(num)
            continue

        # 콤마로 분리된 복수 참조 처리
        parts = [p.strip() for p in clean.split(",")]
        current_prefix = ""
        # 첫 번째 ID에서 접두어 기억 (콤마 뒤 숫자만 올 때 복원용)
        # "QNA-SSI-36991, 36990" → QNA-SSI- 접두어는 복잡해서 스킵
        # "FSS-CASE-2024-2409-01, 2025-2512-01" → FSS-CASE- 복원 가능

        for part in parts:
            part = part.strip()
            part = re.sub(r"\s*연계$", "", part).strip()
            if not part:
                continue

            if part.startswith("QNA-"):
                current_prefix = "QNA-"
                _add_ref(part, ids, seen)
            elif part.startswith("FSS-CASE-"):
                current_prefix = "FSS-CASE-"
                _add_ref(part, ids, seen)
            elif part.startswith("KICPA-CASE-"):
                current_prefix = "KICPA-CASE-"
                _add_ref(part, ids, seen)
            elif part.startswith("EDU-"):
                current_prefix = "EDU-"
                _add_ref(part, ids, seen)
            # 콤마 뒤 접두어 없이 숫자/코드만 (예: "2025-2512-01")
            elif current_prefix and re.match(r"^[\d]", part):
                if current_prefix in ("FSS-CASE-", "KICPA-CASE-"):
                    _add_ref(f"{current_prefix}{part}", ids, seen)
                # QNA 콤마 뒤 숫자 복원은 불가 (SSI/KQA 등 다양한 중간 패턴)

    return ids


def _add_ref(ref_id: str, ids: dict, seen: set) -> None:
    """파싱된 참조 ID를 유형별 리스트에 추가합니다."""
    if ref_id in seen:
        return
    seen.add(ref_id)
    if ref_id.startswith("QNA-"):
        ids["qna"].append(ref_id)
    elif ref_id.startswith(("FSS-CASE-", "KICPA-CASE-")):
        ids["findings"].append(ref_id)
    elif ref_id.startswith("EDU-"):
        ids["edu"].append(ref_id)


def _fetch_ie_case_chunks(case_numbers: list[str]) -> list[dict]:
    """IE 사례 번호 → 본문 컬렉션에서 해당 사례의 청크들을 조회합니다.

    Why: IE 사례는 parent 컬렉션이 없고, chunk_id가 1115-IE3~IE6 식으로 연속됨.
    hierarchy에서 '사례 N:' 패턴으로 필터링.
    """
    if not case_numbers:
        return []

    db = _get_db()
    coll = db[settings.mongo_collection_name]

    # "사례 N" regex OR 조건 생성
    patterns = [re.compile(rf"사례\s*{re.escape(n)}[\s:：]") for n in case_numbers]

    ie_chunks = list(
        coll.find(
            {"chunk_id": {"$regex": "^1115-IE"}},
            {"embedding": 0},
        )
    )

    results = []
    seen_ids: set[str] = set()
    for doc in ie_chunks:
        hierarchy = doc.get("hierarchy", "")
        for pattern in patterns:
            if pattern.search(hierarchy) and doc["chunk_id"] not in seen_ids:
                seen_ids.add(doc["chunk_id"])
                results.append(doc)
                break

    return results


def fetch_pinpoint_docs(matched_topics: list[dict]) -> list[dict]:
    """matched_topics의 precedents/red_flags에서 문서 ID를 파싱하여 원문을 직접 조회합니다.

    Why: 리트리버(벡터 유사도)가 놓치는 큐레이션 선례·감리사례 원문을 정확히 가져오기 위함.
    핀포인트 fetch 결과는 리트리버보다 1순위로 relevant_docs에 배치됨.
    """
    if not matched_topics:
        return []

    # 1) 모든 matched_topics에서 문서 ID 수집
    all_text_parts: list[str] = []
    for topic in matched_topics:
        # precedents: {branch_label: [case_strings]}
        for cases in topic.get("precedents", {}).values():
            all_text_parts.extend(cases)
        # red_flags: {warning_prefix, check_items_by_branch: {branch: [items]}}
        rf = topic.get("red_flags", {})
        for items in rf.get("check_items_by_branch", {}).values():
            all_text_parts.extend(items)
        # checklist_text: 체크리스트에 포함된 문단 참조도 파싱 대상
        ct = topic.get("checklist_text", "")
        if ct:
            all_text_parts.append(ct)

    combined_text = "\n".join(all_text_parts)
    parsed = _parse_doc_ids_from_text(combined_text)

    db = _get_db()
    results: list[dict] = []
    seen_parent_ids: set[str] = set()

    # 2) QNA 원문 fetch
    if parsed["qna"]:
        qna_coll = db[QNA_PARENT_COLL]
        for qna_id in parsed["qna"]:
            if qna_id in seen_parent_ids:
                continue
            doc = qna_coll.find_one({"_id": qna_id})
            if doc:
                seen_parent_ids.add(qna_id)
                results.append(
                    {
                        "source": "QNA",
                        "chunk_id": f"{qna_id}_pinpoint",
                        "parent_id": qna_id,
                        "category": "질의회신",
                        "chunk_type": "pinpoint",
                        "content": doc.get("content", "")[:500],
                        "full_content": doc.get("content", ""),
                        "title": doc.get("metadata", {}).get("title", ""),
                        "case_group_title": "",
                        "score": 1.0,
                        "vector_score": 0.0,
                        "related_paragraphs": [],
                        "hierarchy": f"질의회신 > {qna_id}",
                    }
                )

    # 3) 감리사례 (FSS/KICPA) 원문 fetch
    if parsed["findings"]:
        findings_coll = db[FINDINGS_PARENT_COLL]
        for fid in parsed["findings"]:
            if fid in seen_parent_ids:
                continue
            doc = findings_coll.find_one({"_id": fid})
            if doc:
                seen_parent_ids.add(fid)
                results.append(
                    {
                        "source": "감리사례",
                        "chunk_id": f"{fid}_pinpoint",
                        "parent_id": fid,
                        "category": "감리사례",
                        "chunk_type": "pinpoint",
                        "content": doc.get("content", "")[:500],
                        "full_content": doc.get("content", ""),
                        "title": doc.get("metadata", {}).get("title", ""),
                        "case_group_title": "",
                        "score": 1.0,
                        "vector_score": 0.0,
                        "related_paragraphs": [],
                        "hierarchy": f"감리사례 > {fid}",
                    }
                )

    # 4) 교육자료 (EDU) 원문 fetch
    if parsed["edu"]:
        kai_coll = db[KAI_PARENT_COLL]
        for eid in parsed["edu"]:
            if eid in seen_parent_ids:
                continue
            doc = kai_coll.find_one({"_id": eid})
            if doc:
                seen_parent_ids.add(eid)
                results.append(
                    {
                        "source": "교육자료",
                        "chunk_id": f"{eid}_pinpoint",
                        "parent_id": eid,
                        "category": "교육자료",
                        "chunk_type": "pinpoint",
                        "content": doc.get("content", "")[:500],
                        "full_content": doc.get("content", ""),
                        "title": doc.get("metadata", {}).get("title", ""),
                        "case_group_title": "",
                        "score": 1.0,
                        "vector_score": 0.0,
                        "related_paragraphs": [],
                        "hierarchy": f"교육자료 > {eid}",
                    }
                )

    # 5) IE 사례 → 본문 청크에서 조회 후 RAG 스키마로 변환
    if parsed["ie_cases"]:
        ie_chunks = _fetch_ie_case_chunks(parsed["ie_cases"])
        for doc in ie_chunks:
            chunk_id = doc.get("chunk_id", "")
            if chunk_id in seen_parent_ids:
                continue
            seen_parent_ids.add(chunk_id)
            results.append(
                {
                    "source": "본문",
                    "chunk_id": chunk_id,
                    "parent_id": doc.get("parent_id"),
                    "category": doc.get("category", ""),
                    "chunk_type": "pinpoint",
                    "content": doc.get("text", ""),
                    "full_content": "",
                    "title": doc.get("title", ""),
                    "case_group_title": doc.get("case_group_title", ""),
                    "score": 1.0,
                    "vector_score": 0.0,
                    "related_paragraphs": doc.get("related_paragraphs", []),
                    "hierarchy": doc.get("hierarchy", ""),
                }
            )

    # 6) 기준서 본문 문단 — MongoDB chunk_id "1115-{para}" 패턴으로 직접 조회
    if parsed["paragraphs"]:
        coll = db[settings.mongo_collection_name]
        chunk_ids = [f"1115-{p}" for p in parsed["paragraphs"]]
        para_chunks = list(
            coll.find(
                {"chunk_id": {"$in": chunk_ids}},
                {"embedding": 0},
            )
        )
        for doc in para_chunks:
            cid = doc.get("chunk_id", "")
            if cid in seen_parent_ids:
                continue
            seen_parent_ids.add(cid)
            results.append(
                {
                    "source": "본문",
                    "chunk_id": cid,
                    "parent_id": doc.get("parent_id"),
                    "category": doc.get("category", ""),
                    "chunk_type": "pinpoint",
                    "content": doc.get("text", ""),
                    "full_content": "",
                    "title": doc.get("title", ""),
                    "case_group_title": doc.get("case_group_title", ""),
                    "score": 1.0,
                    "vector_score": 0.0,
                    "related_paragraphs": doc.get("related_paragraphs", []),
                    "hierarchy": doc.get("hierarchy", ""),
                }
            )

    return results


# ── 메인 검색 함수 ───────────────────────────────────────────────────────────────


def search_all(query: str, limit: int = 5) -> list[dict]:
    """기본 하이브리드 검색 (Vector + BM25 + RRF) + QNA/감리사례 보조 추출."""
    query_vector = embed_query_sync(query)
    v_results = _search_vector(query_vector, VECTOR_TOP_K)
    k_results = _search_keyword(query, VECTOR_TOP_K // 2)
    fused_docs = _fuse_rrf(v_results, k_results, final_k=limit)
    base_docs = _docs_from_fused(fused_docs)

    existing_ids = {d["chunk_id"] for d in base_docs}

    qna_raw = [
        d
        for d in v_results
        if str(d.get("parent_id", "")).startswith("QNA-")
        and d.get("chunk_id") not in existing_ids
    ][:QNA_SUPPLEMENT]

    findings_raw = [
        d
        for d in v_results
        if str(d.get("parent_id", "")).startswith(("FSS-", "KICPA-"))
        and d.get("chunk_id") not in existing_ids
    ][:FINDINGS_SUPPLEMENT]

    # 교육자료 보조 추출 — AI 답변 컨텍스트용
    kai_raw = [
        d
        for d in v_results
        if str(d.get("parent_id", "")).startswith("EDU-")
        and d.get("chunk_id") not in existing_ids
    ][:KAI_SUPPLEMENT]

    supplement = _docs_from_fused(qna_raw + findings_raw + kai_raw)
    return base_docs + supplement


def search_all_hyde(query: str, limit: int = 5) -> list[dict]:
    """HyDE 폴백 검색: 가상 K-IFRS 조항 텍스트로 벡터 검색."""
    hypothetical_doc = _generate_hypothetical_doc(query)
    hyde_vector = embed_query_sync(hypothetical_doc)

    v_results = _search_vector(hyde_vector, VECTOR_TOP_K)
    k_results = _search_keyword(query, VECTOR_TOP_K)
    fused_docs = _fuse_rrf(v_results, k_results, final_k=limit)
    return _docs_from_fused(fused_docs)


if __name__ == "__main__":
    query = "밀어내기 매출 수익인식 어떻게 해?"
    results = search_all(query, limit=5)
    for r in results:
        print(f"[{r['source']}] 점수: {r['score']:.4f} | 계층: {r['hierarchy']}")
