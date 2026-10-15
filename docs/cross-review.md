# 교차 모델 pre-commit 리뷰

커밋을 만든 모델이 자기 코드를 리뷰하지 않도록, **git pre-commit 훅**이 상대 모델의 CLI를 직접 호출해 staged diff를 리뷰합니다.

| 커밋한 주체 | 판별 | 리뷰어 |
|---|---|---|
| Claude Code (Bash 도구 등) | `CLAUDE_CODE_CHILD_SESSION=1` | Antigravity CLI `agy -p` |
| Antigravity, 터미널, IDE 등 그 외 | 위 변수 없음 | Claude CLI `claude -p` |

`CLAUDECODE`는 IDE 확장의 터미널에서도 켜져서 판별에 쓰지 않습니다. `REVIEW_WITH=agy|claude`로 리뷰어를 강제할 수 있습니다.

## 설치 (클론마다 1회, Mac)

```bash
scripts/install_hooks.sh          # git config core.hooksPath .githooks
agy                                # Antigravity에 한 번 로그인 (헤드리스는 캐시된 로그인만 사용)
claude                             # Claude Code에 한 번 로그인
```

## 동작

1. `git commit` 시 staged diff(`commit -a` 포함)를 가져옵니다. 비어 있으면 건너뜁니다.
2. 리뷰어가 JSON(`summary`, `findings[severity, file, line, issue, fix]`)을 반환합니다.
3. `critical`·`important`가 하나라도 있으면 커밋을 막고(exit 1) 지적 내용을 출력합니다. `minor`는 출력만 하고 통과합니다.
4. 리뷰어가 없거나 로그인이 안 됐거나 시간 초과·응답 파싱 실패면 경고만 하고 **커밋을 허용**합니다(커밋 불가 상태 방지).

한 번만 건너뛰기: `SKIP_REVIEW=1 git commit ...`

## 안전장치

- `agy`는 읽기 전용 옵션이 없고 워크스페이스 안에서 파일을 쓸 수 있어서, 요청 파일만 든 **빈 임시 폴더**에서 실행합니다. `claude`는 diff를 stdin으로 받고 도구를 모두 끕니다(`--tools ""`).
- 리뷰어에는 `GIT_*`, `GITHUB_TOKEN`, `GH_TOKEN`을 넘기지 않습니다. diff는 신뢰할 수 없는 데이터로 취급하도록 프롬프트에 명시합니다.
- `.githooks/`는 개발자 PC에서 실행되는 코드라 PR 리스크 리뷰의 하드스톱(자동 머지 불가)입니다.

## 환경변수

| 이름 | 기본 | 설명 |
|---|---|---|
| `SKIP_REVIEW` | - | `1`이면 이번 커밋은 리뷰 생략 |
| `REVIEW_WITH` | 자동 | `agy` 또는 `claude`로 강제 |
| `REVIEW_TIMEOUT` | 300 | 리뷰어 제한 시간(초) |
| `REVIEW_MODEL_AGY` / `REVIEW_MODEL_CLAUDE` | CLI 기본 | `--model`로 전달 |
| `REVIEW_MAX_DIFF` | 100000 | 리뷰어에 보내는 diff 최대 글자 수(초과분 절단) |

## 한계

- 클라우드 세션(저장소 클론에 `core.hooksPath`가 없거나 `agy`가 없는 곳)의 커밋은 리뷰되지 않습니다. 이 경우 PR의 리스크 리뷰가 마지막 방어선입니다.
- `agy`의 JSON 형식·플래그·인증은 공식 문서 기준으로 작성했고 실제 `agy`로는 아직 실행해 보지 않았습니다(테스트는 가짜 CLI 사용).
- Antigravity에는 Claude Code 같은 `PreToolUse` 훅이 확인되지 않아, Antigravity 쪽 강제는 git 훅에 의존합니다.
- 이전의 Claude Code `PreToolUse` 훅(`.claude/hooks/*`)은 이 방식으로 대체되어 제거했습니다.
