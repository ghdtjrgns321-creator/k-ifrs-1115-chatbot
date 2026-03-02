# app/nodes/format.py
import re
from app.state import RAGState
from app.retriever import _get_db, FINDINGS_PARENT_COLL

# LLM 답변에서 문단 번호를 추출하는 정규식
# 매칭 예: (문단 31), (문단 B34), (문단 56~58), 문단 IE15
# 캡처 그룹: "31", "B34", "56", "IE15" 등
_PARAGRAPH_RE = re.compile(r"문단\s*([A-Z]*\d+)")


def format_response(state: RAGState):
    """LLM의 답변을 마크다운으로 포맷팅하고, [상황 B] 섀도우 매칭 넛지를 추가"""

    answer = state.get("answer", "")
    cited_sources = state.get("cited_sources", [])

    # 1. 섀도우 매칭용 문단 번호 수집 (두 가지 소스에서 합산)
    paragraphs = set()

    # 소스 A: cited_sources의 related_paragraphs (감리사례 데이터에 100% 존재)
    for src in cited_sources:
        for p in src.get("related_paragraphs", []):
            paragraphs.add(str(p))

    # 소스 B: LLM 답변 텍스트에서 정규식으로 문단 번호 추출
    # generate_answer 프롬프트가 "(문단 31)" 형식의 출처를 강제하므로
    # 어떤 소스(본문, QNA)의 답변이든 문단 번호가 텍스트에 포함됩니다.
    for match in _PARAGRAPH_RE.finditer(answer):
        paragraphs.add(match.group(1))

    # 2. 섀도우 매칭 (감리사례 DB 검색 - 상황 B)
    nudge_text = ""
    if paragraphs:
        db = _get_db()
        coll = db[FINDINGS_PARENT_COLL]

        # 배열 안의 문단 번호 중 하나라도 일치하는 지적사례 찾기
        # 부모 컬렉션에서 related_paragraphs는 metadata 하위에 저장됨
        matched_case = coll.find_one(
            {"metadata.related_paragraphs": {"$in": list(paragraphs)}}
        )

        if matched_case:
            # hierarchy에서 마지막 '>' 뒤의 사례 제목을 추출
            hierarchy = matched_case.get("metadata", {}).get("hierarchy", "")
            case_title = hierarchy.split(">")[-1].strip() if hierarchy else "관련 감리지적사례"
            p_str = ", ".join(sorted(paragraphs))
            nudge_text = (
                f"\n\n💡 **덧붙임:** 방금 안내해 드린 문단({p_str})과 관련하여, "
                f"금융감독원이 지적한 **[{case_title}]**가 DB에 존재합니다. "
                f"클릭하여 확인해보세요."
            )

    # 3. 출처 목록 포맷팅
    source_lines = ["\n\n📌 **참고 근거**"]
    for src in cited_sources:
        source_type = src.get("source", "알 수 없음")
        hierarchy = src.get("hierarchy", "출처 정보 없음")
        source_lines.append(f"• [{source_type}] {hierarchy}")

    # 4. 최종 텍스트 조립 (답변 + 넛지 + 출처 + 유의사항)
    final_text = answer + nudge_text + "\n" + "\n".join(source_lines)
    final_text += "\n\n⚠️ **유의사항:** 이 답변은 기준서 본문 기준이며, 구체적 사안은 전문가 상담이 필요합니다."

    return {"answer": final_text}
