# PR 리스크 리뷰 & 자동 머지

PR이 열리거나 푸시되면 GitHub Actions(`.github/workflows/pr-risk-review.yml`)가 diff를 채점해 PR에 코멘트를 달고, 점수에 따라 머지/보류/차단합니다.

## 점수 (0~100, 높을수록 위험)

| 축 | 만점 | 계산 |
|---|---:|---|
| 보안 | 30 | LLM(Claude) 판단. 민감 경로(`.github`, `.env`, auth/secret 등)가 바뀌면 최소 10점 |
| 스코프 | 20 | 파일 수·변경 라인 수. 5파일/100줄 ≈ 0점, 30파일/2000줄 = 만점 |
| Breaking change | 20 | LLM 판단 (API 시그니처, 스키마, 환경변수, deprecated) |
| 테스트 커버리지 | 15 | 소스 변경 대비 테스트 추가 라인 비율(0.5 이상이면 0점). 테스트 삭제 시 +5 |
| 마이그레이션 | 15 | DB 모델 변경인데 마이그레이션 없음 = 15, 마이그레이션 스크립트 = 10, 환경변수·의존성·docker 변경 +5 |

## 동작

| 조건 | 동작 |
|---|---|
| 총점 ≤ 30, 하드스톱 없음, `pytest` 체크 성공 | squash 머지 + 브랜치 삭제 (`risk:low`) |
| 31 ~ 60 | 코멘트만, 사람이 승인 (`risk:medium`) |
| ≥ 61 또는 LLM blocker | 체크 실패(머지 차단) (`risk:high`) |

하드스톱(점수와 무관하게 자동 머지 안 함): `.github/`·`.claude/` 변경, diff가 너무 커서 다 못 본 경우, LLM 호출 실패, 포크 PR.

## 보안 설계

- `pull_request_target`으로 **base 브랜치의 워크플로·스크립트**를 실행합니다. PR이 심사 로직을 바꿔 자기 자신을 통과시킬 수 없습니다.
- PR 코드는 체크아웃·실행하지 않고 API로 diff만 읽습니다. diff는 LLM에 신뢰할 수 없는 데이터로 전달됩니다.
- 프롬프트 인젝션으로 LLM 점수를 낮춰도 결정적 점수·하한·하드스톱·CI가 남습니다.
- 머지 요청에 검토한 head SHA를 넣어, 채점 후 새 커밋이 올라오면 머지되지 않습니다.

## 설정

1. 저장소 Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY` 추가
2. Settings → Actions → General → Workflow permissions: **Read and write**
3. (권장) Settings → Branches에서 `main`에 `pytest`·`risk-review` 체크 필수 지정
4. 임계값·모델은 워크플로의 `AUTO_MERGE_MAX`, `BLOCK_MIN`, `RISK_REVIEW_MODEL` 환경변수로 조정

API 키가 없으면 LLM 축은 채점되지 않고 모든 PR이 사람 승인으로 넘어갑니다.

## 로컬 테스트

```bash
pytest tests/test_risk_review.py -o addopts=""
```
