# Step 1 결과(parsed_elements.json)를 6개 섹션으로 분리

import json
import os

# ── 입출력 경로 ──
INPUT_JSON = "data/processed/parsed-elements.json"
OUTPUT_DIR = "data/sections"
os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(INPUT_JSON, "r", encoding="utf-8") as f:
    parsed = json.load(f)

# ── 섹션 분류 키워드 (헤더 텍스트 기준) ──
# 순서 중요: 위에서부터 매칭하므로, 더 구체적인 키워드를 먼저 배치
SECTION_RULES = [
    ("부록A_용어",      ["부록 A", "용어의 정의"]),
    ("부록B_적용지침",   ["부록 B", "적용지침"]),
    ("부록C_경과규정",   ["부록 C", "시행일", "경과 규정"]),
    ("적용사례",        ["적용사례", "설례"]),
    ("결론도출근거",     ["결론도출근거", "결론 도출 근거"]),
]

# ── 헤더를 만나면 섹션 전환 ──
current_section = "본문"  # 기본값: 문서 시작은 본문
section_elements = {}

for elem in parsed:
    content = elem["content"].strip()
    category = elem["metadata"].get("category", "")

    # 헤더 요소일 때만 섹션 전환 판단
    if category == "heading" or content.startswith("#"):
        for section_name, keywords in SECTION_RULES:
            if any(kw in content for kw in keywords):
                current_section = section_name
                break

    section_elements.setdefault(current_section, []).append(elem)

# ── 섹션별 저장 ──
for section_name, elements in section_elements.items():
    # JSON (Step 3에서 사용)
    json_path = os.path.join(OUTPUT_DIR, f"{section_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(elements, f, ensure_ascii=False, indent=2)

    # MD (육안 확인용)
    md_path = os.path.join(OUTPUT_DIR, f"{section_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        for elem in elements:
            f.write(elem["content"] + "\n\n")

# ── 검증 ──
print("✅ 섹션 분리 완료\n")
for section_name, elements in sorted(section_elements.items()):
    # 표 개수 별도 집계
    tables = sum(1 for e in elements if e["metadata"].get("category") == "table")
    print(f"   {section_name}: {len(elements)}개 요소 (표 {tables}개)")

# 본문 + 부록B가 전체의 핵심 (이 둘만으로 MVP 가능)
core = len(section_elements.get("본문", [])) + len(section_elements.get("부록B_적용지침", []))
total = sum(len(v) for v in section_elements.values())
print(f"\n   → 본문 + 부록B = {core}개 ({core/total*100:.0f}%) ← MVP 핵심")
"""

**예상 출력**:
```
✅ 섹션 분리 완료

   본문: ~450개 요소 (표 12개)
   부록A_용어: ~30개 요소 (표 0개)
   부록B_적용지침: ~280개 요소 (표 25개)
   부록C_경과규정: ~40개 요소 (표 2개)
   적용사례: ~600개 요소 (표 80개)
   결론도출근거: ~1100개 요소 (표 30개)

   → 본문 + 부록B = 730개 (29%) ← MVP 핵심
   """