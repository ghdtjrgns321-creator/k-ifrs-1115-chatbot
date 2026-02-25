# K-IFRS 1115호 PDF → 마크다운 변환 (Upstage Document Parse API)

import os
import json
from dotenv import load_dotenv
from langchain_upstage import UpstageDocumentParseLoader

load_dotenv()

# ── 설정 ──
PDF_PATH = "data/raw/k-ifrs-1115.pdf"
OUTPUT_JSON = "data/processed/parsed_elements.json"   # 요소별 파싱 결과
OUTPUT_MD = "data/processed/k-ifrs-1115.md"           # 전체 마크다운 (확인용)

# ── PDF 파싱 ──
loader = UpstageDocumentParseLoader(
    PDF_PATH,
    split="element",          # 제목/문단/표를 개별 요소로 분할
    output_format="markdown", # 표를 | col1 | col2 | 형태로 보존
    ocr="auto",               # 스캔 페이지 있으면 자동 OCR
)

docs = loader.load()

# ── 결과 저장 (JSON — 이후 Step에서 사용) ──
parsed = []
for doc in docs:
    parsed.append({
        "content": doc.page_content,
        "metadata": {
            "category": doc.metadata.get("category", ""),  # heading / paragraph / table 등
            "page": doc.metadata.get("page", 0),
        }
    })

with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(parsed, f, ensure_ascii=False, indent=2)

# ── 전체 마크다운 저장 (육안 확인용) ──
with open(OUTPUT_MD, "w", encoding="utf-8") as f:
    for elem in parsed:
        f.write(elem["content"] + "\n\n")

# ── 검증 ──
print(f"✅ 총 {len(parsed)}개 요소 추출")

# 카테고리별 분포
from collections import Counter
cats = Counter(e["metadata"]["category"] for e in parsed)
for cat, cnt in cats.most_common():
    print(f"   {cat}: {cnt}개")

# 표 포함 여부 확인
table_count = sum(1 for e in parsed if e["metadata"]["category"] == "table")
print(f"   → 표(table) {table_count}개 보존됨")

# 총 페이지 수
max_page = max(e["metadata"]["page"] for e in parsed)
print(f"   → {max_page}페이지 처리 완료")

# ✅ 총 3424개 요소 추출
#    paragraph: 2061개
#    footer: 516개
#    heading1: 410개
#    list: 330개
#    table: 83개
#    footnote: 20개
#    header: 2개
#    caption: 2개
#    → 표(table) 83개 보존됨
#    → 517페이지 처리 완료