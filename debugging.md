# Streamlit 디버깅 교훈 (k-ifrs-1115-chatbot)

> 최종 업데이트: 2026-03-13

---

## 1. Streamlit CSS 커스터마이징 한계

### 핵심
Streamlit은 CSS 커스터마이징을 공식 지원하지 않음. `st.markdown(unsafe_allow_html=True)`로 주입한 CSS는 내부 레이아웃 컴포넌트에 안정적으로 적용 안 됨.

### CSS 작동 범위
- **O**: `key=` 기반 셀렉터로 **위젯 자체** 스타일 변경 (예: `div.st-key-xxx button`)
- **X**: 내부 레이아웃 속성 (`gap`, `margin`), `stVerticalBlock` 등 프레임워크 내부 컴포넌트

### 올바른 접근
1. Streamlit API docs에서 **네이티브 파라미터 확인** (예: `st.container(gap="xsmall")`)
2. 네이티브로 불가능할 때만 CSS 시도
3. CSS 시도 시 빨간 테두리 디버그로 셀렉터 매칭부터 확인

`st.container()`의 `gap` 파라미터: `None`(0) / `"xxsmall"`(0.25rem) / `"xsmall"`(0.5rem) / **`"small"`(기본, 1rem)** / `"medium"`(2rem) / `"large"`(4rem)

---

## 2. 위젯 키 수정 제한

위젯 인스턴스화 후 `st.session_state["key"] = None` → `StreamlitAPIException`.
**해결**: `on_change` 콜백 안에서 처리 (콜백은 위젯 렌더링 전에 실행되므로 키 수정 가능).

```python
def _on_change():
    if st.session_state.get("my_pills"):
        st.session_state["my_pills"] = None
st.pills("label", options=opts, key="my_pills", on_change=_on_change)
```

---

## 3. 외부 데이터의 숨겨진 문자 패턴

### JSON 공백 패턴
`topics.json`에서 `"합니다 ."` (다와 `.` 사이 공백)으로 저장. 정규식 매칭 실패의 원인.
→ `repr()`로 실제 데이터 확인 후, 정규화 전처리 추가.

### Unicode 변형 (물결표 3종)
kifrs.com 원본에 `~`(U+007E, 108건) / `∼`(U+223C, 28건) / `～`(U+FF5E, 3건) 혼재.
→ 모든 문자 클래스에 3종 모두 포함: `[~～∼\-]`

**교훈**: 외부 데이터의 유사 문자(tilde, dash, quote 등)는 `repr()` + `ord()`로 실제 코드포인트를 반드시 확인. 시각적으로 동일해도 코드포인트가 다를 수 있음.

---

## 4. 데이터 정합성 문제는 데이터에서 해결

- **cross_links 불일치**: cross_link 값이 topics.json 키와 불일치 → JSON 데이터 자체를 수정. 코드에서 퍼지 매칭은 복잡도만 증가.
- **토픽 별칭 해석 순서**: 빈 스텁이 존재하면 정확 매칭이 잘못된 결과 반환 → 별칭 매핑을 **최우선**으로 체크.

---

## 5. `_expand_para_range` — 문단 범위 확장 로직

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

## 6. 청킹 시 번호 목록 `(1)(2)(3)` 누락 버그

### 근본 원인 (3가지)
1. **`para-inner-number-item` HTML 구조 미처리**: kifrs.com API가 `idt-1` 대신 별도 구조 사용. `clean_html_to_md()`가 이 구조를 무시.
2. **조사 이음 정규식이 번호 항목을 먹음**: `")\n이"` → `"(2)\n이 재화나"` → `"(2)이 재화나"`로 합침.
3. **마크다운 단일 `\n`은 줄바꿈 아님**: `\n\n`(이중 줄바꿈)만 단락 분리됨.

### 해결
부모 div 단위로 `number-item` + `hanguel-item` 텍스트를 `\n\n`으로 조립. 후처리로 번호 항목 앞 `\n\n` 보장.

**교훈**: HTML 파싱 후 반드시 원본(`fullContent`)과 비교 검증. `get_text(strip=True)`는 앞뒤 공백/줄바꿈을 제거하므로 주의.

---

## 7. `paraContent` < `fullContent` 텍스트 유실

kifrs.com API가 일부 문단에서 `paraContent`에 본문 일부만 제공. HTML 파싱 후 `fullContent` 키워드 비교 → **30% 이상 유실이면 `fullContent`로 폴백**.

영향: 2건 (BC445I, BC445L) + 웩12.

---

## 8. 문단 참조 볼드 강조 — 체이닝 에지 케이스

### 수정 포인트 4가지
1. **범위 표기(`~`) 처리**: `\d+[A-Za-z]*` → 뒤에 `(?:[~～∼\-]...\d+[A-Za-z]*)?` 추가
2. **루프 횟수**: 3 → 15 (실데이터 최대 13개 나열, `n==0`이면 즉시 탈출)
3. **"와" 접속사 추가**: `및|과|또는|그리고` → `및|과|와|또는|그리고`
4. **괄호 suffix 건너뛰기**: `</span>(3), 37` → `(?:\([0-9가-힣]+\))?` 추가

**교훈**: 정규식 체이닝은 1회에 1단계만 진행하므로, 루프 횟수가 실데이터의 최대 나열 수를 커버해야 함.

---

## 9. QNA/감리사례 parent 문서 처리

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

## 10. summary 줄바꿈 — 범용 한국어 어미 처리

`다.`만 매칭하면 `함.`, `음.`, `됨.` 등 누락. **한글 + 마침표** 범용 패턴으로 변경:
```python
t = re.sub(r"(?<=[가-힣])\s+\.", ".", t)       # 공백 정규화
t = re.sub(r"(?<=[가-힣])\.\s+", ".<br>", t)   # 줄바꿈
```
영문/숫자 뒤 마침표는 lookbehind `[가-힣]`로 영향 없음.

---

## 11. LLM 생성 텍스트 유출 (`finding_descs`)

### 문제 유형
1. **크로스 링크 추천 텍스트** (21건): LLM 응답 말미의 `💡 크로스 링크 추천` 구간이 desc에 포함
2. **LLM 전문(preamble)** (2건): "검토한 결과..." 메타 응답이 그대로 저장
3. **깨진 bold 패턴** (1건): `**: .` 의미 없는 문장
4. **숨겨진 공백** (247건): `"다 ."` → `"다."` 정규화

### 해결
`topics.json` 원본 데이터 정리 + `summary-embeddings.json` 재생성.

**교훈**: LLM으로 큐레이션 데이터 생성 시, 저장 전 후처리(separator 이후 잘라내기, 메타 텍스트 제거)가 필수.

---

## 12. 버튼 클릭 시 에러/깜빡임 — 이중 rerun + DB 에러 캐시 재생

### 근본 원인

**1) 이중 rerun**: `if st.button: st.rerun()` → 2회 rerun → 깜빡임/에러 노출

| 패턴 | rerun 횟수 | 깜빡임 |
|------|-----------|--------|
| `if st.button: st.rerun()` | **2회** | 있음 |
| `st.button(on_click=callback)` | **1회** | 없음 |

**2) `@st.cache_data` 안에서 `st.error()` 호출**: 에러가 캐시에 녹음되어 TTL 동안 매번 재생.
→ `logging.warning()`으로 교체, UI 노출 제거.

**3) 존재하지 않는 함수 import**: `ImportError` → regex로 직접 추출하도록 수정.

**교훈**: Streamlit 페이지 전환/상태 변경은 반드시 `on_click` 콜백 패턴 사용. `@st.cache_data` 안에서 `st.error()` 등 UI 출력 함수 호출 금지.

---

## 13. 핀포인트 문서 ID 파싱 — decision_trees 참조 패턴

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

### 메타데이터 중첩 (debugging.md #9 연계)
parent 컬렉션의 `title`, `hierarchy`는 `metadata` dict 안에 중첩. FSS 감리사례는 `title` 키 자체가 없을 수 있음.
→ `doc.get("metadata", {}).get("title", "")` 패턴으로 방어적 접근.

**교훈**: 큐레이션 데이터의 참조 패턴은 사람이 쓴 텍스트라 일관성이 없음. 파서는 모든 에지 케이스를 커버해야 하며, `_parse_doc_ids_from_text()` 단위 테스트로 전수 검증 필수.

---

## 14. user msg에 CoT prefix 추가 시 non-reasoning 모델 산술 정확도 하락

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

## 15. 문단 참조 괄호 suffix 뒤 줄바꿈 잔류 — text.py 정규식 누락

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

## 16. Cohere Reranker가 큐레이션(pinpoint) 문서를 탈락시키는 문제

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

## 17. 감리사례 매칭 — 문단 번호 기반 → 서머리 임베딩 기반 전환

### 문제

기존 `format.py`가 LLM 답변에서 문단 번호를 추출(`_PARAGRAPH_RE`) → child 컬렉션에서 `related_paragraphs` 매칭 → 코사인 유사도 순위 방식. 범용 문단(9, 12, 22 등)이 자주 매칭되어 노이즈 발생, `GENERIC_PARAGRAPHS` 블랙리스트로 땜질.

### 해결

`summary_matcher.py` 도입: `summary-embeddings.json`에 사전 임베딩된 QNA/감리/IE 서머리와 사용자 질문의 코사인 유사도로 직접 매칭. 문단 번호 추출/블랙리스트 불필요.

**교훈**: 문단 번호 매칭은 간접적(문단→문서→유사도)이라 노이즈에 취약. 서머리 설명을 사전 임베딩하고 query와 직접 비교하는 것이 더 안정적.

---

## 18. 여는 괄호 직후 줄바꿈 잔류 — clean_text step 4 누락 패턴 (舊 #16)

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

**교훈**: 크롤링 아티팩트 줄바꿈은 특정 위치(문단 참조 앞/뒤/괄호 안)에 다양한 패턴으로 나타남. 개별 케이스를 땜질하기보다, `(\n문단` 같은 구조적 패턴 단위로 범용 규칙을 추가할 것. #15와 동일 파일, 동일 근본 원인(크롤링 줄바꿈 파편화).
