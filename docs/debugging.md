# 디버깅 교훈

> 최종 업데이트: 2026-03-15 (#32~#41 추가)
>
> Streamlit 관련 교훈은 [STREAMLIT.md](STREAMLIT.md) §8로 이동됨.

---

## 0. 핵심 원칙: 정규식은 최후의 수단, 근본 원인을 먼저 해결

### 문제 인식

이 프로젝트에서 반복된 안티패턴: **출력 단계에서 정규식으로 데이터 결함을 땜질** → 새 에지 케이스 발견 → 정규식 추가/수정 → 또 다른 에지 케이스... 무한 루프.

해당 항목: #3(범위 확장 패턴 추가), #6(체이닝 루프 횟수 증가), #12(파싱 분기 7가지), #14·#17(같은 파일 유사 정규식 반복 패치)

### 올바른 접근 순서

| 우선순위 | 방법 | 예시 |
|---------|------|------|
| **1순위** | **데이터 원본 수정** | `topics.json` 공백 정규화, cross_links 키 수정 (#2, #9) |
| **2순위** | **전처리 파이프라인에서 정규화** | 크롤링 단계에서 인라인 태그 보존 파싱, 물결표 3종 통일 |
| **3순위** | **구조적 접근으로 대체** | 문단 번호 매칭 → 서머리 임베딩 (#16), reranker → bypass (#15) |
| **4순위** | **정규식 (최후 수단)** | 위 3가지로 해결 불가한 경우에만. 반드시 테스트 전수 검증 동반 |

### 정규식을 쓸 때의 체크리스트

1. **"데이터 원본에서 해결 가능한가?"** — 가능하면 정규식 쓰지 마라
2. **"전처리에서 한 번만 처리하면 되지 않나?"** — 런타임 후처리보다 전처리 1회가 낫다
3. **"유사 정규식이 같은 파일에 이미 있는가?"** — 있으면 함수로 통합하라 (#14)
4. **"커버 못하는 패턴이 뭔가?"** — 반례를 먼저 나열하고 시작하라
5. **에지 케이스 3개 이상이면 설계를 재검토하라** — 파서/구조적 접근이 필요한 신호

### 실패 vs 성공 사례

| | 실패 (정규식 땜질) | 성공 (근본 해결) |
|---|---|---|
| 감리사례 매칭 | 문단 번호 추출 → 블랙리스트 → 노이즈 | 서머리 임베딩 직접 비교 (#16) |
| 데이터 공백 | 런타임 `re.sub(r"\s+\.", ".")` | 원본 JSON 정규화 (#9) |
| 큐레이션 탈락 | rerank 임계값 조정 | bypass 경로 분리 (#15) |

---

## 1. 외부 데이터의 숨겨진 문자 패턴

### JSON 공백 패턴
`topics.json`에서 `"합니다 ."` (다와 `.` 사이 공백)으로 저장. 정규식 매칭 실패의 원인.
→ `repr()`로 실제 데이터 확인 후, 정규화 전처리 추가.

### Unicode 변형 (물결표 3종)
kifrs.com 원본에 `~`(U+007E, 108건) / `∼`(U+223C, 28건) / `～`(U+FF5E, 3건) 혼재.
→ 모든 문자 클래스에 3종 모두 포함: `[~～∼\-]`

**교훈**: 외부 데이터의 유사 문자(tilde, dash, quote 등)는 `repr()` + `ord()`로 실제 코드포인트를 반드시 확인. 시각적으로 동일해도 코드포인트가 다를 수 있음.

---

## 2. 데이터 정합성 문제는 데이터에서 해결

- **cross_links 불일치**: cross_link 값이 topics.json 키와 불일치 → JSON 데이터 자체를 수정. 코드에서 퍼지 매칭은 복잡도만 증가.
- **토픽 별칭 해석 순서**: 빈 스텁이 존재하면 정확 매칭이 잘못된 결과 반환 → 별칭 매핑을 **최우선**으로 체크.

---

## 3. `_expand_para_range` — 문단 범위 확장 로직

### 처리해야 하는 패턴 (매칭 우선순위)

| 순서 | 패턴 | 예시 | 확장 결과 |
|------|------|------|-----------|
| 1 | 소수점 하위번호 | `한129.1~5` | `한129.1`, ..., `한129.5` |
| 2 | 접미사 없음→있음 | `B63~B63B` | `B63`, `B63A`, `B63B` |
| 3 | 양쪽 알파벳 접미사 | `IE238A~IE238G` | `IE238A`, ..., `IE238G` |
| 4 | 숫자 범위 | `B20~B27` | `B20`, ..., `B27` |

### 주요 수정사항
- **접두사 패턴**: `[A-Za-z]*?` → `[A-Za-z가-힣]*?` (한글 접두사 대응)
- **하위 문단 접미사**: `B19(1)` → `re.sub(r"\([0-9가-힣]+\)$", "", raw_num)` 으로 정리
- **물결표**: `[~～∼\-]` 3종 모두 포함

**교훈**: 범위 확장 로직은 실데이터의 모든 패턴(접두사 문자셋, 접미사 유무 조합, 숫자 체계)을 커버해야 함. 새 데이터 추가 시 `99-verify-chunks.py`로 전수 검증.

---

## 4. 청킹 시 번호 목록 `(1)(2)(3)` 누락 버그

### 근본 원인 (3가지)
1. **`para-inner-number-item` HTML 구조 미처리**: kifrs.com API가 `idt-1` 대신 별도 구조 사용. `clean_html_to_md()`가 이 구조를 무시.
2. **조사 이음 정규식이 번호 항목을 먹음**: `")\n이"` → `"(2)\n이 재화나"` → `"(2)이 재화나"`로 합침.
3. **마크다운 단일 `\n`은 줄바꿈 아님**: `\n\n`(이중 줄바꿈)만 단락 분리됨.

### 해결
부모 div 단위로 `number-item` + `hanguel-item` 텍스트를 `\n\n`으로 조립. 후처리로 번호 항목 앞 `\n\n` 보장.

**교훈**: HTML 파싱 후 반드시 원본(`fullContent`)과 비교 검증. `get_text(strip=True)`는 앞뒤 공백/줄바꿈을 제거하므로 주의.

---

## 5. `paraContent` < `fullContent` 텍스트 유실

kifrs.com API가 일부 문단에서 `paraContent`에 본문 일부만 제공. HTML 파싱 후 `fullContent` 키워드 비교 → **30% 이상 유실이면 `fullContent`로 폴백**.

영향: 2건 (BC445I, BC445L) + 웩12.

---

## 6. 문단 참조 볼드 강조 — 체이닝 에지 케이스

### 수정 포인트 4가지
1. **범위 표기(`~`) 처리**: `\d+[A-Za-z]*` → 뒤에 `(?:[~～∼\-]...\d+[A-Za-z]*)?` 추가
2. **루프 횟수**: 3 → 15 (실데이터 최대 13개 나열, `n==0`이면 즉시 탈출)
3. **"와" 접속사 추가**: `및|과|또는|그리고` → `및|과|와|또는|그리고`
4. **괄호 suffix 건너뛰기**: `</span>(3), 37` → `(?:\([0-9가-힣]+\))?` 추가

**교훈**: 정규식 체이닝은 1회에 1단계만 진행하므로, 루프 횟수가 실데이터의 최대 나열 수를 커버해야 함.

---

## 7. QNA/감리사례 parent 문서 처리

### 컬렉션 라우팅
parent 문서는 메인 컬렉션이 아닌 **별도 컬렉션**에 저장:
- QNA → `k-ifrs-1115-qna-parents` (키: `_id`)
- 감리사례 → `k-ifrs-1115-findings-parents` (키: `_id`)

ID 접두사(`QNA-`, `FSS-`, `KICPA-`)로 라우팅.

### 메타데이터 중첩
parent 컬렉션은 `title`, `hierarchy`가 **`metadata` dict 안에** 중첩 저장. top-level 먼저 확인 후 `metadata` 안에서 찾는 유틸 함수 사용.

### 감리지적사례 제목 비일관성
DB title이 비일관적 (레퍼런스 접두어 포함 / 빈 title / ID 미포함 등) → `_build_pdr_label()`로 여러 케이스 방어적 처리.

**교훈**: PDR 구조에서 parent/child가 다른 컬렉션·다른 스키마일 수 있음. 조회 후 `repr(doc.keys())`로 실제 구조 확인.

---

## 8. summary 줄바꿈 — 범용 한국어 어미 처리

`다.`만 매칭하면 `함.`, `음.`, `됨.` 등 누락. **한글 + 마침표** 범용 패턴으로 변경:
```python
t = re.sub(r"(?<=[가-힣])\s+\.", ".", t)       # 공백 정규화
t = re.sub(r"(?<=[가-힣])\.\s+", ".<br>", t)   # 줄바꿈
```
영문/숫자 뒤 마침표는 lookbehind `[가-힣]`로 영향 없음.

---

## 9. LLM 생성 텍스트 유출 (`finding_descs`)

### 문제 유형
1. **크로스 링크 추천 텍스트** (21건): LLM 응답 말미의 `💡 크로스 링크 추천` 구간이 desc에 포함
2. **LLM 전문(preamble)** (2건): "검토한 결과..." 메타 응답이 그대로 저장
3. **깨진 bold 패턴** (1건): `**: .` 의미 없는 문장
4. **숨겨진 공백** (247건): `"다 ."` → `"다."` 정규화

### 해결
`topics.json` 원본 데이터 정리 + `summary-embeddings.json` 재생성.

**교훈**: LLM으로 큐레이션 데이터 생성 시, 저장 전 후처리(separator 이후 잘라내기, 메타 텍스트 제거)가 필수.

---

## 12. 핀포인트 문서 ID 파싱 — decision_trees 참조 패턴

### 문제
`decision_trees.py`의 `4_precedents`/`5_red_flags`에 큐레이팅된 문서 참조(207건)가 요약 문자열로만 LLM에 전달되고, 원문 전문은 주입되지 않음. 리트리버(벡터 유사도)에만 의존하면 커버리지 40% 수준.

### 해결: `retriever.py`의 `_parse_doc_ids_from_text()` + `fetch_pinpoint_docs()`

**파싱 난이도 높은 패턴들:**

| 패턴 | 예시 | 처리 |
|------|------|------|
| IE + 콤마 구분 숫자 | `[IE 사례 20, 21]` | IE 전용 분기에서 숫자만 추출 |
| IE + QNA 혼합 | `[IE 사례 5-A, QNA-SSI-38672]` | named_ref 먼저 추출 후 제거, 나머지에서 IE 번호 |
| FSS 콤마 접두어 복원 | `[FSS-CASE-2024-2409-01, 2025-2512-01]` | current_prefix 추적 |
| QNA 콤마 접두어 | `[QNA-SSI-36991, 36990]` | QNA 중간 패턴 다양해서 복원 불가 → 첫 ID만 처리 |
| 5자리+ 숫자 필터 | IE 문맥의 `38672` | QNA ID 잔재이므로 5자리 이상 스킵 |
| "연계" 접미사 | `[FSS-CASE-2024-2505-04 연계]` | regex로 제거 |
| 한글 접미사 | `[IE 사례 35-경우A]` | 사례 번호 `35`만 추출 |

### 메타데이터 중첩 (debugging.md #7 연계)
parent 컬렉션의 `title`, `hierarchy`는 `metadata` dict 안에 중첩. FSS 감리사례는 `title` 키 자체가 없을 수 있음.
→ `doc.get("metadata", {}).get("title", "")` 패턴으로 방어적 접근.

**교훈**: 큐레이션 데이터의 참조 패턴은 사람이 쓴 텍스트라 일관성이 없음. 파서는 모든 에지 케이스를 커버해야 하며, `_parse_doc_ids_from_text()` 단위 테스트로 전수 검증 필수.

---

## 13. user msg에 CoT prefix 추가 시 non-reasoning 모델 산술 정확도 하락

### 문제

gpt-4.1-mini(calc) 경로에서 `_COT_PREFIX`(207자, 포맷 지시)를 user message 앞에 prepend하면 진행률 계산 정답률이 급락:
- `_COT_PREFIX` **있음**: 평균 0.67, 진행률 정답 1/3
- `_COT_PREFIX` **없음**: 평균 0.83, 진행률 정답 3/3

### 근본 원인

`_COT_PREFIX`의 포맷 지시(`**[결론]**` 섹션 필수, `**(문단 XX)**` 형식 필수)가 시스템 프롬프트(`CALC_CLARIFY_SYSTEM`)에 이미 동일한 내용으로 포함됨. **중복 지시**가 gpt-4.1-mini의 attention을 산술 로직에서 포맷 규칙으로 분산.

### 해결

`_COT_PREFIX` 완전 제거. 시스템 프롬프트만으로 포맷 유도 충분.

### 추가 조치

calc 경로에서 `topic_knowledge`(~2000자, 계산과 무관한 토픽 개념 설명)도 조건부 스킵 → 추가 +0.03 효과.

**교훈**: non-reasoning 모델에 system prompt와 user msg에 동일한 포맷 지시를 중복 주입하면 오히려 핵심 태스크(산술) 정확도가 하락한다. 포맷 지시는 system prompt에 1회만 명시하고, user msg는 태스크 데이터(질문+컨텍스트)에 집중시킬 것.

---

## 14. 문단 참조 괄호 suffix 뒤 줄바꿈 잔류 — text.py 정규식 누락

### 문제

본문/적용지침 카드에서 "문단 35(2)" 뒤에 불필요한 빈 줄이 표시됨. 예: `[문단 B5]` 카드 내 "문단 35(2)\n에 따라..."가 줄바꿈으로 렌더링.

### 근본 원인

`app/ui/text.py:233-237`의 교차참조 분리 복원 정규식:
```python
r"(문단\s*[A-Za-z0-9~～]+)\n([의에이가을를은는로으로와과도만부터까지])"
```
`[A-Za-z0-9~～]+`는 "문단 35"까지만 매칭하고 `(2)` 괄호를 포함하지 않음. 같은 파일의 라인 149-152에는 이미 `(?:\([0-9가-힣]+\))?`가 적용되어 있었으나, 이 정규식에는 누락.

### 해결

괄호 suffix 옵셔널 그룹 추가:
```python
r"(문단\s*[A-Za-z0-9~～]+(?:\([0-9가-힣]+\))?)\n([의에이가을를은는로으로와과도만부터까지])"
```

**교훈**: 동일 파일 내 유사 정규식이 여러 곳에 있으면, 한쪽을 수정할 때 나머지도 동일 패턴이 적용되었는지 반드시 확인할 것. 특히 크롤링 원본에 "문단 XX(N)" 형태의 세부항 참조가 빈번하므로 괄호 suffix는 항상 고려 대상.

---

## 15. Cohere Reranker가 큐레이션(pinpoint) 문서를 탈락시키는 문제

### 문제

`MASTER_DECISION_TREES`의 precedents/red_flags에서 핀포인트 fetch한 문서(QNA, 감리사례, IE 원문)가 Cohere reranker에서 `rerank_threshold`(0.05) 미만으로 대량 탈락. T3 테스트에서 105건 중 103건 탈락 확인.

### 근본 원인

Cohere `rerank-multilingual-v3.0`의 텍스트 유사도 채점은 **query-document 의미 유사도** 기반. 큐레이션 문서는 사용자 질문과 직접적 의미 유사도가 낮지만 **도메인 전문가가 관련성을 사전 판단**한 것.

### 해결

`rerank.py`에서 pinpoint 문서를 **reranker bypass** 처리:
```python
pinpoint = [d for d in retrieved_docs if d.get("chunk_type") == "pinpoint"]
non_pinpoint = [d for d in retrieved_docs if d.get("chunk_type") != "pinpoint"]
# non-pinpoint만 reranker 채점, pinpoint는 1순위 고정
combined = pinpoint + reranked
```

**교훈**: Reranker(Cross-encoder)는 텍스트 유사도 기반이므로, 도메인 전문가가 큐레이션한 문서까지 유사도 필터에 통과시키면 안 됨. 큐레이션 데이터는 별도 경로(bypass)로 처리.

---

## 16. 감리사례 매칭 — 문단 번호 기반 → 서머리 임베딩 기반 전환

### 문제

기존 `format.py`가 LLM 답변에서 문단 번호를 추출(`_PARAGRAPH_RE`) → child 컬렉션에서 `related_paragraphs` 매칭 → 코사인 유사도 순위 방식. 범용 문단(9, 12, 22 등)이 자주 매칭되어 노이즈 발생, `GENERIC_PARAGRAPHS` 블랙리스트로 땜질.

### 해결

`summary_matcher.py` 도입: `summary-embeddings.json`에 사전 임베딩된 QNA/감리/IE 서머리와 사용자 질문의 코사인 유사도로 직접 매칭. 문단 번호 추출/블랙리스트 불필요.

**교훈**: 문단 번호 매칭은 간접적(문단→문서→유사도)이라 노이즈에 취약. 서머리 설명을 사전 임베딩하고 query와 직접 비교하는 것이 더 안정적.

---

## 17. 여는 괄호 직후 줄바꿈 잔류 — clean_text step 4 누락 패턴 (舊 #16)

### 문제

문단 32 카드에서 "수행의무를 (\n문단 35~37에 따라)" — 여는 괄호 `(` 직후에 불필요한 줄바꿈이 표시됨.

### 근본 원인

`app/ui/text.py` step 4(기존)의 정규식이 `(content\n문단...\n)` 패턴(괄호 안 양쪽 줄바꿈)만 처리. `(\n문단...)` 패턴(여는 괄호 직후 줄바꿈)은 미처리.

크롤링 시 `soup.get_text(separator="\n")`가 `<a>` 등 인라인 태그 경계에서 줄바꿈을 삽입하여 발생.

### 해결

step 4a 추가 — 여는 괄호 직후 줄바꿈을 범용적으로 제거:
```python
text = re.sub(r"\(\s*\n+\s*(문단)", r"(\1", text)
```

**교훈**: 크롤링 아티팩트 줄바꿈은 특정 위치(문단 참조 앞/뒤/괄호 안)에 다양한 패턴으로 나타남. 개별 케이스를 땜질하기보다, `(\n문단` 같은 구조적 패턴 단위로 범용 규칙을 추가할 것. #14와 동일 파일, 동일 근본 원인(크롤링 줄바꿈 파편화).

---

## 18. evidence.py `sources` 변수 버그 — for 루프 잔류 변수 참조

### 문제

`_render_evidence_panel()` 내부에서 IE 그룹/PDR 그룹 렌더링 후 `_render_supp_extra(sources, ...)` 호출 시, `sources` 변수가 내부 for 루프(`for group_name, sources in ACCORDION_GROUPS.items()`)의 **마지막 할당값**을 참조. IE/PDR 그룹이 `ACCORDION_GROUPS`의 마지막 항목이 아닌 경우 잘못된 소스 목록이 전달됨.

### 근본 원인

Python의 for 루프 변수는 루프 종료 후에도 스코프에 남음. `for ... in ACCORDION_GROUPS.items()` → `break` 후에도 `sources`는 마지막으로 매칭된 항목의 값을 유지. 이후 다른 조건문에서 `sources`를 암묵적으로 사용하면 의도하지 않은 그룹의 소스 목록이 전달됨.

### 해결

`_render_supp_extra(ACCORDION_GROUPS.get(group_name, []), ...)` — 명시적으로 현재 그룹명으로 조회.

**교훈**: Python for 루프 변수는 루프 밖에서도 살아있으므로, 중첩된 조건 분기에서 루프 변수를 재사용하면 stale reference 버그가 발생함. 특히 `break`로 일찍 탈출한 경우 어느 시점의 값인지 추적이 어려움. 명시적 dict 조회가 안전함.

---

## 19. Cohere 클라이언트 매 요청 재생성 — HTTP 커넥션 풀 낭비

### 문제

`reranker.py`의 `rerank_results()` 함수 내부에서 `co = cohere.ClientV2(api_key=...)` 를 매 호출마다 실행. `/chat` 요청 시 매번 새 HTTP 클라이언트 + 커넥션 풀 초기화 비용 발생.

### 해결

모듈 레벨 싱글턴 패턴 적용:
```python
_cohere_client: cohere.ClientV2 | None = None

def _get_cohere_client() -> cohere.ClientV2:
    global _cohere_client
    if _cohere_client is None:
        _cohere_client = cohere.ClientV2(api_key=settings.cohere_api_key)
    return _cohere_client
```

**교훈**: API 클라이언트(HTTP 기반)는 함수 내부에서 매번 생성하지 말고, 모듈 레벨 싱글턴 또는 팩토리 패턴으로 커넥션 풀을 재사용할 것. 특히 Cohere, OpenAI, httpx 등 TCP 커넥션을 관리하는 클라이언트는 재생성 비용이 큼.

---

## 20. `logging.basicConfig`을 config.py에 두면 import 부작용 발생

### 문제

`config.py`(pydantic-settings 설정 파일)에 `logging.basicConfig()`을 배치하면, 이 파일을 import하는 **모든 모듈**에서 전역 로깅 설정이 강제 적용됨. 단위 테스트 시 로깅 설정 격리 불가, 전처리 스크립트에서 의도하지 않은 포맷 적용.

### 근본 원인

`config.py`는 **설정값 제공** 역할인데, 모듈 레벨에서 `logging.basicConfig()`을 호출하면 **부작용(side effect)**이 import 시점에 발생. Python의 import는 모듈 레벨 코드를 즉시 실행하므로, 설정 파일에 부작용 코드를 두면 import 순서에 따라 동작이 달라질 수 있음.

### 해결

`logging.basicConfig()`을 `main.py`(FastAPI 진입점)로 이동. 설정 파일은 순수 데이터 선언만 유지.

**교훈**: 설정 파일(`config.py`, `settings.py`)에는 값 선언만 두고, 전역 상태를 변경하는 코드(`logging.basicConfig`, DB 커넥션 초기화 등)는 애플리케이션 진입점(`main.py`, `streamlit_app.py`)에 배치할 것.

---

## 21. 페이지 전환 깜빡임(flicker) — CSS 셀렉터 방향 오류 + regex escape 버그

### 문제

홈→토픽 전환 시 이전 홈 콘텐츠(30개 버튼)가 0.3~0.5초간 노출. CSS `[data-stale="true"] .block-container { opacity: 0 }` 규칙이 전혀 매칭되지 않음.

### 근본 원인 (Playwright DOM 검사로 확인)

1. **CSS 셀렉터 방향이 반대**: Streamlit의 `data-stale="true"`는 `.block-container`의 **자식**인 `.element-container`(개별 위젯 컨테이너)에 설정됨. `[data-stale] .block-container`는 "data-stale을 가진 **조상**의 자손 block-container"를 의미하므로 **절대 매칭 불가**.
2. **regex escape 버그**: `text.py:301`의 `r"\1\x00"` — raw string에서 `\x00`은 리터럴 4문자(`\`, `x`, `0`, `0`)이며, `re.sub` 교체 문자열에서 `\x`는 유효한 escape가 아님 → `re.error: bad escape \x` → QNA 탭 렌더링 실패 → 페이지 전환 지연 가중

### 해결

1. **CSS**: `.element-container[data-stale="true"] { display: none !important }` — stale 위젯 자체를 직접 숨김
2. **regex**: `r"\1\x00"` → `lambda m: m.group(1) + "\x00"` — 교체 문자열을 함수로 변경하여 실제 null byte 사용

### 검증 방법

Playwright CLI로 DOM 검사:
```bash
npx @playwright/cli eval "document.querySelector('[data-stale]').className"
# → "stElementContainer element-container ..."  (block-container의 자식)

npx @playwright/cli eval "document.querySelector('.block-container').getAttribute('data-stale')"
# → null  (block-container 자체에는 data-stale 없음)
```

**교훈**: Streamlit 내부 DOM 구조를 추측하지 말고, Playwright/DevTools로 실제 속성 위치를 확인할 것. CSS `A B` 셀렉터는 "A의 자손 B"이므로, 속성이 자식에 있는데 부모를 타겟하면 매칭 불가. 또한 Python raw string의 `\x`는 regex replacement에서 유효하지 않으므로 lambda를 사용할 것.

---

## 22. 외부 테이블/분개 문단 가독성 깨짐 — `data-file-name` .htm 미처리

### 문제

IE 적용사례 중 ~29개 문단에 `data-file-name` 속성으로 외부 `.htm` 파일(테이블/분개)이 참조됨. 03-chunk 단계에서 이 외부 HTML을 크롤링하지 않아 "Evernote Export" 메타텍스트 + 깨진 한 줄 텍스트로 표시.

### 근본 원인

1. **전처리 누락**: `03-chunk-with-weight.py`가 `data-file-name` 속성을 무시하고 `fullContent` 그대로 사용
2. **`_ensure_paragraph_breaks()`가 테이블 행 분리**: 단일 `\n`→`\n\n` 변환이 마크다운 테이블 행 사이에도 적용되어 테이블 렌더링 깨짐
3. **마크다운 테이블 헤더 볼드**: `<th>` 없는 데이터 전용 테이블에서 첫 행이 헤더(볼드)로 처리됨

### 해결

1. `app/preprocessing/11-fix-external-tables.py` 실행: 외부 .htm 크롤링→`paraContent`에 `<table>` 주입→마크다운 테이블 변환→MongoDB `text` 필드 갱신 (29건)
2. `app/ui/text.py:_ensure_paragraph_breaks()`: 테이블 행(`|`로 시작하는 줄) 사이 `\n`을 보호 마커로 치환 후 복원
3. `11-fix-external-tables.py:clean_html_to_md()`: `<th>` 없는 테이블에 빈 헤더 행 삽입하여 데이터 행 볼드 방지

**교훈**: 크롤링 데이터에 외부 파일 참조가 있으면 전처리 단계에서 반드시 크롤링·주입해야 함. 후처리(UI)에서 깨진 데이터를 정규식으로 복원하는 것은 불가능. 또한 마크다운 테이블은 `\n`(단일)으로 행이 연결되어야 하므로, `\n→\n\n` 변환 시 테이블 행을 보호해야 함.

---

## 24. topics.json 파이프라인 덮어쓰기 사고 — 토픽 분할 누락

### 문제

UI에서 "행사하지 않은 권리(낙전수익/상품권)" 클릭 시 "큐레이션 데이터가 아직 준비되지 않았습니다" 에러. 이전 세션에서 `git checkout -- topics.json`으로 HEAD 복원 후 `_add_topics.py` 실행을 빠뜨림.

### 근본 원인

`topics.json`은 2단계 파이프라인으로 관리됨:

```
10-parse-curation.py → 24개 합산 토픽 (통제 이전의 특수 형태, 고객의 권리 관련)
     ↓
_add_topics.py → 30개 개별 토픽 (재매입약정, 위탁약정, ..., 행사하지 않은 권리, ...)
```

HEAD의 topics.json은 24개 합산 토픽 상태(10-parse 직후). UI(`constants.py`)와 `decision_trees.py`는 개별 토픽명("행사하지 않은 권리")으로 참조하므로, `_resolve_topic_key()`가 키를 찾지 못함.

### 해결

1. `_add_topics.py` 실행 → 30개 토픽 복원
2. 미매칭 문단 21개 + IE 사례 14개 재추가 (이전 세션 작업 복구)
3. cross_links 20건 수정 (토픽명 변경/분할로 인한 stale 참조)

### 추가 발견: cross_links 불일치 20건

| 유형 | 예시 | 수정 |
|------|------|------|
| 토픽명 미세 변형 | "기간에 걸쳐 이행 vs 한 시점 이행" | → "기간에 걸쳐 vs 한 시점 인식" |
| 분할 전 합산명 | "고객의 권리 관련" | → 개별 토픽명으로 교체 |
| 존재하지 않는 키 | "거래가격의 후속변동" | → "거래가격의 후속 변동" (띄어쓰기) |

### 검증

```python
# 모든 cross_links가 실제 토픽 키에 존재하는지 검증
all_keys = set(topics.keys())
for k, v in topics.items():
    for link in v.get("cross_links", []):
        assert link in all_keys, f"{k}: invalid cross_link '{link}'"
```

**교훈**: 파이프라인 중간 산출물(topics.json)을 git checkout이나 10-parse 재실행으로 복원할 때, 반드시 후속 스크립트(_add_topics.py)도 실행해야 함. topics.json의 정합성은 (1) 토픽 키 ↔ UI 표시명, (2) cross_links ↔ 실제 키, (3) decision_trees 토픽명 ↔ 실제 키 3가지 축으로 검증 필요.

---

## 23. 품질 테스트 Partial 4건 구조적 개선 (2026-03-14)

### 문제

26개 품질 테스트 × 3회 결과 Pass 22/26 (84.6%), Partial 4/26 — 4가지 구조적 문제:
1. **SECTION-8**: API timeout 시 에러로 종료 (PydanticAI `retries`는 validation 전용)
2. **TEST-0**: 양방향 분기(본인/대리인 등)에서 핵심 판단 요소 미확인인데 TYPE 2 확정 결론
3. **SECTION-7**: 진행률 측정 체크리스트에 "유의적 관여 여부" 선행 판단 누락
4. **TEST-2**: 정보 충분한 질문에서도 불필요 꼬리질문 생성 (analyze→clarify 간 정보 단절)

### 해결

1. **retry 래퍼** (`pipeline.py`): `_retry_node()` — httpx.Timeout/HTTPStatus/ConnectionError에 지수 백오프 재시도 (max 2회)
2. **양방향 분기 안전장치** (`decision_trees.py` + `agents.py`):
   - 4개 토픽에 `7_critical_factors` 필드 추가 (본인vs대리인, 라이선싱, 기간에걸쳐vs한시점, 일련의구별)
   - `_inject_clarify_system()`에 critical_factors 미확인 시 TYPE 1 강제 가이드 주입
   - `_validate_clarify()`에서 TYPE 2 + 미확인 factor → `ModelRetry`
3. **체크리스트 선행 판단** (`decision_trees.py`): 진행률 측정의 `2_checklist` 첫 항목으로 "유의적 관여 여부" 추가
4. **provided_info 전달** (`agents.py` + `prompts.py` + `analyze.py` + `generate.py`):
   - `AnalyzeResult.provided_info` 필드 추가 → ANALYZE_PROMPT에 추출 지시
   - `ClarifyDeps.provided_info` 추가 → `_inject_clarify_system()`에서 "이미 확인된 정보" 섹션 주입

**교훈**: LLM 품질 문제는 프롬프트 땜질보다 **데이터 구조(critical_factors) + 정보 흐름(provided_info) + 검증 로직(validator)**의 3계층으로 접근해야 구조적으로 해결됨.

---

## 25. title 없는 문단의 expander/캡션 표시 — content 첫 문장 폴백

### 문제

토픽 브라우즈에서 경과규정(C1~C10, C7A, C8A) 및 용어정의(한5, 한7) 문단이 "문단 C5"처럼 번호만 표시됨. 기준서 본문 18개 문단의 MongoDB `title` 필드가 빈 문자열(`""`)이라서 발생.

### 영향 범위

DB 전체 72건 title 빈값:
- **기준서 본문 18건**: 한5, 한7, C1~C10, C1A~C1C, 한C1.1, C7A, C8A (UI에 직접 표시)
- **감리사례 child chunks 54건**: FSS-CASE-*, KICPA-CASE-* (parent doc으로 렌더링하므로 `_build_pdr_label()`이 처리 → UI 영향 없음)

### 해결

`topic_tabs.py` 2곳에서 title 없을 때 content 첫 문장(80자)을 폴백 표시:

1. **`_render_para_expander()`** (expander 제목): title 없으면 `[문단 C5] 이 기준서를 문단 C3(1)에 따라...` 형태
2. **`_render_preview_captions()`** (접힌 상태 미리보기): 동일 로직 적용 — `doc.get("title", f"문단 {p}")` → content 첫 줄 추출

### 공통 패턴

```python
title = doc.get("title") or ""
if not title:
    raw = _strip_context_prefix(content, para_num)
    first_sent = raw.split("\n")[0].strip()[:80]
    title = f"[문단 {para_num}] {first_sent}" if first_sent else f"문단 {para_num}"
```

**교훈**: MongoDB 문서의 `title` 필드가 빈 문자열인 경우 `doc.get("title", fallback)`은 빈 문자열을 반환(기본값 미적용). `doc.get("title") or ""` + falsy 체크가 안전. 또한 동일한 데이터(title)를 표시하는 곳이 여러 군데(expander, preview caption)면 모든 곳에 동일한 폴백 로직을 적용해야 함.

---

## 26. cross_links 토픽명 불일치 — topics.json 데이터 일괄 수정

### 문제

토픽 브라우즈에서 관련 토픽 칩(pills) 클릭 시 "큐레이션 데이터가 아직 준비되지 않았습니다" 에러. 예: "고객의 선택권" 페이지에서 "수행의무의 식별" 클릭 → 매칭 실패.

### 근본 원인

`topics.json`의 `cross_links` 배열값이 실제 토픽 키와 불일치 (34건). 수동 입력 과정에서 발생한 오타/표현 차이:

| 유형 | 깨진 값 | 실제 키 | 건수 |
|------|---------|---------|------|
| 띄어쓰기 | "변동 대가" | "변동대가" | 8 |
| 조사 차이 | "수행의무의 식별" | "수행의무 식별" | 4 |
| 표현 차이 | "본인 대 대리인 판단" | "본인 vs 대리인" | 4 |
| 키명 불일치 | "기간에 걸쳐 이행 vs 한 시점 이행" | "기간에 걸쳐 vs 한 시점 인식" | 5 |
| 약칭 차이 | "거래가격 배분 원칙" | "거래가격 배분" | 4 |
| 조사 변형 | "고객이 행사하지 아니한/않은 권리" | "행사하지 않은 권리" | 3 |
| 미존재 토픽 | "상각과 손상", "수취채권 vs 계약자산 vs 계약부채" | (없음) | 3 |

### 해결

Python 스크립트로 `topics.json`의 cross_links를 일괄 수정:
- 매핑 가능한 31건 → 실제 키로 교체 (자기 참조/중복 방지 포함)
- 매핑 불가능한 3건 → 제거 (해당 토픽이 아직 존재하지 않음)
- 수정 후 전수 검증: `all cross_links in data.keys()` 통과

### 검증

```python
for k, v in data.items():
    for link in v.get("cross_links", []):
        assert link in data, f"{k}: invalid '{link}'"
```

**교훈**: 큐레이션 데이터의 cross-reference는 수동 입력이라 오타·표현 불일치가 불가피. 데이터 추가/변경 시 `assert link in data.keys()` 검증을 파이프라인에 포함하여 불일치를 사전 차단할 것. #2, #24와 동일 근본 원인(데이터 정합성은 데이터에서 해결).

---

## 26. 라우팅/계산/멀티턴 품질 개선 2차 (2026-03-14)

### 문제

10케이스×3회 품질 테스트에서 Partial 5건 식별:
- B1/B2: calc 라우팅 1/3만 성공 → Gemini가 계산 시 미설치 자재 미반영(90억 vs 85억)
- C2: T2에서 접근권 결론 후 T3에서 불필요 추가 질문(로열티/MG) 생성
- C3: "증분차입이자율"(1116호)이 1115호 "금융요소"로 오매칭

### 해결

**Fix 1 (B1/B2)**: calc 라우팅을 regex → LLM 판단으로 전환
- 삭제: `_needs_calculation()`, `_CALC_COMMAND`, `_AMOUNT_PATTERN` (regex 전체 제거)
- 추가: `AnalyzeResult.needs_calculation: bool` → analyze_agent가 LLM으로 판단
- 검증: 14개 테스트케이스 × 3회 = 42/42 정확도 100%, 일관성 100%
- Why: regex heuristic은 토픽 매칭 비결정성 + 패턴 누락으로 B1/B2에서 1/3만 성공.
  LLM은 "산정하면 어떤 원칙?"(판단) vs "산정해주세요"(계산)를 의미적으로 완벽 구분

**Fix 2 (C2)**: 결론 후 추가 질문 금지 (`chat_service.py`, `agents.py`)
- `checklist_state`에 `concluded: bool` 플래그 추가
- `is_conclusion=True` 시 concluded=True로 설정, 후속 턴에서 유지
- `_inject_clarify_system()`에서 concluded=True면 [결론 확인 모드] 주입
- "추가 질문 없이 TYPE 2 확정 결론만 제시하세요" 강제 지시

**Fix 3 (C3)**: 범위 밖 키워드 가드 (`prompts.py`)
- ANALYZE_PROMPT [라우팅] 섹션에 타 기준서 전용 개념 명시적 열거
- 1116호(증분차입이자율, 사용권자산), 1109호(기대신용손실, SPPI), 1037호(충당부채)
- 단, 1115호 교차 개념(금융요소, 유의적 금융요소)은 "IN" 유지

**교훈**: (1) LLM 토픽 매칭에 의존하는 routing 조건은 비결정적 → 확정적 조건(regex+패턴)만으로 충분한지 검증 후 제거. (2) 멀티턴에서 결론 상태를 추적하지 않으면 LLM이 무한 질문 루프에 빠짐 → 세션 상태에 concluded 플래그 필수. (3) 기준서 간 유사 용어(증분차입이자율 ↔ 금융요소)는 명시적 negative list로 방어.

---

## 27. KAI 교육자료 evidence 패널 — catch-all 그룹 오분류

### 문제

evidence 패널에서 본문 문서(문단 46, hierarchy "본문 > 측정")가 "📖 한국회계기준원 교육자료" 그룹에 잘못 표시됨. 실제 KAI 교육자료(`EDU-KASB-xxx`)는 QNA/감리사례처럼 parent 전문을 카드로 보여야 하는데, 범용 본문 렌더러(`_render_document_expander`)로 처리되어 마크다운 구조(## 헤딩, **볼드** 섹션) 소실.

### 근본 원인

1. `constants.py`의 `ACCORDION_GROUPS`에 "교육자료" source 미등록
2. `evidence.py`에서 ACCORDION_GROUPS 매칭 실패 시 하드코딩된 catch-all 그룹("📖 한국회계기준원 교육자료")으로 전부 빠짐
3. KAI 전용 렌더러 없음 — QNA/감리사례는 `_render_pdr_group` → `_render_pdr_expander` 경로인데, KAI는 `_render_default_group` → `_render_document_expander` 경로

### 해결

1. `constants.py`: `ACCORDION_GROUPS`에 `"📖 한국회계기준원 교육자료": ["교육자료"]` 추가
2. `evidence.py`: `_PDR_GROUPS`에 교육자료 그룹 추가 → QNA/감리와 동일한 `_render_pdr_group` → `_render_pdr_expander` 경로
3. `evidence.py`: catch-all 그룹 제거 → ACCORDION_GROUPS 기반 정상 분류만 수행
4. `evidence.py`: AI 답변 인용 감지에 `EDU-[\w-]+` 패턴 추가 + `_SUPPLEMENTABLE`에 "교육자료" 추가

**교훈**: 새로운 문서 유형(source)을 추가할 때는 반드시 (1) `ACCORDION_GROUPS` 등록, (2) 전용 또는 기존 렌더러 경로 지정, (3) ai_answer 인용 감지 패턴 추가의 3가지를 동시에 처리해야 함. catch-all 패턴은 디버깅을 어렵게 하므로 지양.

---

## 28. bare 문서 ID(QNA/EDU/감리) 파란색 강조 누락 — text.py step 3.5

### 문제

AI 답변에서 문단 참조(`문단 37`)는 파란색 볼드로 표시되지만, 같은 괄호 안의 `EDU-KASB-180426`이나 `QNA-2017-I-KAQ015`는 강조되지 않음.

### 근본 원인

`text.py` step 3.5의 정규식이 **대괄호 `[...]`로 감싼 패턴만** 매칭:
```python
r"\[((?:FSS-CASE|KICPA-CASE|QNA)-[\w-]+)\]"
```
1. AI 답변은 `(문단 38, EDU-KASB-180426)` 형태로 bare ID를 사용 — 대괄호 아님
2. `EDU-` 접두사가 정규식에 누락

### 해결

1. 기존 대괄호 패턴에 `EDU` 접두사 추가
2. bare ID 패턴 추가 — 대괄호 없이 나오는 ID도 파란색 볼드 처리:
```python
# bare ID: QNA-xxx, EDU-KASB-xxx, FSS-CASE-xxx 등
text = re.sub(
    r"(?<![\w>])((?:FSS-CASE|KICPA-CASE|QNA|EDU)-[\w-]+)",
    r'<span style="color:#1f77b4;font-weight:600;">\1</span>',
    text,
)
```

**교훈**: 문서 ID 강조 정규식을 추가할 때, AI가 실제 답변에서 해당 ID를 어떤 형식(대괄호, 괄호, bare)으로 출력하는지 확인해야 함. 프롬프트에서 `[QNA-xxx]` 형식을 지시해도 LLM이 항상 따르지 않으므로, bare 패턴도 함께 처리하는 것이 안전. 또한 새로운 문서 유형(EDU) 추가 시 #27과 동일하게 강조 정규식에도 접두사를 추가해야 함.

---

## 29. AI 답변 인용 문단 하이라이트 — expander 라벨에서 인용 여부 시각적 구별

### 문제

ai_answer 페이지 좌측 근거 패널에서 섹션 expander 라벨(예: "변동대가 추정치를 제약함 [문단 56, 문단 57, 문단 58]")의 모든 문단이 동일한 스타일이라, AI가 실제로 어떤 문단을 인용했는지 구별 불가.

### 해결

`_get_cited_ids()` 헬퍼를 `evidence.py`에 추가하여 AI 답변에서 3종류 ID를 통합 추출:
- 문단: `_extract_para_refs` → `_para_ref_to_num` → `_expand_para_range` → `{"56", "B35"}`
- QNA: `re.findall(r"QNA-[\w-]+")` → `{"QNA-2019-001"}`
- 감리/교육: `re.findall(r"(FSS-CASE-[\w-]+|KICPA-CASE-[\w-]+|EDU-[\w-]+)")` → set

`cited_ids` set을 `evidence.py` → `grouping.py` → `doc_renderers.py`로 전파:
- `_build_para_label()`: 인용된 문단만 `:blue[**문단 XX**]`
- `_make_label()`: 인용된 문단 expander 라벨 `:blue[**문단 XX - 제목**]`
- `_render_pdr_expander()`: 인용된 ID `:blue[**[QNA-xxx]**]`

`page_state == "ai_answer"`일 때만 `cited_ids` 계산 (1/2단계 무영향, `cited_ids=None`).

**교훈**: Streamlit의 `:blue[**text**]` 마크다운 문법은 expander 라벨 안에서도 동작하여 별도 CSS 없이 인라인 강조 가능. 상위 함수에서 계산한 데이터를 `Optional` 파라미터로 하위 렌더러 전체에 전파할 때는, 기본값 `None`으로 하위 호환을 유지하면서 점진적으로 적용 가능.

---

## 30. `_fill_missing_docs` 섹션 매칭 실패 — hierarchy 소소제목 ≠ topics.json title

### 문제

"지급청구권" 섹션에 topics.json 등록 문단이 B9~B13 (5건)인데, expander에 B9, B11, B12만 표시 (B10, B13 누락). `_fill_missing_docs()`의 보충 로직이 동작하지 않음.

### 근본 원인

`_extract_topic_key()`가 hierarchy에서 추출한 소소제목 `"지금까지 수행을 완료한 부분에 대한 지급청구권"`과 topics.json의 section title `"지급청구권 (문단 B9~B13)"`이 **완전히 다른 문자열**.

`_fill_missing_docs(sec_title)` → `_get_section_paras(sec_title)` → `sec.get("title") == sec_title` 정확 매칭 → **실패**.

hierarchy에서 minor가 있는 문서는 `_regroup_by_section`을 거치지 않고 `sub_groups`에 직접 들어가므로, `get_section_for_para()`로 정확한 topics.json title을 얻을 기회가 없었음.

### 해결

`_fill_missing_docs()` 내부에서 `_get_section_paras(sec_title)` 실패 시, 첫 문서의 문단번호로 `get_section_for_para(para)`를 호출하여 topics.json의 canonical title을 얻은 뒤 재시도:

```python
all_paras = _get_section_paras(sec_title)
if not all_paras:
    for _, doc in items:
        para = _get_doc_para_num(doc)
        if para:
            canonical_title, _ = get_section_for_para(para)
            if canonical_title:
                all_paras = _get_section_paras(canonical_title)
                break
```

### 부분 매칭 시도 → 실패 이유

`_clean_title()` 후 부분 포함 매칭(`"지급청구권" in "지금까지...지급청구권"`)을 시도했으나, **동일 키워드 섹션이 2개** 존재:
- 본문 문단 37: `"지급청구권 (문단 37)"`
- 적용지침 B9~B13: `"지급청구권 (문단 B9~B13)"`

부분 매칭은 문단 37에 먼저 매칭되어 **오매칭** 발생. 문단번호 기반 정확 조회가 유일한 안전 경로.

**교훈**: hierarchy 경로와 topics.json title은 같은 개념을 가리키지만 문자열이 다를 수 있음. 문자열 비교(정확/부분)보다 **문단번호를 키로 한 역인덱스 조회**가 확실. 특히 동일 키워드("지급청구권")가 다른 섹션(본문 vs 적용지침)에 존재할 때 부분 매칭은 오매칭 위험.

---

## 31. 검색 폼 제출 시 페이지 최상단으로 스크롤 — `st.form` + `@st.fragment` 조합 무효

### 문제

홈 페이지 하단의 "직접 질문하기" 폼에서 "검색하기" 클릭 시 페이지가 최상단으로 스크롤. `st.status()` 진행 표시(15%, 30%...)가 화면 밖(하단)으로 밀려나 사용자에게 보이지 않음.

### 1차 시도 (실패)

`@st.fragment`로 `st.form`을 감쌌으나 **스크롤 초기화 여전히 발생**.

### 근본 원인

Streamlit 공식 문서: **`st.form` 제출은 fragment 안에서도 항상 전체 앱 rerun을 유발**. `@st.fragment`는 일반 위젯 인터랙션에만 부분 rerun을 적용하고, `st.form_submit_button` 클릭은 예외적으로 전체 rerun을 강제함.

### 해결 (2차)

`st.form` 제거 → `@st.fragment` 안에서 일반 `st.text_area` + `st.button` 사용:

```python
@st.fragment
def _home_search_fragment():
    query = st.text_area(..., key="home_search_input")
    if st.button("검색하기", key="home_search_btn"):
        if query and query.strip():
            _call_chat(query.strip(), use_cache=False)

_home_search_fragment()
```

일반 `st.button` 클릭 → fragment rerun만 발생 → 스크롤 위치 유지.
fragment 내 `st.rerun()` (페이지 전환 시) → 전체 rerun → 새 페이지 상단 표시 (정상).

적용 파일: `pages.py` (홈, 근거, AI답변), `topic_browse.py` (토픽)

**교훈**: `@st.fragment` + `st.form`은 스크롤 유지에 무효. `st.form_submit_button`은 항상 전체 rerun. fragment 내 스크롤 유지가 필요하면 반드시 일반 위젯(`st.button`)을 사용할 것.

---

## 32. IE 적용사례 pinpoint — 문단 개별 반환 → 사례 단위 병합

### 문제

IE 사례 1건(예: 사례 48)이 여러 문단(IE48, IE48A, IE48B, IE48C)으로 분리되어 pinpoint에 개별 doc으로 반환. "본인 vs 대리인" 질문에서 47개 문단이 `GENERATE_DOC_LIMIT` 슬롯을 과다 점유.

### 근본 원인

`_fetch_ie_case_chunks()`가 사례 번호로 매칭되는 모든 문단을 개별 dict로 반환. IE 사례는 parent 컬렉션이 없어 QNA처럼 PDR 패턴을 쓸 수 없고, 사례↔문단 그룹핑 로직이 없었음.

### 해결

`_fetch_ie_case_chunks()`에서 같은 사례 번호의 문단들을 하나의 doc으로 병합:
- chunk_id 순 정렬 후 `text`를 `\n\n`으로 결합
- 병합 doc의 chunk_id: `1115-IE-case-{사례번호}`
- `_merged_chunk_ids`에 원본 ID 보존 (테스트 매칭용)

결과: 47개 문단 → 8개 사례

**교훈**: 리트리버/pinpoint가 반환하는 문서의 **단위(granularity)**가 LLM 컨텍스트 효율에 직접 영향. parent 컬렉션이 없는 데이터(IE 사례)도 사례 단위 그룹핑을 적용하여 1사례=1doc으로 통합해야 함.

---

## 33. 핀포인트 파싱 — 소괄호 참조 + 축약 ID + critical_factors 3중 Gap

### 문제

decision_trees.py의 section 2(checklist), section 7(critical_factors)에 있는 참조가 pinpoint fetch에서 누락. section 4/5는 정상 동작.

### 근본 원인 (3가지)

| Gap | 원인 | 영향 |
|-----|------|------|
| 소괄호 미파싱 | `_parse_doc_ids_from_text()`가 `[대괄호]`만 파싱. section 2는 `(소괄호)` 사용 | (QNA-221109A), (FSS-2022-2311-03) 등 누락 |
| 축약 ID 불일치 | section 2에서 `FSS-2022-...` 사용, MongoDB `_id`는 `FSS-CASE-2022-...` | DB 조회 실패 |
| critical_factors 미수집 | `fetch_pinpoint_docs()`가 section 7 텍스트를 수집하지 않음 | (문단 B37⑴) 등 핵심 문단 누락 |

### 해결

1. 대괄호 + 소괄호 양쪽 파싱: `re.findall(r"\(([^)]*(?:QNA|FSS|KICPA|EDU|IE)[^)]*)\)", text)`
2. 축약 ID 자동 정규화: `FSS-` → `FSS-CASE-`, `KICPA-` → `KICPA-CASE-`
3. `fetch_pinpoint_docs()`에서 `checklist`(리스트) + `critical_factors` 수집 추가

**교훈**: 같은 데이터 소스(decision_trees.py)에서도 섹션마다 참조 형식이 다를 수 있음. 파서는 모든 섹션의 표기 규칙을 통합 처리해야 하며, 새로운 섹션 추가 시 `_parse_doc_ids_from_text()` 단위 테스트로 검증 필수.

---

## 34. LLM topic_hints가 임베딩 매칭을 방해하는 역효과 — hints 가중치 조정

### 문제

SECTION-9(고객의 선택권), SECTION-14(보증)에서 임베딩 유사도가 정답 토픽을 1~2위로 정확히 잡는데, LLM topic_hints가 잘못된 토픽(할인액의 배분, 수행의무 식별)에 +5.0 가산하여 정답 토픽을 top 3에서 밀어냄.

### 근본 원인

hints 가산점(5.0)이 임베딩 최대 점수(~4.7)보다 높아, LLM이 잘못된 hint를 줄 때 임베딩의 올바른 신호를 압도. LLM의 topic_hints는 31개 토픽 중 정확한 이름을 꾸준히 맞추지 못함 (비결정성).

### 해결

hints 가산점을 5.0 → **3.0**으로 하향. 임베딩 유사도(sim × 10.0, 보통 2.8~4.7)가 잘못된 hints(3.0)를 이길 수 있도록 밸런스 조정.

결과: 26개 테스트에서 0% Hit 5건 → **1건**으로 감소.

**교훈**: 다중 신호(keyword + LLM hints + embedding) 합산 시, 각 신호의 가중치는 **신뢰도 순**으로 설정해야 함. LLM hints는 불안정(비결정적)하므로 embedding(결정적, 사전 계산)보다 낮은 가중치가 적절. 불안정한 신호에 높은 가중치를 주면 안정적인 신호를 방해하는 역효과 발생.

---

## 35. pinpoint 문서가 AI 답변 좌측 패널에 표시되지 않는 문제

### 문제

pinpoint으로 fetch된 QNA/감리/IE 문서(10~15건)가 LLM context에는 주입되지만, AI 답변 페이지 좌측 근거 패널에 전혀 표시되지 않음. 본문/적용지침 5건만 보임.

### 근본 원인 (2단계)

1. **`DocResult` 스키마에 `chunk_type` 필드 누락**: pipeline state의 `chunk_type="pinpoint"`이 `_to_doc_result()` → `DocResult` 변환 과정에서 소실. SSE done 이벤트를 거쳐 Streamlit UI에 도달할 때 `chunk_type` 정보가 없음.

2. **`_prepare_ai_answer_docs()` 필터링 구조**: QNA/감리/IE 문서를 `_SUPPLEMENTABLE`로 일괄 제거 → AI 답변 텍스트에서 인용한 ID만 `_get_cited_pdr_docs()`로 재추가. LLM이 인용하지 않으면 UI에서 완전히 사라짐.

### 해결

1. `schemas.py:DocResult`에 `chunk_type: str = ""` 필드 추가
2. `search_service.py:_to_doc_result()`에서 `chunk_type` 전달
3. `evidence.py:_prepare_ai_answer_docs()`에서 pinpoint 문서(`chunk_type == "pinpoint"`)는 제거 대상에서 제외하고 항상 메인 패널에 표시

**교훈**: 파이프라인 내부의 메타데이터(`chunk_type`)가 API 스키마(`DocResult`)를 거쳐 프론트엔드까지 전달되려면, 중간 변환 함수(`_to_doc_result`)와 직렬화 스키마 모두에 해당 필드가 존재해야 함. 내부 state에만 있고 API 스키마에 없으면 프론트에서는 항상 기본값(빈 문자열/None)으로 보임.

---

## 36. pinpoint 미인용 문서 → 기존 섹션의 "참고하면 좋은 추가 문서"로 배치

### 설계 원칙

pinpoint 문서는 decision_tree에서 도메인 전문가가 사전 선별한 큐레이션 근거. LLM이 인용하지 않더라도 사용자가 확인할 수 있어야 함.

### 잘못된 접근 (revert됨)

pinpoint 문서를 메인 docs 리스트에 직접 추가 → source 기반 그룹핑이 꼬여 31건이 "본문 및 적용지침"에 합산, DuplicateElementKey 에러 발생. 별도 "큐레이션 참고 문서" 섹션도 기존 UI 구조에 맞지 않음.

### 올바른 접근

pinpoint 미인용 문서를 **기존 각 섹션(QNA, 감리사례, IE)의 "📂 참고하면 좋은 추가 문서" 더보기**에 배치:
- `_supp_by_group`에 pinpoint + retriever 미인용 문서를 합산
- pinpoint(`chunk_type="pinpoint"`, score=1.0)이 retriever보다 우선 정렬
- 소스별 최대 5건 (기존 3건 → 5건으로 확장)

### 현재 표시 계층

```
좌측 근거 패널 — 각 섹션별:
  ① AI 인용 본문/적용지침 (cited_paragraphs에서 DB 재조회)
  ② AI 인용 QNA/감리/IE (답변 텍스트에서 ID regex 추출 → DB 재조회)
  ③ "📂 참고하면 좋은 추가 문서" 더보기 (pinpoint 우선 + retriever 보충, 소스별 TOP 5)
```

**교훈**: 기존 UI 렌더러에 새 데이터를 넣을 때는 렌더러의 source 기반 그룹핑/키 생성 로직과 충돌하지 않는지 확인. 메인 docs 리스트에 직접 추가하면 DuplicateKey, 그룹 혼선 발생. 기존 "더보기" 경로(`_supp_by_group`)를 활용하는 것이 안전.

**참조**: `app/ui/evidence.py:_prepare_ai_answer_docs()`, `app/ui/evidence.py:_render_supp_extra()`

---

## 37. MongoDB Atlas 한글 $regex/$in 미동작 — fetch_ie_case_docs 조회 실패

### 문제

`fetch_ie_case_docs(("사례 24",))`가 0건 반환. DB에 `case_group_title: "사례 24: 대량 할인 장려금"` 문서 5건이 존재하는데도 조회 실패.

### 근본 원인

MongoDB Atlas에서 한글이 포함된 `$regex`와 `$in` 연산자가 동작하지 않음:
- `{"case_group_title": {"$regex": "^사례 24"}}` → 0건
- `{"case_group_title": {"$in": ["사례 24: 대량 할인 장려금"]}}` → 0건
- `{"case_group_title": "사례 24: 대량 할인 장려금"}` (정확 매칭) → 5건 ✓
- `{"$or": [{"case_group_title": "사례 24: 대량 할인 장려금"}]}` → 5건 ✓

### 해결

1. `_get_all_ie_case_titles()`: 전체 `case_group_title` distinct 목록을 캐시 (600초)
2. Python에서 prefix 매칭: "사례 24" → "사례 24: 대량 할인 장려금"
3. `$or` + 정확 매칭으로 DB 조회
4. `@st.cache_data` 제거: 상위 레벨(`_get_cited_ie_docs`)에서 세션 캐시하므로 중복

**교훈**: MongoDB Atlas는 한글 문자열에 대해 `$regex`/`$in`이 비정상 동작할 수 있음. 한글 필드 매칭은 Python 전처리 + 정확 매칭(`$or` + exact)이 안전.

**참조**: `app/ui/db.py:fetch_ie_case_docs()`, `app/ui/db.py:_get_all_ie_case_titles()`

---

## 38. IE pinpoint source "본문" → "적용사례IE" 수정

### 문제

IE pinpoint 문서의 `source`가 `"본문"`으로 설정되어, ACCORDION_GROUPS의 `"📋 적용사례(IE)": ["적용사례IE"]` 그룹에 매칭 안 됨. 좌측 패널에서 IE 섹션이 표시 안 되거나 "기준서 본문 및 적용지침"에 섞임.

### 근본 원인

`retriever.py:fetch_pinpoint_docs()` 5번 항목(IE 사례)에서 `"source": "본문"`으로 하드코딩. IE 사례는 본문 컬렉션에서 가져오지만, UI에서는 "적용사례IE" 그룹으로 분류되어야 함.

### 해결

`retriever.py:591` — `"source": "본문"` → `"source": "적용사례IE"`, `"category": "적용사례IE"`

**교훈**: pinpoint fetch에서 source 값은 DB의 원래 카테고리가 아니라 **UI 그룹핑 기준**에 맞춰 설정해야 함. ACCORDION_GROUPS와 source 값이 불일치하면 UI에서 해당 문서가 보이지 않음.

**참조**: `app/retriever.py:fetch_pinpoint_docs()`, `app/ui/constants.py:ACCORDION_GROUPS`

---

## 39. IE 사례 desc 인덱스 키 불일치 — case_group_title vs 짧은 키

### 문제

`_render_document_expander`에서 IE desc를 `get_desc_for_ie_case(cgt)` 호출 시, `cgt`가 `"사례 23: 가격할인(price concessions)"` (DB 긴 형태)인데 인덱스 키는 `"사례 23"` (짧은 형태)이라 매칭 실패.

### 근본 원인

`topic_content_map.py`의 `IE_CASE_DESC_INDEX`는 topics.json의 `ie.cases[].title`로 키를 만드는데, 이 값이 `"사례 23"` 형태. DB의 `case_group_title`은 `"사례 23: 가격할인(price concessions)"` 형태. 둘이 다름.

### 해결

`doc_renderers.py`에서 `case_group_title`을 `:` 기준으로 split하여 짧은 키로 조회:
```python
short_key = re.split(r"[:：]", cgt, maxsplit=1)[0].strip()
ie_desc = get_desc_for_ie_case(short_key) or get_desc_for_ie_case(cgt)
```

IE desc를 expander 내부에 💡 큐레이션 요약 박스(회색 배경, 좌측 테두리)로 표시.

**교훈**: 동일 데이터(IE 사례 제목)가 DB/큐레이션/코드에서 서로 다른 형식으로 존재할 수 있음. 조회 시 정규화(split/prefix 매칭)가 필수. 특히 한국어 IFRS 데이터는 콜론/전각콜론 혼용(`:`/`：`)에 주의.

**참조**: `app/ui/doc_renderers.py:_render_document_expander()`, `app/domain/topic_content_map.py:IE_CASE_DESC_INDEX`

---

## 40. 프로젝트 전체 데이터 정합성 감사 — 6개 취약점 수정

### 문제

topics.json 파이프라인 재실행 시 `qna_descs`/`finding_descs`가 반복 유실되는 문제에서 출발, 전체 프로젝트를 섹션별로 점검하여 **데이터 변경 시 꼬이는 모든 취약점**을 발견.

### 발견된 취약점 6가지

| 섹션 | 취약점 | 위험 |
|------|--------|------|
| A1 | summary-embeddings.json에 orphaned ID 4건 | summary_matcher에서 노이즈 매칭 |
| A2 | topic-embeddings.json에 orphaned 토픽 2건 | tree_matcher에서 존재하지 않는 토픽에 점수 부여 |
| A3 | `_split_merged_topics()` 하드코딩이 기존 desc 덮어쓰기 | split 토픽의 qna_descs/finding_descs 유실 |
| B | source 문자열 10+파일 하드코딩 | 한 곳 변경 시 나머지 미변경 → 그룹핑 실패 |
| C | BM25 빌드 실패 시 서버 미시작 | graceful degradation 불가 |
| D | `_go_home()` 캐시 키 미정리 | 이전 질문의 보조 문서가 새 질문에 잔류 |

### 해결

**A1**: `12-summary-embed.py` — topics.json의 `qna_ids`/`finding_ids`에 없는 orphaned ID 자동 제외

**A2**: `13-topic-embed.py` — topics.json 키에 없는 토픽 자동 제외

**A3**: `_split_merged_topics(existing=)` — 기존 topics.json의 split 토픽 qna_descs/finding_descs도 보존

**A4**: `verify_data_consistency()` — topics.json ↔ summary-embeddings ↔ topic-embeddings 교차 검증 함수 추가 (10-parse-curation.py 실행 시 자동 호출)

**B**: `constants.py`에 source 문자열 상수 11개 + ID 접두어 상수 정의 → evidence.py, grouping.py, doc_helpers.py, retriever.py, db.py에서 import 사용

**C**: `main.py` — BM25 빌드 try/except + graceful degradation (vector search만으로 동작)

**D**: `session.py` — `_go_home()` reset_keys에 캐시 키 7개 추가 (`_supp_by_group`, `_cited_*_cache*`)

**C1**: `topic_content_map.py` — TOPIC_CONTENT_MAP 빈 dict 시 warning 로그

### 검증

```python
# 교차 검증 실행 (10-parse-curation.py 끝에서 자동 호출)
verify_data_consistency()
# → summary-embeddings orphaned: 4건 (12-summary-embed.py 재실행으로 정리)
# → topic-embeddings orphaned: 2건 (13-topic-embed.py 재실행으로 정리)
```

**교훈**: 데이터 파이프라인은 **교차 검증**이 없으면 orphaned/stale 데이터가 조용히 누적된다. 파이프라인 실행 시 자동 검증 함수를 호출하여 불일치를 사전 감지해야 함. source 문자열 같은 도메인 상수는 중앙화하여 한 곳에서 관리해야 변경 시 연쇄 불일치를 방지할 수 있다.

**참조**: `app/preprocessing/10-parse-curation.py:verify_data_consistency()`, `app/ui/constants.py`

---

## 41. AI 답변 좌측 패널 — IE 사례/QNA/감리 표시 전면 개선 (2026-03-15)

### 배경

AI 답변 페이지 좌측 근거 패널에서 IE 적용사례, QNA, 감리사례가 전혀 표시되지 않는 문제. 본문/적용지침만 표시됨.

### 발견된 문제 (7개)

| # | 문제 | 원인 | 해결 |
|---|------|------|------|
| 1 | `chunk_type` SSE 미전달 | `DocResult` 스키마에 `chunk_type` 필드 없음 | `schemas.py`에 필드 추가 + `_to_doc_result`에서 전달 |
| 2 | IE pinpoint source "본문" | `retriever.py`에서 IE 사례 source를 "본문"으로 하드코딩 | `"적용사례IE"`로 변경 |
| 3 | pinpoint 미인용 문서 미표시 | `_prepare_ai_answer_docs()`가 AI 미인용 문서 일괄 제거 | `_supp_by_group`에 pinpoint 포함, "참고하면 좋은 추가 문서" 더보기 |
| 4 | 그룹 0건 시 더보기 미렌더 | `if not group_docs: continue`로 그룹 자체 스킵 | `has_supp` 확인 후 더보기만이라도 렌더 |
| 5 | `fetch_ie_case_docs` 한글 매칭 실패 | MongoDB Atlas `$regex`/`$in` 한글 미동작 | Python prefix 매칭 + `$or` 정확 매칭 |
| 6 | `_get_cited_ie_docs` 반환값에 `source` 누락 | DB 원본 doc에 source 필드 없음 → 그룹핑 실패 | `d["source"] = SRC_IE` 설정 |
| 7 | IE desc 인덱스 키 불일치 | DB "사례 23: 가격할인" vs 인덱스 "사례 23" | `:` split 정규화 |

### 추가 개선

- **AI 인용 사례 볼드**: `_render_ie_group`에서 AI 답변의 "사례 N" 추출 → 📌 아이콘 + `:blue[**title**]` + `expanded=True`
- **IE desc 누락 24건 보충**: `topic_content_map.py`에 `_FALLBACK_IE_DESCS` 추가 (LLM 생성)
- **desc 쓰레기 정리**: `_get_ie_desc_clean()` — 끝의 `, , .` 제거
- **사례 내 라벨 통일**: `_make_label`에서 `case_group_title` 있으면 `[사례 N: 제목] 문단 IEXXX - title` 형태
- **"참고하면 좋은" IE**: DB에서 개별 문서 가져와 메인 사례와 동일한 그룹 형태로 렌더링

### 설계 원칙

```
AI 답변 좌측 근거 패널 표시 계층:
  ① AI 인용 본문/적용지침 → 메인 (cited_paragraphs → DB 재조회)
  ② AI 인용 QNA/감리 → 메인 (답변 텍스트 regex → DB 재조회)
  ③ AI 인용 IE 사례 → 메인 (답변 텍스트 "사례 N" regex → DB 재조회)
     → 📌 볼드 + 자동 펼침 + desc
  ④ pinpoint 미인용 + retriever 미인용 → "📂 참고하면 좋은 추가 문서"
     → IE: 사례 그룹 형태 (desc + 개별 문서)
     → QNA/감리: PDR expander
```

**참조**: `app/ui/evidence.py`, `app/ui/doc_renderers.py`, `app/api/schemas.py`, `app/retriever.py`, `app/ui/db.py`, `app/domain/topic_content_map.py`

---

## 23. st.status 위젯 클릭 시 빈 칸 펼쳐지는 UX 문제

### 문제
`st.status(expanded=False)`로 진행 표시를 했으나, 사용자가 클릭하면 빈 `<details>` 영역이 펼쳐짐. CSS `pointer-events: none`을 `div[data-testid="stStatusWidget"]`에 적용해도 `<details>/<summary>` 내부 구조까지 차단 불가.

### 해결
`st.status` → `st.empty()` + `st.info()`로 교체.
```python
progress = st.empty()
progress.info("질문을 분석하고 있어요 (15%)")
# SSE 이벤트마다 업데이트
progress.info("근거 문서를 검색하고 있어요 (40%)")
# 완료 시
progress.empty()
```

### 교훈
`st.status`는 내부적으로 `<details>` HTML 요소를 사용하므로 CSS만으로 클릭을 완전 차단할 수 없음. 진행 표시만 필요하면 `st.empty()` + `st.info()`가 더 적합.
