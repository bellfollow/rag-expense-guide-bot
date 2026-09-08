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
5. 문서 우선순위: 각 참고 문서엔 등급(tier, rank)이 표시된다. rank 숫자가 작을수록 법적으로 상위(법률 > 시행령 > 시행규칙 > 법령해설_매뉴얼 > 고시/훈령/예규 > 사업지침_운영요강). 사업 범위 안에서 다루는 사안은 원칙적으로 rank가 더 큰(하위) 사업지침을 우선 적용하되, rank가 더 작은(상위) 문서에 명시된 금지·의무 조항(강행규정)은 지침 내용보다 우선한다. 두 문서 내용이 충돌하면 둘 다 인용하고 어느 것을 우선했는지와 그 이유를 밝혀라.
""",
)

GEMINI_RECEIPT_EXTRACT_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction="""
# Role
영수증/증빙 이미지에서 정보를 추출하는 전문가.

# Rules
1. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.
2. is_receipt는 이미지가 영수증/증빙서류(카드전표, 세금계산서, 청구서 등 지출 증빙)인지 먼저 판단하라.
   사진, 스크린샷, 일러스트, 도표, 인물/풍경 사진 등 지출 증빙이 아니면 false로 표기하라.
3. is_receipt가 false면 vendor/item/amount/date는 전부 null로 표기하라.
4. item은 실제 구매/사용 내역을 간결하게 요약하라 (예: "노트북 구입", "회의 다과 구입", "국내선 항공권").
5. 정보를 알 수 없으면 null로 표기하라.
6. amount는 숫자만(원 단위, 콤마/통화기호 제외).

{"is_receipt": true, "vendor": "상호명", "item": "구매/사용 내역 요약", "amount": 0, "date": "YYYY-MM-DD"}
""",
)

# 문서 간 법적 등급 — 한국 법령 체계상 고정된 위계(문서마다 다른 게 아니라 법 이론상 보편적인 순서라 하드코딩 타당).
# 신규 문서는 GEMINI_DOC_TIER_MODEL이 내용 보고 자동으로 이 중 하나에 매핑함 (파일명 수동 등록 불필요).
DOC_TIER_RANK = {
    "법률": 1,
    "시행령": 2,
    "시행규칙": 3,
    "법령해설_매뉴얼": 4,
    "고시_훈령_예규": 5,
    "사업지침_운영요강": 6,
    "기타": 99,
}
DEFAULT_DOC_TIER = {"tier": "기타", "label": "미분류 문서", "rank": 99}

# 자동분류가 틀렸을 때만 쓰는 수동 보정 escape hatch. 평소엔 비워둠.
DOCUMENT_TIER_OVERRIDE: dict[str, dict] = {}

GEMINI_DOC_TIER_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction="""
# Role
한국 법령/행정문서 위계 분류 전문가.

# Rules
1. 입력으로 문서 앞부분(제목, 목적, 제정근거, 발령형식 등)이 주어진다. 이를 보고 문서의 법적 성격과 "적용 범위"를 함께 판단하라.
2. tier는 반드시 아래 중 하나여야 한다: "법률", "시행령", "시행규칙", "법령해설_매뉴얼", "고시_훈령_예규", "사업지침_운영요강", "기타"
   - 법률: OO법, OO법률 원문 (국회 제정)
   - 시행령: OO법 시행령 원문 (대통령령)
   - 시행규칙: OO법 시행규칙 원문 (부령/총리령)
   - 법령해설_매뉴얼: 법률/시행령/시행규칙의 조문을 설명·해설하는 매뉴얼로, "특정 사업 하나"가 아니라 그 법이 적용되는 전체 제도/모든 사업에 공통 적용됨 (예: "OO법 매뉴얼"이 개별 지원사업이 아니라 국가연구개발사업 전체에 대한 해설일 때)
   - 고시_훈령_예규: 행정기관 고시/훈령/예규/공고
   - 사업지침_운영요강: "특정 지원사업 1건"에만 적용되는 운영지침/관리지침/가이드라인/집행기준/요강 (제목에 특정 사업명이 명시되어 그 사업 참여자에게만 적용되는 문서)
   - 기타: 위 어디에도 해당 안 하거나 판단 근거 부족
   - **핵심 구분 기준은 형식(매뉴얼/지침 등 명칭)이 아니라 적용 범위다**: "법령 전체/모든 사업 공통"이면 법령해설_매뉴얼(전체 범위, 상위), "이 사업 하나만"이면 사업지침_운영요강(개별 범위, 하위). 제목에 구체적인 사업명(예: "OO 지원사업 △△팀")이 박혀있으면 사업지침_운영요강 쪽으로 판단하라.
3. doc_type에는 문서의 실제 명칭(예: "국가연구개발혁신법 시행령")을 적어라. 알 수 없으면 파일명 기반으로 추정하되 확신 없음을 reasoning에 밝혀라.
4. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.

{"doc_type": "문서 실제 명칭", "tier": "법률|시행령|시행규칙|고시_훈령_예규|사업지침_운영요강|기타", "reasoning": "판단 근거"}
""",
)


def get_doc_tier_override(filename: str) -> dict | None:
    return DOCUMENT_TIER_OVERRIDE.get(filename)


def build_doc_tier(tier: str, doc_type: str) -> dict:
    rank = DOC_TIER_RANK.get(tier, DOC_TIER_RANK["기타"])
    return {"tier": tier, "label": f"{doc_type} ({tier}, rank {rank})", "rank": rank}


# 창업탐색비 비목 목록 (guiideline.pdf "Ⅲ. 창업탐색비 항목별 집행기준" 추출, 2026-08-09 기준)
# 규정 개정 시 이 목록도 함께 갱신 필요.
RECEIPT_CATEGORY_TAXONOMY = """
1. 시제품제작비 (창업탐색비의 50% 이상 계상)
   - 전문가활용비, 외주용역비, 재료비, 기자재구입비, 기자재임차비, 지식재산권창출활동비, 시제품시험·검사비
2. 활동비 (전체의 50% 이내, 활동비+기타사업운영경비 합산 50% 미만)
   - 교육비, 제품홍보비, 홍보물제작비
3. 기타 사업운영 경비 (전체의 50% 이내, 1회 100만원 이상은 심의위원회 회부)
   - 창업탐색추진비, 소모품비, 문헌구입비, 일반수수료, 국내여비(운임/숙박비/식비/일비)

주의사항 — 지침에 명시된 지원 불가 항목:

아래는 가이드라인 원문에 단정적 금지 표현으로 적힌 항목이다.
영수증에 인쇄된 사실만으로 아래에 해당함이 확인되면 flag를 "지원불가"로 판정하라.
추정이 필요하면 "확인필요"다(Rule 4-2 참조).

[영수증만으로 판정 가능한 금지 항목]
- 유류비(주유소 결제, 휘발유·경유 구입): "유류비는 지원되지 않으며" — 지원불가.
  자가용 이용 시에는 동일구간 대중교통비 정액으로만 집행하며, 톨비 영수증만 인정된다.
  주유소 영수증은 그 자체로 지원 불가이며 출장 목적 여부를 확인할 필요가 없다.
- 주차비(주차장 결제): "출장지 내에서 소요되는 교통비(버스, 지하철, 택시 요금 등),
  주차비 등의 각종 비용은 일비에 포함되므로 별도로 청구할 수 없다" — 지원불가.
- 렌터카 이용료: "국내 출장 시 렌트카 이용 경비는 청구할 수 없다" — 지원불가.
- 출장지 내 택시·버스·지하철 요금: 위와 같은 조항으로 일비에 포함 — 지원불가.
  (출장지까지의 이동 운임인 KTX·시외버스 승차권은 국내여비(운임)로 지원 가능하다.)
- 범용성 기자재(PC, 노트북, 태블릿)와 범용 소프트웨어(한글, MS-Office 등): 구매 금지 — 지원불가.
- 귀금속·보석 등 쥬얼리 재료: "원칙적으로 구매가 불가능" — 지원불가.

[영수증만으로는 판정할 수 없는 금지 항목 — "확인필요"로 둘 것]
- "사업 관련 회의비 및 현물성 물품 구매는 지급하지 아니한다" — 회의 목적 식비/다과/물품은
  지원 불가이나, 영수증에는 그 지출이 회의 목적이었는지가 인쇄되지 않는다.
  식당·카페·편의점 영수증을 이 조항만으로 "지원불가"로 판정하지 마라.
  국내여비 세부항목인 "식비"(출장 중 식사)는 지원 가능하므로, 회의 중 식사인지
  출장 중 식사인지 구분되지 않으면 "확인필요"로 하고 확인이 필요한 사유를 명시하라.
- 협약기간 밖 집행, 과제와 무관한 지출, 친족 간 거래: 영수증만으로 확인 불가 — "확인필요".
"""

# 정산보고서(여러 영수증) 일괄 검토 시 비목별 계상비율 캡 검증용 (guiideline.pdf "Ⅲ. 창업탐색비 항목별 집행기준" 명시 수치).
# total_budget(전체 창업탐색비) 입력 시에만 검증 가능 — 없으면 캡 체크 스킵.
SETTLEMENT_CAP_RULES = [
    {"scope": "main_category", "keys": ["시제품제작비"], "type": "min", "ratio": 0.5,
     "label": "시제품제작비는 전체 창업탐색비의 50% 이상 계상해야 함"},
    {"scope": "main_category", "keys": ["활동비"], "type": "max", "ratio": 0.5,
     "label": "활동비는 전체 창업탐색비의 50% 이내"},
    {"scope": "main_category", "keys": ["기타 사업운영 경비"], "type": "max", "ratio": 0.5,
     "label": "기타 사업운영 경비는 전체 창업탐색비의 50% 이내"},
    {"scope": "combined", "keys": ["활동비", "기타 사업운영 경비"], "type": "max", "ratio": 0.5,
     "label": "활동비+기타 사업운영 경비 합산이 전체의 50% 이상이 될 수 없음"},
    {"scope": "sub_item", "keys": ["기자재구입비"], "type": "max", "ratio": 0.2,
     "label": "기자재구입비는 전체 창업탐색비의 20% 이내"},
]

# 절대금액 캡 (guiideline.md 원문 정독 조사 결과, document 대화 기록 참고).
# SETTLEMENT_CAP_RULES(비율 캡: 여러 영수증 합계 대비 %)와는 판정 단위(건당/일당 실금액)와
# 필요 입력(등급 등)이 달라 별도 리스트로 분리한다.
#
# sub_items는 RECEIPT_CATEGORY_TAXONOMY / GEMINI_RECEIPT_CLASSIFY_MODEL이 실제로 내놓는
# sub_item 문자열과 정확히 일치할 때만 매칭한다(부분일치 금지) — 애매하면 unknown으로
# 떨어지는 게 잘못된 규칙을 들이대는 것보다 안전하다(false positive 금지 원칙).
#
# ⚠ 한계: 전문가활용비 규칙(장기자문/단기자문)은 sub_item="전문가활용비"만으로는
# 어느 쪽인지 분류 단계가 구분하지 않는다(taxonomy에 장기/단기 구분 없음). 장기자문 최소액
# (C급 550,000원)이 단기자문 최대 한도(A급 300,000원)보다 훨씬 커서, "전문가활용비"라는
# 이름만 보고 단기 캡을 들이대면 정상적인 장기자문 지급까지 위반으로 오탐한다. 그래서 아래
# 규칙은 "전문가활용비(단기자문)"라는, 지금 분류 단계가 실제로는 내놓지 않는 구체 라벨에
# 걸어뒀다 — 즉 함수/규칙 자체는 완성돼 있지만, 분류 단계가 장기/단기를 구분해서 내놓기
# 전까지는 자동 파이프라인에서 항상 unknown으로 떨어진다(오탐 방지가 자동 적용보다 우선).
ABSOLUTE_CAP_RULES = [
    {
        "id": "expert_short_term",
        "label": "전문가활용비(단기자문) 회당 한도",
        "sub_items": ["전문가활용비(단기자문)"],
        "unit": "1회",
        "type": "금지형",
        "grade_dependent": True,
        "default_grade": "A",
        "limits": {"A": 300_000, "B": 250_000, "C": 200_000},
        "source": {
            "location": "manual/output/guiideline.md L100-108",
            "quote": "전문가 활용비는 크게 장기자문, 단기자문으로 나뉘며, 각각의 지급한도 금액은 다음과 같다. "
                     "[단위: 천원] 단기자문(회당, 월 최대 3회) — A급 300 이하 / B급 250 이하 / C급 200 이하",
        },
    },
    {
        "id": "other_ops_committee_referral",
        "label": "기타 사업운영 경비 1회당 100만원 이상 → 심의위원회 회부",
        # 기타 사업운영 경비 산하 sub_item 전부. RECEIPT_CATEGORY_TAXONOMY(config.py L119)의
        # 국내여비 표기를 그대로 사용 — 세부항목(식비 등)이 분류 단계에서 나오면 아래 더 구체적인
        # 규칙(travel_daily_allowance/travel_meal_allowance)이 우선 적용되고 이 규칙은 안 걸린다.
        "sub_items": ["창업탐색추진비", "소모품비", "문헌구입비", "일반수수료",
                      "국내여비(운임/숙박비/식비/일비)"],
        "unit": "1회",
        "type": "절차형",
        "grade_dependent": False,
        "limits": {"ALL": 1_000_000},
        "source": {
            "location": "manual/output/guiideline.md L206",
            "quote": "기타 사업운영 경비가 1회당 100만원 이상인 경우 심의위원회에 회부하여 지급 결정하도록 한다.",
        },
    },
    {
        "id": "travel_daily_allowance",
        "label": "국내여비 일비 한도",
        # taxonomy가 실제로 이 구체 라벨을 내놓는지 불확실(위 한계 설명 참고) — 나오면 바로 걸림.
        "sub_items": ["국내여비(일비)"],
        "unit": "1일",
        "type": "금지형",
        "grade_dependent": False,
        "limits": {"ALL": 20_000},
        "source": {
            "location": "manual/output/guiideline.md L279-286",
            "quote": "[국내 여비 정액표](단위: 원) 일비(1일당) — A급 20,000 / B급,C급 20,000",
        },
    },
    {
        "id": "travel_meal_allowance",
        "label": "국내여비 식비 한도",
        "sub_items": ["국내여비(식비)"],
        "unit": "1일",
        "type": "금지형",
        "grade_dependent": True,
        "default_grade": "A",
        "limits": {"A": 25_000, "B": 20_000, "C": 20_000},
        "source": {
            "location": "manual/output/guiideline.md L279-286",
            "quote": "[국내 여비 정액표](단위: 원) 식비(1일당) — A급 25,000 / B급,C급 20,000",
        },
    },
]

# 컴플라이언스가 override_flag="지원불가"를 낼 때, 인용한 조항에 아래 표현 중 하나가
# 실제로 포함돼야만 override를 인정한다(pipeline.py에서 검사).
# LLM이 "제출서류 표"를 금지 조항으로 오인해 override를 낸 사례가 있어 코드로 게이트한다.
# "~할 수 있다", "~를 원칙으로 한다" 같은 재량 표현은 금지가 아니므로 목록에 넣지 마라.
PROHIBITION_MARKERS = [
    "지급하지 아니한다",
    "지원되지 않으며",
    "지원되지 않는다",
    "청구할 수 없다",
    "집행 불가",
    "집행이 불가",
    "구매가 불가능",
    "계상할 수 없다",
    "지급불가",
    "지급 불가",
    "사용할 수 없다",
]

# 미구현(근거 있음, 판정에 필요한 데이터가 지금 파이프라인에 없어 보류) — 대충 채우지 않는다.
#
# · 전문가활용비(장기자문): "월당, 최소금액 기준 월 4회이상"이라는 빈도 조건이 얽혀 있어
#   영수증 금액만으로는 그 조건 충족 여부를 판정할 수 없다.
#   원문(L100-108): "장기자문(월당, 최소금액 기준 월 4회이상) — A급 1,000~1,200 / B급 800~1,000 / C급 550~800 [단위: 천원]"
#
# · 창업탐색추진비: 캡이 팀원 참여율 점수(①EL·EM 참여율 평균 ②PM/PI 정성평가, 산출공식
#   (①+②)÷2)에 의존한다 — 영수증에 없는 외부 평가자료가 있어야 한도 자체를 계산할 수 있어
#   단건 판정이 원천적으로 불가능하다.
#   원문(L210): "창업탐색팀 구성원 1인당 월30만원 한도의 창업탐색추진비를 지급하며..."
#
# · 소모품비 총 100만원 한도: 사업기간 전체 누적 총액 기준이라 단일 영수증 스코프를 벗어난다.
#   review_settlement(배치) 쪽에서 라인아이템 합산이 붙어야 검증 가능 — 별도 작업.
#   원문(L230): "'소모품비'란... (총100만원 한도 내에서 집행 가능)"
#
# · 국내여비 숙박비: (a) B/C급은 지역(서울/광역시/그 밖의 지역)까지 필요한데 현재 추출
#   단계가 지역을 뽑지 않고, (b) A급은 애초에 "실비"(정액 상한 자체가 없음)라 "등급 없으면
#   가장 관대한 등급(A급) 기본값" 전략 자체가 성립하지 않는다(상한이 없는 걸 기본값으로 못 씀).
#   그래서 sub_items 목록에 아예 안 올려뒀다 — 매칭되는 규칙이 없으므로 check_absolute_cap이
#   자동으로 unknown을 반환한다(별도 처리 코드 불필요).
#   원문(L279-289): "숙박비(1야당) A급 실비 / B급,C급 실비* ... * B급, C급 숙박비 상한액:
#   서울특별시 70,000, 광역시 60,000, 그 밖의 지역은 50,000" /
#   "상한액을 초과하여 여비를 지출하였을 때에는 숙박비의 10분의 3을 넘지 아니하는 범위에서
#   여비를 추가로 지급할 수 있다."

GEMINI_RECEIPT_CLASSIFY_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction=f"""
# Role
실험실창업탐색팀 창업탐색비 비목 분류 전문가.

# 비목 목록 (아래 목록에서만 골라라. 목록에 없는 명칭을 지어내지 마라)
{RECEIPT_CATEGORY_TAXONOMY}

# Rules
1. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.
2. flag가 "지원불가"인 경우: main_category와 sub_item을 모두 "해당없음"으로 표기하라.
   목록에 있는 비목명에 억지로 끼워맞추지 마라(예: 회의 목적 식비를 "창업탐색추진비"나
   "국내여비(식비)"로 분류하지 말 것 — 그 항목들은 다른 목적의 지출을 위한 것이지
   회의비의 대체 명칭이 아니다).

3. flag가 "정상"인 경우: main_category는 "시제품제작비"/"활동비"/"기타 사업운영 경비"
   중 하나, sub_item은 위 목록의 세부항목명 중 하나를 그대로 사용하라.
   flag가 "확인필요"인 경우: 비목이 특정되면 위와 같이 표기하고, 영수증 정보만으로는
   어느 비목인지 특정할 수 없으면 main_category와 sub_item을 "해당없음"으로 두어라.
   비목을 특정할 수 없다는 것 자체가 확인이 필요한 사유다.

4. flag 판정 기준 — 아래 순서로 적용한다.
   4-1. "지원불가"는 영수증에 실제로 인쇄된 사실만으로 금지 조항에 걸릴 때만 쓴다.
        (예: 상품명이 주류·귀금속류, 결제일이 협약기간 밖, 품목이 명백한 범용성 기자재)
        영수증에 없는 정황을 추정해서 "지원불가"로 판정하지 마라.
   4-2. 판단 근거에 다음 표현이 들어간다면 그것은 "지원불가"가 아니라 "확인필요"다:
        "~로 추정된다", "~로 간주된다", "~로 보인다", "~일 가능성이 높다",
        "증빙이 없으므로", "목적이 명시되지 않았으므로", "불명확하므로"
        증빙이 없다는 것은 지급 불가의 근거가 아니라 확인이 필요하다는 근거다.
   4-3. 식당·카페·편의점 영수증에는 그 지출이 회의 목적이었는지 여부가 인쇄되지 않는다.
        따라서 회의비 금지 조항만을 근거로 "지원불가"를 판정할 수 없다.
        "확인필요"로 하고, reasoning에 무엇을 확인해야 하는지(회의 목적 여부, 출장 여부,
        참석자 등) 구체적으로 적어라.
   4-4. "정상"은 영수증 정보만으로 비목과 집행 적정성이 모두 확인될 때만 쓴다.
   4-5. 위 어디에도 확신이 없으면 "확인필요"가 기본값이다.

5. confidence는 판단 확신도(high/medium/low).
   reasoning에 4-2의 추정 표현이 하나라도 들어갔다면 "high"를 쓰지 마라.

{{"main_category": "대분류명|해당없음", "sub_item": "세부항목명|해당없음", "flag": "정상|지원불가|확인필요", "confidence": "high|medium|low", "reasoning": "판단 근거 설명"}}
""",
)

GEMINI_RECEIPT_COMPLIANCE_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction="""
# Role
연구비 집행 컴플라이언스 검토 전문가. 이미 분류된 비목이 실제 규정 기준(한도, 필요서류, 절차)에 맞게 집행됐는지 검토한다.

# Rules
0. [분류 결과]의 flag가 "지원불가"면 애초에 지급 대상이 아닌 항목이다 — 사전결재/참석자명단 등 증빙 구비 여부와 무관하게 compliance_status를 "위반의심"으로 판정하고, compliance_notes에 왜 지급 대상 자체가 아닌지(분류 단계의 지원불가 사유)를 적어라. 이 경우엔 "확인불가"로 흐리지 마라 — 증빙이 갖춰져도 애초에 지급 불가인 항목이다.
1. flag가 "정상" 또는 "확인필요"인 경우에만 아래 2번부터 적용한다. 오직 제공된 [참고 규정]만 근거로 판단하라. 영수증 정보만으로 확인 불가능한 항목(예: 사전 결재 여부, 참석자 명단)은 "확인불가"로 명시하고 무엇이 더 필요한지 적어라.
2. [분류 결과]의 flag가 "정상" 또는 "확인필요"라도, [참고 규정]에 이 지출을
   명시적으로 금지하는 조항이 있고 그 조항이 이 영수증에 직접 적용된다면
   compliance_status를 "위반의심"으로 판정하고 override_flag를 "지원불가"로 설정하라.
   분류 단계는 규정을 검색하지 않으므로, 규정에 근거한 금지 판단은 이 단계의 책임이다.

   "명시적 금지"란 규정 원문에 다음과 같은 단정적 금지 표현이 있는 경우를 말한다:
     "지급하지 아니한다", "지원되지 않으며", "청구할 수 없다", "집행 불가",
     "구매가 불가능하다", "계상할 수 없다", "지급불가"
   "~할 수 있다", "~를 원칙으로 한다", "필요시" 같은 재량·조건 표현은 금지가 아니다.

   "직접 적용"이란 조항이 금지하는 대상과 이 영수증의 지출 대상이 같다는 뜻이다.
   예: 조항이 "유류비는 지원되지 않으며"인데 영수증이 주유소 휘발유 결제 → 직접 적용.
   조항이 다른 비목에 관한 것이거나 적용 여부를 추정해야 한다면 override_flag는 null로 두어라.

   override_flag를 설정할 때는 citation에 그 금지 조항 원문을 그대로 인용하라.
   금지 조항을 찾지 못했거나 적용이 불확실하면 override_flag는 반드시 null이다.
3. 규정에 명시된 금액 한도가 있으면 영수증 금액과 비교하여 초과 여부를 판단하라.
4. 문서 우선순위: 각 참고 규정엔 등급(tier, rank)이 표시된다. rank 숫자가 작을수록 법적으로 상위(법률 > 시행령 > 시행규칙 > 법령해설_매뉴얼 > 고시/훈령/예규 > 사업지침_운영요강). 사업 범위 안에서 다루는 사안은 원칙적으로 rank가 더 큰(하위) 사업지침을 우선 적용하되, rank가 더 작은(상위) 문서에 명시된 금지·의무 조항(강행규정)은 지침 내용보다 우선한다. 두 문서 내용이 충돌하면 hierarchy_note에 어느 문서를 우선했는지와 이유를 적어라. 충돌이 없으면 hierarchy_note는 빈 문자열로 둬라.
5. required_documents: [참고 규정]에 해당 비목의 제출서류 목록(예: "참고 1. 창업탐색비 집행관련 제출서류" 표)이 포함돼있으면 그 항목에 해당하는 사전/사후 제출서류를 배열로 추출하라(예: ["[별지6] 검수조서", "[별지9] 예산집행 증빙서류"]). 참고 규정에 해당 비목의 제출서류 정보가 없으면 빈 배열로 둬라. 영수증 이미지만으로 실제 서류가 첨부됐는지 확인하지 마라 — 이 필드는 어떤 서류가 필요한지 안내하는 체크리스트일 뿐, 첨부 여부 판정이 아니다.
6. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.

{"compliance_status": "준수|위반의심|확인불가", "compliance_notes": "판단 설명 (한도초과/서류미비 등 구체적으로)", "citation": "인용 조항", "hierarchy_note": "문서 간 충돌 시 우선순위 판단 근거, 없으면 빈 문자열", "required_documents": ["필요서류1", "필요서류2"], "override_flag": "지원불가|null"}
""",
)

GEMINI_DOC_MATCH_MODEL = genai.GenerativeModel(
    model_name="gemini-3.5-flash-lite",
    system_instruction="""
# Role
첨부된 증빙서류(이미지 또는 PDF)가 어떤 필요서류 항목에 해당하는지 판정하는 전문가.

# Rules
1. [필요서류 목록]의 각 항목에 대해 [첨부 파일] 중 해당하는 것이 있는지 판정하라.
2. status 판정 기준:
   - "matched": 해당 서류가 첨부 파일 중에 명확히 존재
   - "missing": 첨부 파일 어디에도 해당 서류가 없음
   - "unclear": 비슷한 서류가 있으나 확실치 않음 / 품질 문제로 판독 불가
3. evidence_file에는 매칭된 파일의 파일명을 그대로 적어라. matched가 아니면 null.
4. 한 파일은 하나의 필요서류에만 배정하라. 여러 항목에 걸칠 수 있으면 가장 적합한 하나만
   matched로 하고 나머지는 unclear로 두고 reason에 사유를 적어라.
5. 목록에 없는 서류가 첨부돼있어도 무시하라. 판정 대상은 [필요서류 목록]뿐이다.
6. 반드시 아래 JSON 형식으로만 답하라. 설명이나 코드블록 없이 JSON 객체 하나만 출력하라.

{"document_match": [{"document": "필요서류명", "status": "matched|missing|unclear", "evidence_file": "파일명|null", "confidence": "high|medium|low", "reason": "판단 근거"}]}
""",
)

GEMINI_CONFIG = genai.types.GenerationConfig(temperature=0.0, max_output_tokens=65536)

QDRANT_PATH = os.getenv("QDRANT_PATH", "")
if QDRANT_PATH:
    qdrant_client = QdrantClient(path=QDRANT_PATH)
else:
    qdrant_client = QdrantClient(host="qdrant", port=6333)
