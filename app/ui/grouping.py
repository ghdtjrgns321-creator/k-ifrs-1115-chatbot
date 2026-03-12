# app/ui/grouping.py
# 본문/적용지침B/결론도출근거 문서를 소제목 > 소소제목 2단계로 그룹핑.
#
# 디자인:
#   변동대가                          ← 소제목 (볼드 텍스트)
#     ▸ 변동대가 추정치를 제약함 (3건)  ← 소소제목 (접을 수 있는 expander)
#       📄 문단 56 - 제목              ← 문서 카드 (flat)
#   📂 다른 주제 더보기                ← 나머지

import re

import streamlit as st

from app.domain.topic_content_map import (
    PARA_SECTION_INDEX,
    get_desc_for_para,
    get_section_for_para,
)
from app.ui.components import _get_doc_para_num, _render_document_expander
from app.ui.text import _esc


def _para_sort_key(doc: dict) -> tuple[str, int, str]:
    """B59 → ("B", 59, ""), B59A → ("B", 59, "A")."""
    para = _get_doc_para_num(doc)
    m = re.match(r"([A-Za-z]*)(\d+)([A-Za-z]*)", para)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return ("ZZ", 999999, "")


def _extract_topic_key(doc: dict) -> tuple[str, str]:
    """hierarchy에서 (소제목, 소소제목) 추출."""
    hierarchy = doc.get("hierarchy", "")
    source = doc.get("source") or doc.get("category", "")
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]

    if "결론도출근거" in source:
        if len(parts) >= 4:
            return (parts[3], parts[4] if len(parts) >= 5 else "")
        elif len(parts) >= 3:
            return (parts[2], "")
        return ("", "")

    if source == "적용지침B":
        if len(parts) < 2:
            return ("", "")
        return (parts[1], parts[2] if len(parts) >= 3 else "")

    if len(parts) < 3:
        return ("", parts[1] if len(parts) >= 2 else "")
    return (parts[2], parts[3] if len(parts) >= 4 else "")


def _get_parent_category(doc: dict) -> str:
    """hierarchy에서 대분류 추출."""
    hierarchy = doc.get("hierarchy", "")
    source = doc.get("source") or doc.get("category", "")
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]
    if source == "본문" and len(parts) >= 2:
        return parts[1]
    if "결론도출근거" in source and len(parts) >= 3:
        return parts[2]
    return ""


def _clean_title(title: str) -> str:
    """소제목에서 "(문단 XX~YY)" 등 문단 번호 범위를 제거합니다."""
    return re.sub(r"\s*[\(（]문단\s*[A-Za-z0-9~～\-,\s]+[\)）]\s*", "", title).strip()


# ── 렌더링 ────────────────────────────────────────────────────────────────────


def _find_group_desc(docs_or_items) -> str:
    """문서 그룹에서 대표 desc를 찾습니다.

    items가 (idx, doc) 또는 (minor, idx, doc) 형태 모두 지원.
    첫 번째로 매칭되는 desc를 반환합니다.
    """
    for item in docs_or_items:
        doc = item[-1] if isinstance(item, tuple) else item
        para = _get_doc_para_num(doc)
        if para:
            desc = get_desc_for_para(para)
            if desc:
                return desc
    return ""


def _desc_blockquote(desc: str) -> None:
    """큐레이션 desc를 연한 회색 블록으로 렌더링합니다."""
    if not desc:
        return
    import html as _html
    # 마크다운 볼드 → HTML strong
    _d = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _html.escape(desc))
    # 한국어 문장 종결 뒤 줄바꿈
    _d = re.sub(r"(?<=[가-힣])\.\s+", ".<br>", _d)
    _d = _d.replace("\n", "<br>")
    st.markdown(
        f'<div style="line-height:1.75; color:#475569; font-size:0.88em; '
        f'padding:0.5rem 0.75rem; background:#f8fafc; '
        f'border-left:2px solid #cbd5e1; border-radius:2px;">'
        f'{_d}</div>',
        unsafe_allow_html=True,
    )


def _hierarchy_minor_fallback(doc: dict) -> str:
    """topics.json에 없는 문단의 fallback 그룹명을 hierarchy에서 추출합니다.

    hierarchy: "본문 > 인식 > 수행의무의 이행" → "수행의무의 이행"
    """
    hierarchy = doc.get("hierarchy", "")
    source = doc.get("source") or doc.get("category", "")
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]
    # 본문: parts[2]가 소제목 (이미 major로 사용됨) → 그 자체를 fallback
    if source == "본문" and len(parts) >= 3:
        return parts[2]
    if source == "적용지침B" and len(parts) >= 2:
        return parts[1]
    return ""


def _regroup_by_section(
    ungrouped: list[tuple[int, dict]],
) -> tuple[dict[str, list[tuple[int, dict]]], list[tuple[int, dict]]]:
    """topics.json 섹션 정보로 낱개 문단을 재그룹핑합니다.

    topics.json에 없는 문단은 hierarchy에서 부모 섹션명을 fallback으로 사용.
    Returns: (section_groups, truly_ungrouped)
    """
    section_groups: dict[str, list[tuple[int, dict]]] = {}
    truly_ungrouped: list[tuple[int, dict]] = []

    for idx, doc in ungrouped:
        para = _get_doc_para_num(doc)
        sec_title, _ = get_section_for_para(para) if para else ("", "")
        if not sec_title:
            # fallback: hierarchy에서 소제목 사용
            sec_title = _hierarchy_minor_fallback(doc)
        if sec_title:
            section_groups.setdefault(sec_title, []).append((idx, doc))
        else:
            truly_ungrouped.append((idx, doc))

    return section_groups, truly_ungrouped


def _get_section_paras(sec_title: str) -> list[str]:
    """섹션 제목으로 topics.json에 등록된 모든 문단 번호를 수집합니다."""
    from app.domain.topic_content_map import _expand_range, TOPIC_CONTENT_MAP
    for topic in TOPIC_CONTENT_MAP.values():
        for sec in topic.get("main_and_bc", {}).get("sections", []):
            if sec.get("title") == sec_title:
                result = []
                for p in sec.get("paras", []) + sec.get("bc_paras", []):
                    result.extend(_expand_range(p))
                return result
    return []


def _fill_missing_docs(
    sec_title: str, items: list[tuple[int, dict]]
) -> list[tuple[int, dict]]:
    """섹션에 등록된 문단 중 items에 없는 것을 DB에서 보충합니다."""
    from app.ui.db import fetch_docs_by_para_ids

    all_paras = _get_section_paras(sec_title)
    if not all_paras:
        return items

    existing = {_get_doc_para_num(doc) for _, doc in items}
    missing = [p for p in all_paras if p not in existing]
    if not missing:
        return items

    fetched = fetch_docs_by_para_ids(tuple(missing))
    new_items = list(items)
    for doc in fetched:
        pn = doc.get("paraNum", "")
        if pn and pn not in existing:
            existing.add(pn)
            new_items.append((900 + len(new_items), {
                "source": doc.get("category", ""),
                "hierarchy": doc.get("hierarchy", ""),
                "title": doc.get("title", ""),
                "content": doc.get("content", "") or doc.get("text", ""),
                "full_content": doc.get("content", "") or doc.get("text", ""),
                "chunk_id": doc.get("chunk_id", ""),
                "paraNum": pn,
                "metadata": doc.get("metadata") or {},
                "score": 0.0,
            }))

    # 문단번호 순 정렬
    return sorted(new_items, key=lambda x: _para_sort_key(x[1]))


def _build_para_label(items: list[tuple[int, dict]]) -> str:
    """items의 문단번호를 [문단 9, 문단 15] 형태로 생성합니다."""
    paras = []
    for _, doc in items:
        p = _get_doc_para_num(doc)
        if p and p not in paras:
            paras.append(p)
    if not paras:
        return ""
    return "[" + ", ".join(f"문단 {p}" for p in paras) + "]"


def _render_section_expander(
    sec_title: str, items: list[tuple[int, dict]]
) -> None:
    """섹션별 expander + desc blockquote + 누락 문단 보충 렌더링."""
    # topics.json에 등록된 문단 중 빠진 것 보충
    items = _fill_missing_docs(sec_title, items)

    title = _clean_title(sec_title)
    para_label = _build_para_label(items)
    label = f"{title} {para_label}" if para_label else title

    with st.expander(_esc(label), expanded=False):
        _desc_blockquote(_find_group_desc(items))
        for idx, doc in items:
            _render_document_expander(doc, doc_index=idx)


def _render_sub_grouped(
    items: list[tuple[str, int, dict]],
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """소소제목별 expander + retrieved 문서만 렌더링."""
    sub_groups: dict[str, list[tuple[int, dict]]] = {}
    sub_ungrouped: list[tuple[int, dict]] = []

    for minor, idx, doc in items:
        if minor:
            sub_groups.setdefault(minor, []).append((idx, doc))
        else:
            sub_ungrouped.append((idx, doc))

    # 낱개 문단을 topics.json 섹션으로 재그룹핑
    if sub_ungrouped:
        sec_groups, truly_ungrouped = _regroup_by_section(sub_ungrouped)
        # 재그룹된 섹션은 sub_groups에 병합
        for sec_title, sec_items in sec_groups.items():
            sub_groups.setdefault(sec_title, []).extend(sec_items)
        sub_ungrouped = truly_ungrouped

    # 소소제목이 없으면 flat 표시
    if not sub_groups:
        for idx, doc in sub_ungrouped:
            _render_document_expander(doc, doc_index=idx)
        return

    # 진짜 미분류 문서 flat 표시
    for idx, doc in sub_ungrouped:
        _render_document_expander(doc, doc_index=idx)

    # 소소제목 → expander (2번째 계층)
    for minor_title, minor_items in sorted(
        sub_groups.items(),
        key=lambda kv: _para_sort_key(kv[1][0][1]),
    ):
        _render_section_expander(minor_title, minor_items)


def _render_major_section(
    major_title: str,
    items: list[tuple[str, int, dict]],
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """소제목 헤더 + 소소제목 렌더링."""
    title = _clean_title(major_title)
    st.markdown(f"📌 **{_esc(title)}**")
    _render_sub_grouped(items, allowed_sources=allowed_sources)


# ── 진입점 ────────────────────────────────────────────────────────────────────


def _render_topic_grouped_docs(
    docs: list[dict],
    idx_offset: int = 0,
    score_ordered: list[dict] | None = None,
    search_query: str = "",
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """소제목 > 소소제목 2단계 그룹핑 렌더링."""
    grouped: dict[str, list[tuple[str, int, dict]]] = {}
    ungrouped: list[tuple[int, dict]] = []

    for i, doc in enumerate(docs):
        major, minor = _extract_topic_key(doc)
        if major:
            grouped.setdefault(major, []).append((minor, idx_offset + i, doc))
        else:
            ungrouped.append((idx_offset + i, doc))

    if not grouped:
        for idx, doc in ungrouped:
            _render_document_expander(doc, doc_index=idx)
        return

    # score 1위 소제목 → 메인
    group_score_sum: dict[str, float] = {}
    if score_ordered:
        for doc in score_ordered:
            candidate, _ = _extract_topic_key(doc)
            if candidate and candidate in grouped:
                group_score_sum[candidate] = (
                    group_score_sum.get(candidate, 0.0) + doc.get("score", 0.0)
                )
        if search_query and group_score_sum:
            kws = [
                w for w in re.sub(r"[^\w]", " ", search_query).split() if len(w) >= 2
            ]
            for gname in group_score_sum:
                match_cnt = sum(1 for kw in kws if kw in gname)
                if match_cnt:
                    group_score_sum[gname] += match_cnt * 100.0

    top_major = (
        max(group_score_sum, key=lambda k: group_score_sum[k])
        if group_score_sum
        else max(grouped.keys(), key=lambda k: len(grouped[k]))
    )
    top_items = grouped.pop(top_major)
    top_score = group_score_sum.get(top_major, 1.0) or 1.0

    # 같은 대분류 관련 소제목 통합
    top_category = ""
    for _, _, doc in top_items:
        top_category = _get_parent_category(doc)
        if top_category:
            break

    if top_category:
        for m, s in list(group_score_sum.items()):
            if m not in grouped or s < top_score * 0.30:
                continue
            m_cat = ""
            for _, _, doc in grouped[m]:
                m_cat = _get_parent_category(doc)
                if m_cat:
                    break
            if m_cat == top_category:
                for minor, idx, doc in grouped.pop(m):
                    top_items.append((minor if minor else m, idx, doc))

    # 메인 렌더링
    _render_major_section(top_major, top_items, allowed_sources=allowed_sources)

    # 나머지 토픽도 전부 flat 표시 (더보기 접기 없음)
    for major_title, items in sorted(
        grouped.items(),
        key=lambda kv: _para_sort_key(kv[1][0][2]),
    ):
        _render_major_section(major_title, items, allowed_sources=allowed_sources)

    if ungrouped:
        st.markdown("📖 **한국회계기준원 교육자료**")
        for idx, doc in ungrouped:
            _render_document_expander(doc, doc_index=idx)
