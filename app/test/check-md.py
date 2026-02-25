import json

file_path = "data/processed/parsed-elements.json"

with open(file_path, "r", encoding="utf-8") as f:
    elements = json.load(f)

print("📊 추출된 표(Table) 3개 미리보기!\n" + "="*50)
table_count = 0

for elem in elements:
    # metadata의 category가 'table'인 것만 찾기
    if elem.get("metadata", {}).get("category") == "table":
        print(f"\n[표 {table_count + 1}]")
        print(elem.get("content"))
        print("-" * 50)
        table_count += 1
        
        # 3개만 출력력
        if table_count >= 3:
            break

print("\n💡 파이프(|) 모양으로 예쁘게 표가 그려져 있나요?")