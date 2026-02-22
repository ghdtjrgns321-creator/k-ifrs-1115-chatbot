# Solar Pro3 테스트
from langchain_upstage import ChatUpstage

llm = ChatUpstage(
    model = "solar-pro3-preview",
    temperature = 0
)

response = llm.invoke("K-IFRS 1115호에서 수행의무 식별 기준을 설명해주세요.")
print(f"✅ Solar Pro 3: {response.content[:100]}...")