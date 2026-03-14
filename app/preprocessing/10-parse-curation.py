"""
topic-curation.txt → topics.json 변환 스크립트.

큐레이션 텍스트 파일을 파싱하여 topic_content_map.py에서 사용할
구조화된 JSON을 생성합니다.

사용법:
    PYTHONPATH=. uv run python app/preprocessing/10-parse-curation.py
"""

import json
import re
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────────────────────────────
INPUT_FILE = Path("data/topic-curation/topic-curation.txt")
OUTPUT_FILE = Path("data/topic-curation/topics.json")

# ── 큐레이션 헤더 → topic_content_map 키 매핑 ─────────────────────────────────
# 큐레이션 텍스트의 ## 헤더가 KEYWORD_TO_TOPIC 키와 다를 때 변환
HEADER_TO_KEY: dict[str, str] = {
    "계약식별": "계약의 식별",
    "수행의무 식별의 원칙": "수행의무 식별",
    "거래가격 배분 원칙": "거래가격 배분",
    "본인 vs 대리인(총액(매출) 인식 vs 순액(수수료) 인식)": "본인 vs 대리인",
    "라이선싱(접근권(기간) vs 사용권(시점), 판매/사용 기준 로열티 예외)": "라이선싱",
    "반품권이 있는 판매(환불부채와 반환제품회수권 인식)": "반품권이 있는 판매",
    "보증(확신 유형(충당부채) vs 용역 유형(별도 수행의무)": "보증",
    "통제 이전의 특수 형태(재매입약정 / 위탁약정 / 미인도청구약정 / 고객의 인수)": "통제 이전의 특수 형태",
    "고객의 권리 관련(고객 선택권 / 고객이 행사하지 아니한 권리 / 환불되지 않는 선수수수료)": "고객의 권리 관련",
    "표시(계약자산, 계약부채, 수취채권)": "표시",
}


# ── 정규식 패턴 ────────────────────────────────────────────────────────────────

# 문단 번호 패턴: "9", "B34", "BC77", "IE7", "B34A", "한129.1"
RE_PARA_NUM = re.compile(
    r"(?:한\d+\.\d+|[A-Z]*\d+[A-Z]?)"
)

# 괄호 안 문단 범위 추출: "(문단 9~16)" "(문단 B34~B38)" "(문단 22~30, 한129.1~한129.5)"
RE_PARA_RANGE = re.compile(
    r"\(문단\s+([\w\d~～,\s.]+)\)"
)

# BC 괄호 범위: "(BC31~BC57, BC69~BC70)" "(BC76~BC83)"
RE_BC_RANGE = re.compile(
    r"\((BC[\w~～,\sOA-Z]+)\)"
)

# QNA ID: "QNA-SSI-38674", "QNA-2021-I-KQA008", "QNA-201909A", "QNA-202504C"
RE_QNA_ID = re.compile(
    r"(QNA-[A-Za-z0-9\-]+)"
)

# 감리사례 ID: "FSS-CASE-2022-2311-02", "KICPA-CASE-2024-04"
RE_FINDING_ID = re.compile(
    r"((?:FSS|KICPA)-CASE-[\d\-]+)"
)

# 적용사례 패턴: "사례 1 (회수 가능성 미충족, IE2~IE6):" or "사례 45 (대리인, IE231~IE233):"
RE_IE_CASE = re.compile(
    r"사례\s+(\d+[A-Za-z]?)\s*\(([^)]+)\)\s*:"
)

# IE 범위 추출: "IE2~IE6" from case description
RE_IE_RANGE = re.compile(
    r"(IE\d+[~～]IE\d+)"
)


def expand_range(raw: str) -> list[str]:
    """'9~16' → ['9','10',...,'16'],  'BC31~BC57' → ['BC31',...,'BC57'].

    범위가 아닌 단일 값이면 [raw]을 반환.
    20개 초과는 양 끝점만 반환.
    """
    raw = raw.strip()
    m = re.match(r"^([A-Za-z]*?)(\d+)[~～]([A-Za-z]*?)(\d+)$", raw)
    if not m:
        # 한129.1~한129.5 같은 특수 패턴
        m2 = re.match(r"^(한\d+\.)(\d+)[~～]\1(\d+)$", raw)
        if m2:
            prefix = m2.group(1)
            start, end = int(m2.group(2)), int(m2.group(3))
            if end - start > 20:
                return [f"{prefix}{start}"]
            return [f"{prefix}{n}" for n in range(start, end + 1)]
        return [raw]

    prefix1, start_n, prefix2, end_n = (
        m.group(1), int(m.group(2)), m.group(3), int(m.group(4)),
    )
    prefix = prefix1 or prefix2
    if start_n > end_n or (end_n - start_n) > 20:
        return [f"{prefix}{start_n}", f"{prefix}{end_n}"]
    return [f"{prefix}{n}" for n in range(start_n, end_n + 1)]


def _strip_sub_para(s: str) -> str:
    """하위 문단 표시 제거: '84⑵' → '84', '89(2)' → '89'.

    원 괄호 숫자(⑴~⑼, U+2474~U+247C)와 일반 괄호 하위번호를 제거합니다.
    DB는 하위 문단을 별도 문서로 저장하지 않으므로 기본 문단으로 조회해야 합니다.
    """
    # 원 괄호 숫자: ⑴⑵⑶⑷⑸⑹⑺⑻⑼ (U+2474~U+247C)
    s = re.sub(r"[\u2474-\u247C]", "", s)
    # 일반 괄호 하위번호: (1), (2), ...
    s = re.sub(r"\(\d+\)$", "", s)
    return s.strip()


def parse_para_list(text: str) -> list[str]:
    """문단 범위 텍스트에서 개별 문단 번호 리스트를 추출.

    입력 예: "9~16, B20~B27" → ["9", "10", ..., "16", "B20", ..., "B27"]
    """
    result: list[str] = []
    # 쉼표로 분리
    for part in re.split(r"[,，]", text):
        part = _strip_sub_para(part.strip())
        if not part:
            continue
        # 범위인지 확인
        if "~" in part or "～" in part:
            result.extend(expand_range(part))
        else:
            # 단일 값
            if re.match(r"^[A-Za-z]*\d+[A-Za-z]?$", part) or part.startswith("한"):
                result.append(part)
    return result


def extract_paras_from_header(header_text: str) -> list[str]:
    """섹션 헤더의 "(문단 X~Y)" 부분에서 문단 번호 추출."""
    m = RE_PARA_RANGE.search(header_text)
    if not m:
        return []
    return parse_para_list(m.group(1))


def extract_bc_from_header(header_text: str) -> list[str]:
    """섹션 헤더의 "(BCxx~BCyy)" 부분에서 BC 문단 번호 추출."""
    m = RE_BC_RANGE.search(header_text)
    if not m:
        return []
    return parse_para_list(m.group(1))


def split_into_numbered_sections(text: str) -> dict[int, str]:
    """텍스트를 번호 섹션(1~6)으로 분리.

    패턴: "\n1. [본문]", "\n2. [부록", "\n3. [결론", "\n4. [적용", "\n5. [질의", "\n6. [감리"
    """
    # 각 섹션 시작 위치 찾기
    section_starts: list[tuple[int, int]] = []  # (section_num, char_pos)

    for m in re.finditer(r"\n(\d)\.\s+\[", text):
        sec_num = int(m.group(1))
        if 1 <= sec_num <= 6:
            section_starts.append((sec_num, m.start()))

    if not section_starts:
        return {}

    sections: dict[int, str] = {}
    for i, (sec_num, start) in enumerate(section_starts):
        end = section_starts[i + 1][1] if i + 1 < len(section_starts) else len(text)
        sections[sec_num] = text[start:end].strip()

    return sections


def parse_main_sections(sec1_text: str) -> tuple[str, list[dict]]:
    """섹션 1 (본문)에서 summary와 sections 추출.

    본문 텍스트에서 "소제목 (문단 X, Y): 설명" 패턴을 파싱하여
    개별 section 엔트리를 생성합니다.
    """
    lines = sec1_text.split("\n")

    # 첫 번째 줄은 "1. [본문] 기준서 핵심 요약 (문단 X~Y)" 헤더
    header_line = lines[0] if lines else ""
    header_paras = extract_paras_from_header(header_line)

    # 헤더 다음 첫 줄이 summary
    summary = ""
    content_start = 1
    for i, line in enumerate(lines[1:], 1):
        stripped = line.strip()
        if stripped and not stripped.startswith("•") and not stripped.startswith("-"):
            summary = stripped.rstrip(".") + "."
            content_start = i + 1
            break

    # 나머지 텍스트에서 소제목 패턴 찾기
    # 패턴: "소제목 (문단 X, Y):" 또는 "소제목 (문단 X~Y):"
    remaining_text = "\n".join(lines[content_start:])

    # 소제목 패턴으로 분리
    # "제목 (문단 XX, YY):" or "제목 (문단 XX~YY):" or 번호있는 "1. 별도 계약으로 (문단 20):"
    sub_pattern = re.compile(
        r"(?:^|\n)(?:\d+\.\s+)?"  # 선택적 번호 접두사
        r"([^\n(]+?)"             # 소제목 (탐욕적이지 않게)
        r"\s*\(문단\s+([\w\d~～,\s.]+)\)"  # (문단 범위)
        r"\s*:"                   # 콜론
    )

    sections: list[dict] = []
    matches = list(sub_pattern.finditer(remaining_text))

    if matches:
        for i, m in enumerate(matches):
            title_raw = m.group(1).strip()
            para_text = m.group(2).strip()
            paras = parse_para_list(para_text)

            # 설명: 이 매치 끝부터 다음 매치 시작까지
            desc_start = m.end()
            desc_end = matches[i + 1].start() if i + 1 < len(matches) else len(remaining_text)
            desc_text = remaining_text[desc_start:desc_end].strip()
            # 첫 문장만 (너무 길면 자르기)
            desc = _clean_desc(desc_text)

            title = f"{title_raw} (문단 {para_text})"

            sections.append({
                "title": title,
                "desc": desc,
                "paras": paras,
                "bc_paras": [],
            })
    else:
        # 소제목 패턴이 없는 경우: 전체를 하나의 섹션으로
        if header_paras:
            sections.append({
                "title": header_line.split("]", 1)[-1].strip() if "]" in header_line else "기준서 핵심 요약",
                "desc": summary,
                "paras": header_paras,
                "bc_paras": [],
            })

    return summary, sections


def parse_bc_sections(sec3_text: str) -> list[dict]:
    """섹션 3 (결론도출근거)에서 BC sections 추출."""
    lines = sec3_text.split("\n")

    # 첫 줄: "3. [결론도출근거] 도입 이유 및 배경 (BC76~BC83)"
    header_line = lines[0] if lines else ""

    remaining_text = "\n".join(lines[1:])

    # BC 소제목 패턴: "도입 목적 (BC76):" or "제약의 적용 (BC203~BC212):"
    sub_pattern = re.compile(
        r"(?:^|\n)"
        r"([^\n(]+?)"             # 소제목
        r"\s*\((BC[\w~～,\sOA-Z]+)\)"  # (BC범위)
        r"\s*:"                   # 콜론
    )

    sections: list[dict] = []
    matches = list(sub_pattern.finditer(remaining_text))

    if matches:
        for i, m in enumerate(matches):
            title_raw = m.group(1).strip()
            bc_text = m.group(2).strip()
            bc_paras = parse_para_list(bc_text)

            desc_start = m.end()
            desc_end = matches[i + 1].start() if i + 1 < len(matches) else len(remaining_text)
            desc_text = remaining_text[desc_start:desc_end].strip()
            desc = _clean_desc(desc_text)

            sections.append({
                "title": title_raw,
                "desc": desc,
                "paras": [],
                "bc_paras": bc_paras,
            })
    else:
        # 소제목 없이 통째로 BC 범위만 있는 경우
        bc_paras = extract_bc_from_header(header_line)
        if bc_paras:
            sections.append({
                "title": "결론도출근거",
                "desc": "\n".join(lines[1:3]).strip(),
                "paras": [],
                "bc_paras": bc_paras,
            })

    return sections


def parse_appendix_b(sec2_text: str) -> list[dict]:
    """섹션 2 (부록 B)에서 B-paragraph sections 추출.

    대부분의 토픽은 "별도 지침 없음"이지만,
    일부 토픽(본인 vs 대리인, 라이선싱 등)은 본문급 분량의 내용이 있음.
    """
    lines = sec2_text.split("\n")
    remaining_text = "\n".join(lines[1:])

    # "별도 지침 없음" 패턴 확인
    no_guidance_patterns = [
        "별도로 할당된 지침이",
        "별도 지침이",
        "독립된 지침은 없",
        "별도로 할당된 세부 지침이",
        "별도로 배정",
        "지침이 완결",
    ]
    for pat in no_guidance_patterns:
        if pat in remaining_text:
            return []

    # B-paragraph 소제목 패턴: "제목 (문단 B34~B38):" or "제목 (문단 B3~B4):"
    sub_pattern = re.compile(
        r"(?:^|\n)(?:\d+단계:\s+)?"
        r"([^\n(]+?)"
        r"\s*\(문단\s+(B[\w\d~～,\s.]+)\)"
        r"\s*:"
    )

    sections: list[dict] = []
    matches = list(sub_pattern.finditer(remaining_text))

    if matches:
        for i, m in enumerate(matches):
            title_raw = m.group(1).strip()
            para_text = m.group(2).strip()
            paras = parse_para_list(para_text)

            desc_start = m.end()
            desc_end = matches[i + 1].start() if i + 1 < len(matches) else len(remaining_text)
            desc = _clean_desc(remaining_text[desc_start:desc_end])

            sections.append({
                "title": f"{title_raw} (문단 {para_text})",
                "desc": desc,
                "paras": paras,
                "bc_paras": [],
            })
    else:
        # 패턴 매칭 안 되지만 내용이 있는 경우 — B문단 참조를 전체 텍스트에서 추출
        b_refs = re.findall(r"문단\s+(B\d+[A-Z]?(?:[~～]B\d+[A-Z]?)?)", remaining_text)
        if b_refs:
            all_paras: list[str] = []
            for ref in b_refs:
                all_paras.extend(parse_para_list(ref))
            if all_paras:
                sections.append({
                    "title": "적용지침",
                    "desc": _clean_desc(remaining_text),
                    "paras": list(dict.fromkeys(all_paras)),  # 중복 제거, 순서 유지
                    "bc_paras": [],
                })

    return sections


def parse_ie_cases(sec4_text: str) -> tuple[str, list[dict]]:
    """섹션 4 (적용사례)에서 IE 케이스 추출."""
    lines = sec4_text.split("\n")

    # 첫 줄 이후 첫 의미있는 줄이 summary
    summary = ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("사례"):
            summary = stripped.rstrip(".")
            break

    # "사례 N (설명, IExx~IEyy):" 패턴
    cases: list[dict] = []
    for m in RE_IE_CASE.finditer(sec4_text):
        case_num = m.group(1)
        case_info = m.group(2)

        # IE 범위 추출
        ie_match = RE_IE_RANGE.search(case_info)
        para_range = ie_match.group(1) if ie_match else ""

        # 설명 부분 (IE 범위 제거)
        case_desc_raw = RE_IE_RANGE.sub("", case_info).strip().strip(",").strip()

        # 사례 번호 다음 텍스트 (콜론 이후)
        case_start = m.end()
        # 다음 사례 또는 섹션 끝까지
        next_match = RE_IE_CASE.search(sec4_text, case_start)
        case_end = next_match.start() if next_match else len(sec4_text)
        desc_text = _clean_desc(sec4_text[case_start:case_end])

        cases.append({
            "title": f"사례 {case_num}: {case_desc_raw}" if case_desc_raw else f"사례 {case_num}",
            "desc": desc_text,
            "para_range": para_range,
            "case_group_title": "",  # DB 조회로 채움
        })

    # "적용사례(IE) 중 ... 별도의 사례는 없습니다" 패턴 확인
    if not cases and ("별도의 사례는 없" in sec4_text or "별도로 마련된" in sec4_text):
        summary = ""

    return summary, cases


def parse_qna_ids(sec5_text: str) -> tuple[str, list[str]]:
    """섹션 5 (질의회신)에서 QNA ID 추출."""
    lines = sec5_text.split("\n")

    # 첫 줄 이후 첫 의미있는 줄이 summary
    summary = ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped and not RE_QNA_ID.search(stripped):
            summary = stripped.rstrip(".")
            break

    qna_ids = list(dict.fromkeys(RE_QNA_ID.findall(sec5_text)))
    return summary, qna_ids


def parse_finding_ids(sec6_text: str) -> tuple[str, list[str]]:
    """섹션 6 (감리지적사례)에서 감리사례 ID 추출."""
    lines = sec6_text.split("\n")

    # summary 추출
    summary = ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped and not RE_FINDING_ID.search(stripped):
            summary = stripped.rstrip(".")
            break

    finding_ids = list(dict.fromkeys(RE_FINDING_ID.findall(sec6_text)))
    return summary, finding_ids


def parse_cross_links(text: str) -> list[str]:
    """크로스 링크 섹션에서 토픽명 추출.

    "➡️ [3단계] 변동 대가:" 패턴에서 토픽명을 추출합니다.
    토픽명은 ': ' 직전까지의 텍스트입니다.
    """
    links: list[str] = []
    for m in re.finditer(r"➡️\s*\[[^\]]+\]\s*(.+?):", text):
        topic_name = m.group(1).strip()
        # 괄호 안 설명 제거: "변동 대가 (및 제약)" → "변동대가"
        topic_name = re.sub(r"\s*\([^)]*\)\s*", "", topic_name)
        # 공백 정규화
        topic_name = topic_name.strip()
        if topic_name:
            links.append(topic_name)
    return links


def _clean_desc(text: str) -> str:
    """설명 텍스트 정리 — 첫 2~3문장만 추출, 불필요한 공백 제거."""
    text = text.strip()
    # 줄바꿈을 공백으로
    text = re.sub(r"\n+", " ", text)
    # 연속 공백 제거
    text = re.sub(r"\s+", " ", text)
    # 마지막에 남는 마침표(.) 뒤의 불필요한 문장 제거 — 최대 300자
    if len(text) > 400:
        # 마침표 기준으로 300자 이내에서 자르기
        cut = text[:400].rfind(".")
        if cut > 100:
            text = text[:cut + 1]
    return text.strip()


def parse_topic_block(raw_header: str, block_text: str) -> dict:
    """하나의 토픽 블록을 파싱하여 TopicData dict를 반환."""
    # 키 결정
    header = raw_header.strip()
    topic_key = HEADER_TO_KEY.get(header, header)

    # 번호 섹션으로 분리
    sections = split_into_numbered_sections("\n" + block_text)

    # 1. 본문
    summary = ""
    main_sections: list[dict] = []
    if 1 in sections:
        summary, main_sections = parse_main_sections(sections[1])

    # 2. 부록 B
    appendix_sections: list[dict] = []
    if 2 in sections:
        appendix_sections = parse_appendix_b(sections[2])

    # 3. 결론도출근거
    bc_sections: list[dict] = []
    if 3 in sections:
        bc_sections = parse_bc_sections(sections[3])

    # 4. 적용사례
    ie_summary, ie_cases = "", []
    if 4 in sections:
        ie_summary, ie_cases = parse_ie_cases(sections[4])

    # 5. 질의회신
    qna_summary, qna_ids = "", []
    if 5 in sections:
        qna_summary, qna_ids = parse_qna_ids(sections[5])

    # 6. 감리지적사례
    findings_summary, finding_ids = "", []
    if 6 in sections:
        findings_summary, finding_ids = parse_finding_ids(sections[6])

    # 크로스 링크
    cross_links = parse_cross_links(block_text)

    # 모든 sections 합치기: 본문 → 부록B → BC
    all_main_sections = main_sections + appendix_sections + bc_sections

    return {
        "display_name": topic_key,
        "cross_links": cross_links,
        "main_and_bc": {
            "summary": summary,
            "sections": all_main_sections,
        },
        "ie": {
            "summary": ie_summary,
            "cases": ie_cases,
        },
        "qna": {
            "summary": qna_summary,
            "qna_ids": qna_ids,
        },
        "findings": {
            "summary": findings_summary,
            "finding_ids": finding_ids,
        },
    }


def main() -> None:
    """메인 실행: 큐레이션 텍스트 파싱 → JSON 출력."""
    raw_text = INPUT_FILE.read_text(encoding="utf-8")

    # "## " 기준으로 토픽 블록 분리
    # "# " (대섹션 헤더)은 무시
    topic_blocks: list[tuple[str, str]] = []
    parts = re.split(r"\n## ", raw_text)

    for part in parts[1:]:  # 첫 번째는 파일 헤더
        # 첫 줄이 토픽 헤더
        first_newline = part.find("\n")
        if first_newline == -1:
            continue
        header = part[:first_newline].strip()
        body = part[first_newline:]
        topic_blocks.append((header, body))

    print(f"📂 {len(topic_blocks)}개 토픽 블록 감지")

    # 각 토픽 파싱
    result: dict[str, dict] = {}
    for header, body in topic_blocks:
        topic_key = HEADER_TO_KEY.get(header.strip(), header.strip())
        topic_data = parse_topic_block(header, body)
        result[topic_key] = topic_data

        # 통계 출력
        n_sections = len(topic_data["main_and_bc"]["sections"])
        n_cases = len(topic_data["ie"]["cases"])
        n_qna = len(topic_data["qna"]["qna_ids"])
        n_findings = len(topic_data["findings"]["finding_ids"])
        n_links = len(topic_data["cross_links"])
        print(
            f"  ✅ {topic_key:30s} | "
            f"sections={n_sections:2d}  cases={n_cases}  "
            f"qna={n_qna}  findings={n_findings}  links={n_links}"
        )

    # 기존 파일 로드 (보존 로직용)
    existing: dict | None = None
    if OUTPUT_FILE.exists():
        existing = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))

    # ── 통합 토픽 → 개별 토픽 분할 ────────────────────────────────────────────
    # Why: 큐레이션 원본은 "통제 이전의 특수 형태"(4개)와 "고객의 권리 관련"(3개)을
    # 합산 헤더로 묶지만, UI·decision_trees는 개별 토픽명으로 참조.
    # 이전에는 _add_topics.py를 별도 실행했으나, 매번 누락되어 반복 사고 발생.
    # ADR-16 교훈: 파이프라인을 단일 스크립트로 통합하여 누락 원천 차단.
    result = _split_merged_topics(result, existing=existing)

    # 기존 파일의 qna_descs/finding_descs 보존 (파이프라인 재실행 시 유실 방지)
    # Why: qna_descs/finding_descs는 수동 큐레이션 데이터라 파싱 결과에 없음
    if existing:
        preserved = 0
        for topic_key, topic_val in existing.items():
            if topic_key not in result:
                continue
            for sec_key, desc_key in [("qna", "qna_descs"), ("findings", "finding_descs")]:
                old_descs = topic_val.get(sec_key, {}).get(desc_key, {})
                if old_descs and sec_key in result[topic_key]:
                    new_descs = result[topic_key][sec_key].get(desc_key, {})
                    if not new_descs or len(new_descs) < len(old_descs):
                        result[topic_key][sec_key][desc_key] = old_descs
                        preserved += len(old_descs)
        if preserved:
            print(f"\n🔒 기존 desc 보존: {preserved}건 (qna_descs + finding_descs)")

    # JSON 출력
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n💾 {OUTPUT_FILE} 저장 완료 ({len(result)}개 토픽)")


def _split_merged_topics(topics: dict, existing: dict | None = None) -> dict:
    """통합 토픽 2개를 7개 개별 토픽으로 분할합니다.

    _add_topics.py에 하드코딩된 데이터를 그대로 이관.
    이 함수가 main() 안에서 자동 호출되므로 별도 스크립트 실행 불필요.

    existing이 주어지면 split 토픽의 qna_descs/finding_descs도 보존합니다.
    Why: SPLIT_TOPICS는 정적 하드코딩이라 topics.json 수동 편집 내용이 덮어씌워짐
    """
    from app.preprocessing._add_topics_data import SPLIT_TOPICS, MERGED_KEYS

    removed = 0
    for key in MERGED_KEYS:
        if key in topics:
            del topics[key]
            removed += 1

    topics.update(SPLIT_TOPICS)

    # 기존 topics.json의 split 토픽 필드도 보존 (qna_descs/finding_descs)
    if existing:
        preserved = 0
        for topic_key in SPLIT_TOPICS:
            if topic_key not in existing:
                continue
            for sec_key, desc_key in [("qna", "qna_descs"), ("findings", "finding_descs")]:
                old_descs = existing[topic_key].get(sec_key, {}).get(desc_key, {})
                if old_descs:
                    new_descs = topics[topic_key].get(sec_key, {}).get(desc_key, {})
                    if not new_descs or len(new_descs) < len(old_descs):
                        topics[topic_key][sec_key][desc_key] = old_descs
                        preserved += len(old_descs)
        if preserved:
            print(f"   🔒 split 토픽 desc 보존: {preserved}건")

    print(f"\n🔀 토픽 분할: {removed}개 통합 토픽 제거 → {len(SPLIT_TOPICS)}개 개별 토픽 추가")
    print(f"   최종 토픽 수: {len(topics)}개")
    return topics


def verify_data_consistency() -> None:
    """topics.json ↔ summary-embeddings.json ↔ topic-embeddings.json 교차 검증.

    파이프라인 실행 순서(10→12→13) 미준수 시 데이터 버전 불일치를 감지합니다.
    """
    summary_path = Path("data/topic-curation/summary-embeddings.json")
    topic_embed_path = Path("data/topic-curation/topic-embeddings.json")

    if not OUTPUT_FILE.exists():
        print("⚠️  topics.json이 없습니다. 먼저 10-parse-curation.py를 실행하세요.")
        return

    topics = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    topic_keys = set(topics.keys())
    issues = 0

    # topics.json에 등록된 QNA/감리사례 ID 수집
    valid_ids: set[str] = set()
    for td in topics.values():
        valid_ids.update(td.get("qna", {}).get("qna_ids", []))
        valid_ids.update(td.get("findings", {}).get("finding_ids", []))

    # summary-embeddings.json 검증
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        orphaned = [k for k in summary if k not in valid_ids]
        if orphaned:
            print(f"⚠️  summary-embeddings.json orphaned ID {len(orphaned)}건: {orphaned[:5]}")
            issues += len(orphaned)
    else:
        print("ℹ️  summary-embeddings.json 미존재 — 12-summary-embed.py 실행 필요")

    # topic-embeddings.json 검증
    if topic_embed_path.exists():
        topic_embeds = json.loads(topic_embed_path.read_text(encoding="utf-8"))
        orphaned_topics = [k for k in topic_embeds if k not in topic_keys]
        if orphaned_topics:
            print(f"⚠️  topic-embeddings.json orphaned 토픽 {len(orphaned_topics)}건: {orphaned_topics}")
            issues += len(orphaned_topics)
    else:
        print("ℹ️  topic-embeddings.json 미존재 — 13-topic-embed.py 실행 필요")

    if issues == 0:
        print("✅ 데이터 교차 검증 통과 — 불일치 0건")
    else:
        print(f"\n⚠️  총 {issues}건 불일치 감지. 12→13 스크립트를 재실행하세요.")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 60)
    verify_data_consistency()
