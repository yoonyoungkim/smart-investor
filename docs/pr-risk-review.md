# PR 코드리뷰 · 리스크 리뷰 · 자동 머지

PR이 열리거나 푸시되면 GitHub Actions(`.github/workflows/pr-risk-review.yml`)가 아래 순서로 처리합니다.

```
1. 코드리뷰 (LLM)
   ├─ 수정사항 없음           → pass
   ├─ 마이너 (동작 불변)      → 봇이 수정 커밋 푸시 → CI·리뷰가 새 커밋으로 재실행 (이번 실행은 종료)
   └─ 개발자 확인 필요        → 줄 단위 코멘트 + `needs-dev-check` 라벨 → 종료
2. 리스크 판단 (아래 점수)
   ├─ 30 이하, 하드스톱 없음  → pass
   └─ 그 외                   → 코멘트 + `needs-dev-check` 라벨 → 종료
3. 코드리뷰 pass + 리스크 pass + `pytest` 성공 → Approve → squash 머지
   하나라도 아니면 → 코멘트 후 종료
```

### 마이너 수정 규칙 (결정적 검증)

LLM이 제안한 수정은 아래를 모두 만족할 때만 푸시합니다. 하나라도 어기면 개발자 확인으로 넘어갑니다.

- 대상: PR에 포함된 `.py` 또는 `.md/.rst/.txt` 파일. `.github/`·`.claude/`·`.githooks/`·민감 경로(auth, secret 등)는 제외
- `find` 텍스트가 파일에 정확히 한 번 존재, 변경 합계 60줄 이하
- `.py`는 주석·docstring·포맷만 바뀌어야 함: 수정 전후 AST(docstring 제외)가 같아야 통과 (문자열 리터럴, import 삭제 등은 거부)
- PR당 자동 수정 커밋 최대 2회(`[bot-review-fix]` 표식), `BOT_PUSH_TOKEN`이 없으면 푸시하지 않음


## 점수 (0~100, 높을수록 위험)

| 축 | 만점 | 계산 |
|---|---:|---|
| 보안 | 30 | LLM(Claude) 판단. 민감 경로(`.github`, `.env`, auth/secret 등)가 바뀌면 최소 10점 |
| 스코프 | 20 | 파일 수·변경 라인 수. 5파일/100줄 ≈ 0점, 30파일/2000줄 = 만점 |
| Breaking change | 20 | LLM 판단 (API 시그니처, 스키마, 환경변수, deprecated) |
| 테스트 커버리지 | 15 | 소스 변경 대비 테스트 추가 라인 비율(0.5 이상이면 0점). 테스트 삭제 시 +5 |
| 마이그레이션 | 15 | DB 모델 변경인데 마이그레이션 없음 = 15, 마이그레이션 스크립트 = 10, 환경변수·의존성·docker 변경 +5 |

## 리스크 점수에 따른 동작

| 조건 | 동작 |
|---|---|
| 총점 ≤ 30, 하드스톱 없음, `pytest` 체크 성공 | squash 머지 + 브랜치 삭제 (`risk:low`) |
| 31 ~ 60 | 코멘트만, 사람이 승인 (`risk:medium`) |
| ≥ 61 또는 LLM blocker | 체크 실패(머지 차단) (`risk:high`) |

하드스톱(점수와 무관하게 자동 머지 안 함): `.github/`·`.claude/`·`.githooks/` 변경, diff가 너무 커서 다 못 본 경우, LLM 호출 실패, 포크 PR. LLM 실패 사유는 PR 코멘트의 `LLM errors`에 표시됩니다.

## 보안 설계

- `pull_request_target`으로 **base 브랜치의 워크플로·스크립트**를 실행합니다. PR이 심사 로직을 바꿔 자기 자신을 통과시킬 수 없습니다.
- PR 코드는 체크아웃·실행하지 않고 API로 diff만 읽습니다. diff는 LLM에 신뢰할 수 없는 데이터로 전달됩니다.
- 프롬프트 인젝션으로 LLM 점수를 낮춰도 결정적 점수·하한·하드스톱·CI가 남습니다.
- 머지 요청에 검토한 head SHA를 넣어, 채점 후 새 커밋이 올라오면 머지되지 않습니다.

## 설정

### 1. LLM 인증 (둘 중 하나)

| 방식 | Secret 이름 | 발급 | 과금 |
|---|---|---|---|
| A. API 키 | `ANTHROPIC_API_KEY` | [Claude Console](https://platform.claude.com)에서 API 키 생성 | API 토큰 사용량 |
| B. 구독 로그인 | `CLAUDE_CODE_OAUTH_TOKEN` | 로컬 터미널에서 `claude setup-token` 실행 → 브라우저에서 승인 → 터미널에 출력된 토큰 복사 | Claude 구독(Pro/Max/Team/Enterprise) 사용량 |

- 둘 다 있으면 API 키가 우선입니다. 둘 다 없으면 LLM 축은 채점되지 않고 모든 PR이 사람 승인으로 넘어갑니다.
- B의 토큰은 1년짜리이며 `setup-token`은 저장하지 않고 출력만 합니다. 모델 요청만 가능합니다. 발급한 사람의 구독에 묶이고 구독 한도를 소모합니다.
- B는 워크플로가 Claude Code CLI(`npm i -g @anthropic-ai/claude-code@2`)를 설치해 `claude -p`로 채점합니다. 도구를 모두 끄고(`--tools ""`) 빈 임시 폴더에서 실행하며, 환경에는 토큰만 전달합니다(`GITHUB_TOKEN` 미전달). 토큰을 채팅이나 코드에 붙여넣지 마세요.
- Secret 등록: 저장소 Settings → Secrets and variables → Actions → New repository secret

### 2. 자동 수정 푸시·승인용 설정

- `BOT_PUSH_TOKEN` (선택): `contents: write` 권한의 fine-grained PAT(이 저장소 한정). 기본 `GITHUB_TOKEN`으로 푸시하면 CI가 다시 돌지 않으므로 PAT가 필요합니다. 없으면 마이너 수정도 개발자 확인으로 처리됩니다.
- Approve: Settings → Actions → General → **Allow GitHub Actions to create and approve pull requests** 체크. 꺼져 있으면 승인은 건너뛰고 머지는 계속 진행합니다.
- 라벨 `needs-dev-check`는 개발자 확인이 필요할 때 붙고, 통과하면 제거됩니다.

### 3. 나머지

1. Settings → Actions → General → Workflow permissions: **Read and write**
2. (권장) Settings → Branches에서 `main`에 `pytest`·`risk-review` 체크 필수 지정
3. 임계값·모델은 워크플로의 `AUTO_MERGE_MAX`, `BLOCK_MIN`, `RISK_REVIEW_MODEL` 환경변수로 조정

## 로컬 테스트

```bash
pytest tests/test_risk_review.py -o addopts=""
```
