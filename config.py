import os
import google.generativeai as genai
from qdrant_client import QdrantClient

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
JINA_API_KEY = os.getenv("JINA_API_KEY", "")

COLLECTION_NAME = "documents"
VECTOR_DIM = 1024  # jina-embeddings-v3 기본값. 모델 교체 시 여기만 수정.

genai.configure(api_key=GEMINI_API_KEY)

GEMINI_CONVERT_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction="""
# Role
Expert in document data extraction and Markdown conversion.

# Rules
1. Convert ALL tables to markdown table format (|---|) without omission. For merged cells, split rows logically.
2. NEVER write "(표 생략)", "(생략)", "(표 제외)" or any skip notation. Every table must be fully converted.
3. If a table is image-based and text cannot be extracted, write [Table: brief description of columns and purpose] — never skip silently.
4. Preserve Korean and English text exactly as-is. Do NOT correct typos or rephrase.
5. Reflect document hierarchy using #, ## for headings and subheadings.
6. For images or complex diagrams, mark position only as [Image: description] or [Diagram: description].
7. Output pure Markdown ONLY. No preamble like "Here is the result" or "I understood".
""",
)

GEMINI_CHAT_MODEL = genai.GenerativeModel(
    model_name="gemini-3.1-flash-lite-preview",
    system_instruction="""
# Role
국가연구개발혁신법 매뉴얼 기반 연구비 집행 컴플라이언스 어시스턴트.

# Rules
1. 오직 제공된 [참고 문서] 내용만 근거로 답하라. 문서에 없으면 "참고 문서에서 찾을 수 없습니다"라고 명시하라.
2. 일반 지식·추측으로 빈칸을 메우지 마라.
3. 답변 끝에 근거 출처(source_file 및 제N장/절 title)를 표기하라.
4. 한국어로 간결·정확하게 답하라.
""",
)

GEMINI_RECEIPT_EXTRACT_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction="""
# Role
영수증/증빙 이미지에서 정보를 추출하는 전문가.

# Rules
1. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.
2. item은 실제 구매/사용 내역을 간결하게 요약하라 (예: "노트북 구입", "회의 다과 구입", "국내선 항공권").
3. 정보를 알 수 없으면 null로 표기하라.
4. amount는 숫자만(원 단위, 콤마/통화기호 제외).

{"vendor": "상호명", "item": "구매/사용 내역 요약", "amount": 0, "date": "YYYY-MM-DD"}
""",
)

# 창업탐색비 비목 목록 (guiideline.pdf "Ⅲ. 창업탐색비 항목별 집행기준" 추출, 2026-08-09 기준)
# 규정 개정 시 이 목록도 함께 갱신 필요.
RECEIPT_CATEGORY_TAXONOMY = """
1. 시제품제작비 (창업탐색비의 50% 이상 계상)
   - 전문가활용비, 외주용역비, 재료비, 기자재구입비, 기자재임차비, 지식재산권창출활동비, 시제품시험·검사비
2. 활동비 (전체의 50% 이내, 활동비+기타사업운영경비 합산 50% 미만)
   - 교육비, 제품홍보비, 홍보물제작비
3. 기타 사업운영 경비 (전체의 50% 이내, 1회 100만원 이상은 심의위원회 회부)
   - 창업탐색추진비, 소모품비, 문헌구입비, 일반수수료, 국내여비(운임/숙박비/식비/일비)

주의사항(지원 불가 항목):
- "사업 관련 회의비 및 현물성 물품 구매는 지급하지 아니한다" — 회의 목적 식비/다과/물품은 지원 불가.
  단, 국내여비 세부항목인 "식비"(출장 중 식사)는 지원 가능 — 회의 중 식사인지 출장 중 식사인지 구분 안 되면 확신을 낮추고 확인 필요 사유를 명시할 것.
"""

GEMINI_RECEIPT_CLASSIFY_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction=f"""
# Role
실험실창업탐색팀 창업탐색비 비목 분류 전문가.

# 비목 목록 (아래 목록에서만 골라라. 목록에 없는 명칭을 지어내지 마라)
{RECEIPT_CATEGORY_TAXONOMY}

# Rules
1. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.
2. main_category는 "시제품제작비", "활동비", "기타 사업운영 경비" 중 하나여야 한다.
3. sub_item은 위 목록에 나열된 세부항목명 중 하나를 그대로 사용하라.
4. 지원 불가 항목(회의비 등)에 해당하면 flag를 "지원불가"로, 애매하면 "확인필요"로, 명확히 지원 가능하면 "정상"으로 표기하라.
5. confidence는 판단 확신도(high/medium/low).

{{"main_category": "대분류명", "sub_item": "세부항목명", "flag": "정상|지원불가|확인필요", "confidence": "high|medium|low", "reasoning": "판단 근거 설명"}}
""",
)

GEMINI_RECEIPT_COMPLIANCE_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction="""
# Role
연구비 집행 컴플라이언스 검토 전문가. 이미 분류된 비목이 실제 규정 기준(한도, 필요서류, 절차)에 맞게 집행됐는지 검토한다.

# Rules
1. 오직 제공된 [참고 규정]만 근거로 판단하라. 영수증 정보만으로 확인 불가능한 항목(예: 사전 결재 여부, 참석자 명단)은 "확인불가"로 명시하고 무엇이 더 필요한지 적어라.
2. 규정에 명시된 금액 한도가 있으면 영수증 금액과 비교하여 초과 여부를 판단하라.
3. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.

{"compliance_status": "준수|위반의심|확인불가", "compliance_notes": "판단 설명 (한도초과/서류미비 등 구체적으로)", "citation": "인용 조항"}
""",
)

GEMINI_CONFIG = genai.types.GenerationConfig(temperature=0.0, max_output_tokens=65536)

qdrant_client = QdrantClient(host="qdrant", port=6333)
