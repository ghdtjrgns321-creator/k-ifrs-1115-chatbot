"""통합 매칭 로직: MASTER_DECISION_TREES에서 키워드 매칭

analyze 노드가 추출한 standalone_query + search_keywords를
trigger_keywords와 양방향 부분 문자열 매칭하여
is_situation=True일 때 CLARIFY_PROMPT에 주입할 체크리스트 텍스트를 생성합니다.
"""

from app.domain.decision_trees import MASTER_DECISION_TREES


def match_topics(standalone_query: str, search_keywords: list[str]) -> list[dict]:
    """MASTER_DECISION_TREES에서 키워드 매칭 → score 내림차순 상위 3개 반환.

    Returns:
        [{topic_name, checklist_text, checklist, judgment_goal,
          precedents, calculation_formula, score}, ...]
        매칭 없으면 빈 리스트.
    """
    candidates: list[dict] = []

    for topic_name, data in MASTER_DECISION_TREES.items():
        routing = data["1_routing"]
        score = _calc_score(standalone_query, search_keywords, routing["trigger_keywords"])
        if score > 0:
            candidates.append({
                "topic_name": topic_name,
                "checklist_text": _format_checklist(topic_name, data),
                "checklist": data["2_checklist"],
                "judgment_goal": routing["judgment_goal"],
                "precedents": data.get("4_precedents", {}),
                "red_flags": data.get("5_red_flags", {}),
                "calculation_formula": data.get("6_calculation_formula"),
                "score": score,
            })

    # score 내림차순 → 상위 3개 (멀티토픽: 3개 이상 쟁점 지원)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]


# ── 매칭 점수 계산 ──────────────────────────────────────────────

def _calc_score(query: str, keywords: list[str], triggers: list[str]) -> float:
    """양방향 부분 문자열 매칭으로 점수를 산출합니다.

    - search_keywords 매칭: 가중치 2.0 (LLM이 추출한 핵심 용어이므로 신뢰도 높음)
    - standalone_query 매칭: 가중치 1.0 (전체 문장에서 부분 매칭)
    - 완전 일치: 추가 보너스 1.0 (부분 매칭보다 정확도 높음)
    - 1자 키워드/트리거: false positive 방지를 위해 스킵
    """
    score = 0.0
    query_lower = query.lower()

    for trigger in triggers:
        trigger_lower = trigger.lower()
        if len(trigger_lower) < 2:
            continue

        for kw in keywords:
            kw_lower = kw.lower()
            if len(kw_lower) < 2:
                continue
            if kw_lower in trigger_lower or trigger_lower in kw_lower:
                score += 2.0
                if kw_lower == trigger_lower:
                    score += 1.0
                break

        if trigger_lower in query_lower:
            score += 1.0

    return score


# ── 통합 포맷팅 ──────────────────────────────────────────────────

def _format_checklist(topic_name: str, data: dict) -> str:
    """MASTER_DECISION_TREES 항목을 통합 체크리스트 텍스트로 포맷합니다.

    포함: 2_checklist + 3_conclusion_guide + 5_red_flags
    미포함: 4_precedents, 6_calculation_formula (Phase 4에서 generate.py context 주입)
    """
    routing = data["1_routing"]
    lines = [f"[판단 체크리스트: {topic_name}]"]
    lines.append(f"목표: {routing['judgment_goal']}")

    for i, item in enumerate(data["2_checklist"], 1):
        lines.append(f"  {i}. {item}")

    # 결론 가이드
    if data.get("3_conclusion_guide"):
        lines.append("")
        lines.append("[결론 가이드]")
        for guide in data["3_conclusion_guide"]:
            lines.append(f"  {guide}")

    # Red Flags
    red_flags = data.get("5_red_flags")
    if red_flags:
        lines.append("")
        lines.append(red_flags["warning_prefix"])
        for branch_label, questions in red_flags.get("check_items_by_branch", {}).items():
            lines.append(f"  {branch_label}:")
            for q in questions:
                lines.append(f"    {q}")

    return "\n".join(lines)
