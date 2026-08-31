# eval/ — 평가셋과 측정 도구

영수증 판정 파이프라인을 채점하고, 실패 원인을 국소화하는 도구.

## 전제

앱이 떠 있어야 한다. 레포/venv/도커 구성과 무관하게 HTTP로만 호출한다.

```bash
curl http://localhost:5000/          # 앱
curl http://localhost:6333/collections  # Qdrant
```

## 파일

| 파일 | 역할 |
|---|---|
| `labels_prefilled.csv` | 31장 정답 라벨 (`file` 컬럼이 이미지 파일명) |
| `labels_nonreceipt.csv` | 비영수증 negative set 37장 정답 라벨 (`.venv`에 우연히 섞여있던 라이브러리 샘플 이미지) |
| `run_eval.py` | 채점. 다수결 베이스라인 · macro recall · 건별 판정 근거 출력. `is_receipt` 오탐(실제 영수증을 거절)도 함께 검사 |
| `run_eval_nonreceipt.py` | `is_receipt` 거절 채점. `run_eval.py`와 달리 `.venv`를 필터링하지 않고 인덱싱한다 |
| `variance_probe.py` | 같은 이미지를 N회 태워 **단계별 동일성** 비교. 분산이 어느 단계에서 시작하는지 국소화 |
| `survey_all.py` | 미검토 사진을 태워 분포만 확인 (평가셋 확장 여지 판정용) |

**영수증 이미지는 커밋하지 않는다.** 실물이라 개인정보가 들어 있다.
`--images`로 로컬 경로를 지정한다.

## 사용

```bash
# 채점 (1회)
python eval/run_eval.py --api http://localhost:5000 \
  --labels eval/labels_prefilled.csv --images <영수증 폴더>

# 분산 확인 — 같은 이미지 3회, 단계별 동일성
python eval/variance_probe.py --api http://localhost:5000 \
  --labels eval/labels_prefilled.csv --images <영수증 폴더> --ids r001 r002 r004

# 미검토 사진 분포 조사
python eval/survey_all.py --api http://localhost:5000 \
  --exclude eval/labels_prefilled.csv --images <영수증 폴더>

# 비영수증 거절(is_receipt) 채점 — .venv가 들어있는 폴더를 --images로 지정
python eval/run_eval_nonreceipt.py --api http://localhost:5000 --images <.venv 상위 폴더>
```

`run_eval.py`와 `survey_all.py`는 결과를 jsonl에 append하므로 중간에 죽어도 이어서 실행된다.
실패한 건은 재실행 시 자동 재시도된다.

## 판정 기준

**개선은 3회 반복으로만 인정한다.** 1회 측정 결과로 채택/롤백을 판단하지 마라.

```
채택 조건: 3회 최솟값 > 이전 3회 최댓값
```

동일 코드로 3회 돌렸을 때 macro recall이 48~82%로 흔들린 적이 있다.
그 34%p 안에서 네 번의 수정을 "개선/악화"로 잘못 판정했다.
(`document/FINDINGS_2026-08-28_variance.md` 참조)

## 보는 순서

```
1. 단일 클래스 수렴 검사   출력 종류가 1개면 붕괴. 정확도가 높아도 성능이 아니다
2. macro recall           클래스 불균형에 눌리지 않는 값. 판정은 이것으로
3. 클래스별 재현율         어느 클래스를 놓치는가
4. override 효과 / 게이트  분류가 맞춘 것과 컴플라이언스가 구제한 것을 분리
5. 판정 근거              집계값이 같아도 구성이 다르면 여기서 드러난다
```

`survey_all.py`의 모델 판정을 **정답 라벨로 쓰지 마라.** 후보 선별용이다.
모델 출력을 라벨로 쓰면 시스템이 자기 답을 채점하는 순환이 된다.
