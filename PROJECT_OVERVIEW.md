# K-IFRS 1115 Chatbot — 프로젝트 개요

> **이 문서는 LLM에게 프로젝트 컨텍스트를 전달하기 위해 작성되었습니다.**
> 기술 스택, 환경 변수, 실행 명령어, 코딩 컨벤션은 **CLAUDE.md** 참조.
>
> **최종 업데이트**: 2026-03-12

---

## 1. 프로젝트 목적

회계법인 입사를 위한 **포트폴리오 프로젝트 #1**.

**K-IFRS 제1115호(고객과의 계약에서 생기는 수익)** 에 관하여, **회계감사인(감사인)**들이 객관적인 팩트를 손쉽게 찾고, AI의 구조화된 가이드를 통해 판단을 내릴 수 있도록 하는 **전문 도구**입니다.

### 핵심 설계 철학: 2종오류 방지

회계감사에서 오류는 두 가지 유형으로 나뉩니다:

| 오류 유형 | 정의 | 위험도 |
|-----------|------|--------|
| **1종오류** | 존재하지 않는 오류를 지적함 (과잉 지적) | 낮음 — 추가 검토로 해소 가능 |
| **2종오류** | 실재하는 오류를 놓침 (누락) | **치명적** — 부실감사, 제재, 투자자 피해 |

이 프로젝트는 **2종오류 방지에 올인**합니다. LLM이 자유롭게 추론하면 그럴듯하지만 틀린 답(환각)을 생성할 수 있고, 이는 곧 실재하는 회계 쟁점을 놓치는 2종오류로 이어집니다.

### LLM 역할 재정의: "추론자" → "전달자"

- **DB에 저장된 팩트만 전달**: K-IFRS 1115호 본문 + 적용사례(IE) + 질의회신(QNA) + 감리지적사례 + KAI 교육자료(5건, AI 답변 컨텍스트 전용)
- LLM의 자유 추론을 **PydanticAI structured output + Decision Tree**로 구조적으로 제한
- 사전 큐레이션된 결론 가이드(MASTER_DECISION_TREES)를 LLM이 **그대로 전달**
- AI가 먼저 답하는 것이 아니라, **사용자가 먼저 팩트(근거 문서)를 확인**한 뒤 AI에게 질문하는 **"근거 선행, AI 후행"** 구조

### Trade-off

> 이 설계는 **규칙 기반 전문가 시스템**에 가깝습니다.
> 새로운 사업모델(메타버스, DeFi), 타 기준서 교차(1116호 리스 + 1115호 수익), 고도의 복합적 사실판단(Gray Area)에서는 효과가 제한됩니다.
> 대신, K-IFRS 1115호 범위 내에서 **기존 판례와 기준서 원문에 근거한 답변의 신뢰성**을 극대화합니다.

---

## 2. 핵심 UX 흐름 (4단계 State Machine)

```
홈(home) → 토픽 클릭 → 토픽 브라우즈(topic_browse) → 자유 질문 → 근거 열람(evidence) → AI 질문 → AI 답변(ai_answer)
         → 자유 검색 입력 → 근거 열람(evidence) → AI 질문 → AI 답변(ai_answer)
```

- **홈**: 좌(5단계 수익인식 모형) / 우(후속 처리·특수 거래) — 8섹션 매트릭스
- **토픽 브라우즈**: 4탭(본문·BC | 적용사례 | 질의회신 | 감리사례) + 관련 토픽 칩 + 하단 직접 질문
- **근거 열람**: RAG 검색 결과 카테고리별 아코디언
- **AI 답변**: Split View — 좌(근거 문서) + 우(AI 답변 + 꼬리질문)

---

## 3. 디렉토리 구조

```
k-ifrs-1115-chatbot/
├── app/
│   ├── api/
│   │   ├── routes.py              # FastAPI 라우터 (/chat, /search, /health)
│   │   └── schemas.py             # Pydantic 요청/응답 스키마
│   ├── domain/                    # Decision Tree + 큐레이션
│   │   ├── decision_trees.py      # MASTER_DECISION_TREES (25개 토픽)
│   │   ├── tree_matcher.py        # 키워드→점수→상위 2개 매칭
│   │   ├── summary_matcher.py     # 서머리 임베딩 매칭
│   │   └── topic_content_map.py   # topics.json 로드
│   ├── nodes/                     # 1파일 1노드: analyze, retrieve, rerank, generate, format
│   ├── services/                  # chat_service(SSE), search_service, session_store
│   ├── preprocessing/             # 데이터 전처리 파이프라인 (순서대로 실행, 99-verify-chunks.py로 검증)
│   ├── test/                      # 연결·검색 테스트
│   ├── ui/                        # Streamlit UI 컴포넌트 (18파일)
│   │   ├── layout.py              # CSS 주입 + 헤더 + 사이드바
│   │   ├── pages.py               # 홈/근거열람/AI답변 페이지 렌더러
│   │   ├── topic_browse.py        # 토픽 브라우즈 오케스트레이터
│   │   ├── topic_tabs.py          # 4탭 렌더링 (본문·BC, IE, QNA, 감리)
│   │   ├── evidence.py            # 근거 열람 아코디언
│   │   ├── db.py                  # MongoDB 조회 (PDR 라우팅 + cache)
│   │   └── (그 외 12파일)          # components, session, text, modal 등
│   ├── main.py                    # FastAPI 진입점 (lifespan + CORS + BM25 인덱스 빌드)
│   ├── streamlit_app.py           # Streamlit UI 진입점
│   ├── config.py                  # pydantic-settings 중앙 설정
│   ├── agents.py                  # PydanticAI Agent 정의 (ClarifyOutput/GenerateOutput + result_validator)
│   ├── pipeline.py                # 순수 Python async generator 오케스트레이션
│   ├── embeddings.py              # Upstage REST API 직접 호출 (async + sync)
│   ├── retriever.py               # 검색 엔진 (Vector + BM25 + RRF 융합)
│   ├── reranker.py                # Cohere Reranker 래퍼
│   ├── prompts.py                 # 프롬프트 (reasoning_guard + 분기 강제 지시)
│   └── state.py                   # RAGState TypedDict
├── data/                          # raw/(gitignore), web/(청크JSON), findings/, topic-curation/topics.json
├── Dockerfile / docker-compose.yml / pyproject.toml
├── CLAUDE.md                      # 프로젝트 지침 (Claude Code 자동 로드)
└── PROJECT_OVERVIEW.md            # ← 이 파일
```

---

## 4. RAG 파이프라인 (순수 Python 오케스트레이션)

```
pipeline.py — async generator, SSE yield
  [fast-path] clarify 후속 턴 → generate만 실행 (스킵: analyze/retrieve/rerank)
  [일반 흐름] analyze → retrieve → rerank → generate → format
                                    ↓
                              is_situation?
                              ├─ True  → clarify_agent → ClarifyOutput
                              │           (selected_branches + cited_paragraphs + 꼬리질문)
                              └─ False → generate_agent → GenerateOutput
                                          (cited_paragraphs + 듀얼트랙 모델 라우팅)

  [듀얼트랙 라우팅] _needs_calculation() = True?
    ├─ Yes  → gpt-4.1-mini (calc, topic_knowledge 스킵으로 산술 집중도 유지)
    ├─ No, simple  → Gemini Flash (thinking=low, 빠름)
    └─ No, complex → Gemini Flash (thinking=high, 회계 추론 품질 1위)
```

| 노드 | 역할 | Agent / LLM |
|------|------|-------------|
| analyze | 질문 분석/라우팅/complexity 판단 | `analyze_agent` (gpt-4.1-mini) |
| retrieve | **2계층 검색**: 핀포인트(큐레이션 1순위) + 리트리버(벡터+BM25 2순위) | — |
| rerank | Cohere Reranker — rerank_threshold 미만 제거 | — |
| generate | 개념 답변 생성 | `generate_agent` (Gemini Flash / calc→gpt-4.1-mini) → `GenerateOutput` |
| clarify | 거래 상황 꼬리질문 (멀티턴 체크리스트) | `clarify_agent` (Gemini Flash / calc→gpt-4.1-mini) → `ClarifyOutput` |
| format | 감리사례 넛지 추가 | — |

### 핵심 메커니즘

- **2계층 검색**: 핀포인트(큐레이션 문서 직접 조회, 1순위) + 리트리버(Vector+BM25+RRF, 2순위)
- **핀포인트 Fetch**: decision_tree의 precedents/red_flags에서 문서 ID 파싱 → MongoDB 직접 조회 (QNA 66건, 감리 17건, IE 55건, 교육 5건 = 143 고유 참조)
- **PDR**: QNA/감리/교육자료 Child 청크 → parent_id로 부모 원문 전체 조회
- **듀얼트랙 모델 라우팅**: 계산→gpt-4.1-mini / simple→Gemini low / complex→Gemini high
- **멀티턴 체크리스트**: clarify가 Dynamic 체크리스트 주입, Q&A 쌍 추적
- **Precedents 직접 주입**: MASTER_DECISION_TREES의 IE/QNA/감리사례를 context에 직접 주입
- **감리사례 섀도우 매칭**: format에서 유사 감리 지적사례 자동 매칭

### Agent 구성 (`agents.py`)

| Agent | 기본 모델 | 계산 폴백 | 출력 |
|-------|----------|----------|------|
| `analyze_agent` | gpt-4.1-mini | — | `AnalyzeResult` |
| `generate_agent` | Gemini Flash (thinking=high) | gpt-4.1-mini | `GenerateOutput` |
| `clarify_agent` | Gemini Flash (thinking=high) | gpt-4.1-mini | `ClarifyOutput` |
| `text_agent` | gpt-4.1-mini | — | `str` |
| `calc_clarify_agent` | gpt-4.1-mini | — | `CalcClarifyOutput` (계산 전용, topic_knowledge 스킵) |
| `calc_fallback` | gpt-4.1-mini | — | (model override용) |

---

## 5. 환각 방지 아키텍처

이 프로젝트의 핵심 차별점은 **5단계 방어 레이어**로 LLM 환각을 구조적으로 차단하는 것입니다.

### 5단계 방어 레이어

| # | 방어 레이어 | 메커니즘 | 핵심 파일 |
|---|------------|---------|----------|
| 1 | **Domain 큐레이션** | MASTER_DECISION_TREES — 25개 토픽별 체크리스트 + 결론가이드 + 감리경고 + 선례 + 계산공식 | `decision_trees.py` |
| 2 | **PydanticAI Structured Output** | ClarifyOutput — `selected_branches`(분기 선택 강제) + `cited_paragraphs`(인용 강제) | `agents.py` |
| 3 | **result_validator** | 빈 인용/빈 분기 → `ModelRetry`로 LLM 재호출 (retries=2) | `agents.py` |
| 4 | **reasoning_guard** | 프롬프트에 논리 뒤집음 방지 규칙, `[결론 가이드]`에 없는 분기 생성 금지 | `prompts.py` |
| 5 | **Precedents 직접 주입** | retriever 의존도 축소 — 큐레이션된 IE사례/질의회신/감리사례를 **핀포인트 fetch로 원문 주입** + context 요약 주입 | `retrieve.py`, `retriever.py`, `generate.py` |

### 데이터 플로우

```
사용자 질문 → analyze_agent → match_topics()
  → matched_topics
    ├→ checklist_text → system prompt (분기 강제)           ... 레이어 1
    ├→ precedents + formula → context 직접 주입             ... 레이어 5
    └→ clarify_agent → ClarifyOutput                       ... 레이어 2
        ├→ selected_branches (결론가이드 분기만 허용)        ... 레이어 4
        ├→ cited_paragraphs (근거 문단 필수)
        └→ result_validator (빈값 reject → ModelRetry)      ... 레이어 3
```

**핵심**: 분기 제한(레이어1,4) + 인용 강제(레이어2) + 자동 재시도(레이어3) + 선례 주입(레이어5) → LLM이 근거 없는 답변을 생성할 수 없는 구조

---

## 6. 도메인 체크리스트 시스템 (`app/domain/`)

`analyze` 노드가 추출한 키워드를 `MASTER_DECISION_TREES`의 `trigger_keywords`와 매칭하여, `is_situation=True`일 때 `clarify_agent`의 system prompt에 체크리스트 + 결론가이드를 동적 주입합니다.

### MASTER_DECISION_TREES 스키마 (25개 토픽)

```python
MASTER_DECISION_TREES = {
    "토픽명": {
        "1_routing": {"trigger_keywords": [...], "judgment_goal": str},
        "2_checklist": [str, ...],           # Yes/No 판단 질문
        "3_conclusion_guide": ["[분기 1] 조건 → 결론", ...],
        "4_precedents": {"[분기 1]": ["IE45~48: ...", ...]},
        "5_red_flags": {"question": str, "risk_if_yes": str},
        "6_calculation_formula": {"[분기 1]": "투입법: ..."},  # 선택
    }
}
```

### 매칭 로직 (`tree_matcher.py`)

`trigger_keywords` 양방향 부분 문자열 매칭 → score 내림차순 **상위 2개** 반환.
반환값: `topic_name`, `checklist_text`(system prompt용), `precedents`(context 주입용), `red_flags`(핀포인트 fetch용), `judgment_goal`, `calculation_formula`, `score`

---

## 7. 토픽 큐레이션 시스템

25개 토픽에 대해 `topics.json`의 정적 데이터로 관련 문단을 즉시 조회 (RAG 검색 불필요).

```python
TopicData = {
    "display_name": str,
    "cross_links": list[str],         # 관련 토픽 추천
    "main_and_bc": {"summary": str, "sections": [{"title": str, "paras": [...], "bc_paras": [...]}]},
    "ie": {"summary": str, "cases": [{"title": str, "para_range": "IE19~IE24", "case_group_title": str}]},
    "qna": {"summary": str, "qna_ids": [...]},
    "findings": {"summary": str, "finding_ids": [...]},
}
```

4탭 조회: 본문·BC(`fetch_docs_by_para_ids`), 적용사례(`_expand_para_range`→배치), 질의회신/감리(`fetch_parent_doc`→PDR 라우팅)
---

## 8. 데이터 소스 및 청크 스키마

**총 청크**: 약 1,303개 (K-IFRS 1115호 본문·적용지침·BC·IE + QNA 101건 + 감리사례 18건 + KAI 교육자료 5건 + 토픽 큐레이션)

```python
# MongoDB 청크 스키마
{
    "chunk_id": str,          # 고유 식별자
    "content": str,           # 청크 본문
    "source": str,            # "본문", "QNA", "감리사례" 등
    "category": str,          # "본문", "적용지침B", "결론도출근거" 등
    "weight_score": float,    # 카테고리별 검색 가중치
    "hierarchy": str,         # Breadcrumb 경로 (문맥 보강)
    "embedding": list[float], # Upstage solar-embedding 벡터 (passage 모드)
}
```

---

## 9. UI/UX 스타일링

- **shadcn/ui + Linear 스타일**, Tailwind Slate 색상 토큰 기반
- 버튼 스타일링: `key="nav_xxx"` + `div[class*="st-key-nav_"]` CSS 셀렉터 (JS/iframe 금지)
- 상세 디버깅 교훈: `debugging.md` 참조

---

## 10. 향후 개발 방향

- [ ] 통합 테스트 + 시연용 골든셋 구축
- [ ] Gray Area 방어, 멀티토픽 동시 매칭
- [ ] BIG4 가이드 임베딩, RAGAS 평가 자동화, Oracle Cloud 배포
