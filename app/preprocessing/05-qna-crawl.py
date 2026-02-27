import requests
import json
import os
import re

def clean_qna_text(text):
    if not text: return ""
    text = text.replace('&nbsp;', ' ')
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def process_qna_chunks():
    # 앞서 크롤링해둔 1115호 원본 데이터 경로
    RAW_FILE = "data/web/kifrs_1115_all_clauses.json"
    OUTPUT_FILE = "data/web/kifrs_1115_qna_chunks.json"
    
    print("🔍 1. K-IFRS 1115호 본문 데이터에서 연결된 질의회신 ID를 자동 추출합니다...")
    
    # ==========================================
    # 자동화 로직: 본문 데이터에서 faqDocNumbers 싹쓸이
    # ==========================================
    try:
        with open(RAW_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        print(f"❌ 원본 파일을 읽을 수 없습니다. 경로를 확인해주세요: {e}")
        return
        
    doc_numbers = set()
    for item in raw_data:
        faq_str = item.get("faqDocNumbers")
        if faq_str:
            # 콤마로 구분된 ID들을 쪼개서 set에 넣음 (중복 자동 제거)
            for q_id in faq_str.split(","):
                clean_id = q_id.strip()
                if clean_id:
                    doc_numbers.add(clean_id)
                    
    doc_numbers = list(doc_numbers)
    print(f"✅ 총 {len(doc_numbers)}개의 수익인식(1115호) 관련 고유 질의회신 문서를 찾아냈습니다!\n")
    
    # ==========================================
    # 2. 추출된 ID 리스트를 순회하며 Q&A 원문 수집
    # ==========================================
    print("🚀 2. 질의회신(Q&A) 원문 데이터 자동 수집 및 RAG 청킹을 시작합니다...")
    
    qna_chunks = []
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    for i, doc_id in enumerate(doc_numbers, 1):
        url = f"https://www.kifrs.com/api/qnas/v2/{doc_id}"
        
        try:
            # 서버에 부담을 주지 않도록 타임아웃 설정
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code != 200:
                print(f"  ❌ [{i}/{len(doc_numbers)}] 실패: {doc_id} (상태코드: {res.status_code})")
                continue
                
            data = res.json().get("facilityQna", {})
            if not data:
                continue

            title = data.get("title", "제목 없음")
            full_content = data.get("fullContent", "")
            date_str = data.get("date", "202X")[:4] 
            
            clean_content = clean_qna_text(full_content)
            
            # 관련 조항 추출 (계층 구조용)
            bookmarks = data.get("bookmarkStdParagraphs", {})
            para_list = bookmarks.get("1115", [])
            
            if para_list:
                primary_para = para_list[0]
                para_text = f"문단 {primary_para} 등" if len(para_list) > 1 else f"문단 {primary_para}"
            else:
                para_text = "관련문단"

            hierarchy_path = f"질의회신 > K-IFRS 제1115호 > {para_text} > {title} ({date_str})"
            
            chunk = {
                "id": f"QNA-{doc_id}",
                "content": clean_content,
                "metadata": {
                    "stdNum": "1115",
                    "paraNum": doc_id,
                    "category": "질의회신",
                    "weight_score": 1.15,  # 🎯 질의회신 가중치 15% 적용
                    "hierarchy": hierarchy_path,
                    "sectionLevel": 1
                }
            }
            qna_chunks.append(chunk)
            print(f"  ✅ [{i}/{len(doc_numbers)}] 성공: {doc_id} ({title})")
            
        except Exception as e:
            print(f"  ❌ [{i}/{len(doc_numbers)}] 에러 발생 ({doc_id}): {e}")

    # JSON 파일로 일괄 저장
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(qna_chunks, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 총 {len(qna_chunks)}개의 수익 관련 질의회신 청크 자동 수집 완료!")
    print(f"📁 결과물 저장: {OUTPUT_FILE}")

if __name__ == "__main__":
    process_qna_chunks()