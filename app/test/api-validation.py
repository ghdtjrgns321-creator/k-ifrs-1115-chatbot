import os
from dotenv import load_dotenv

load_dotenv()

# Solar Pro3 테스트
from langchain_upstage import ChatUpstage

llm = ChatUpstage(
    model = "solar-pro3",
    temperature = 0
)
print("⏳ Upstage 서버에 요청을 보냈습니다. 답변을 기다리는 중...")
response = llm.invoke("K-IFRS 1115호에서 수행의무 식별 기준을 설명해주세요.")
print(f"✅ Solar Pro 3: {response.content[:100]}...")

# Solar Embedding 테스트
from langchain_upstage import UpstageEmbeddings
embeddings = UpstageEmbeddings(model="solar-embedding-1-large")
vector = embeddings.embed_query("총액인식 순액인식 판단기준")
print(f"✅ Embedding 차원: {len(vector)}")

# ChromaDB 연결 테스트
import chromadb
client = chromadb.HttpClient(host="localhost", port=8100)
print(f"✅ ChromaDB heartbeat: {client.heartbeat()}")

# LangSmith 연결 테스트
from langsmith import Client
ls_client = Client()
print(f"✅ LangSmith 프로젝트: {ls_client.list_projects()}")