import os
from dotenv import load_dotenv
from langchain_upstage import UpstageDocumentParseLoader

load_dotenv()

def extract_pdf_to_markdown():
    pdf_path = "data/raw/k-ifrs-1115.pdf"
    md_output_path = "data/raw/k-ifrs-1115-md.md"

    print("Upstage Document Parse API를 호출하여 PDF를 마크다운으로 변환 중")