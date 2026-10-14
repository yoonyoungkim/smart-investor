# 가치주 / 배당주 추천 분리 — 구현 계획

작성일: 2026-08-16 · 기준: 테스트 242개 통과 / 커버리지 56%

## 요약

조건을 넣고 빼는 구조(`filters/registry.py` + `filters/config.py`)는 이미 있으므로
**전략 분리 자체는 설정 파일 2개로 끝납니다.** 실제 작업량은 대부분
**가치 지표(PER·PBR·ROE 등)가 아직 계산·저장되지 않는다**는 데서 나옵니다.

현재 8개 조건은 전부 배당·안정성 지표입니다. 밸류에이션 지표는 하나도 없습니다.

---

## 1. 현재 보유 데이터 (실측)

`global_fs` 계정별 보유 종목 수:

| 계정 | 미국 | 한국 | 비고 |
|------|-----:|-----:|------|
| Total Revenue | 5,938 | 2,578 | |
| Operating Income | 4,943 | 2,626 | |
| Net Income | 5,937 | 2,621 | |
| Total Assets | 6,223 | 2,626 | |
| **Stockholders Equity** | **6,220** | **0** | ← 미국만 |
| **Total Equity** | **0** | **2,626** | ← 한국만 |
| Total Liabilities | 0 | 2,626 | 미국은 자산-자본으로 유도 |
| EBIT / EBITDA | 5,044 / 4,942 | 0 | 한국 없음 |
| Basic EPS | 5,708 | 0 | 한국 없음 |
| **Ordinary Shares Number** | **6,209** | **0** | 한국 없음 |
| Free Cash Flow | 5,847 | 0 | 한국 없음 |

시가총액:

| | 미국 | 한국 |
|---|---|---|
| `global_ticker.Market Cap` | 8 / 7,062 (사실상 없음) | 2,763 / 2,763 ✅ |
| 대체 산출 | 발행주식수 × 주가 ✅ | 저장값 사용 ✅ |

**결론: 양쪽 모두 PER·PBR·ROE 산출이 가능합니다.** 경로만 다릅니다.

- 미국: `Ordinary Shares Number × Close` → 시총, `Stockholders Equity` → 자본
- 한국: `global_ticker.Market Cap` → 시총, `Total Equity` → 자본

산출 검증 (저장 데이터만 사용):

```
GLPI  시총  12.3B  PER 14.95  PBR 2.67  ROE 17.83%
KIM   시총  16.5B  PER 28.14  PBR 1.58  ROE  5.63%
AU    시총  48.6B  PER 18.45  PBR 6.01  ROE 32.58%
```

---

## 2. 선행 과제 — 계정명 불일치

**미국은 `Stockholders Equity`, 한국은 `Total Equity`로 자본총계가 저장되어 있습니다.**
어느 한쪽 이름만 조회하면 **다른 시장 전체가 조용히 탈락**합니다. 이번 대화에서
`Interest Expense`(한국은 `금융비용`만 공시) 때 겪은 것과 같은 유형입니다.

처리 방안 (권장: B):

| 안 | 내용 | 평가 |
|---|---|---|
| A | 한국 수집기를 `Stockholders Equity`로 통일 | 재수집 필요, 기존 행과 혼재 |
| **B** | **계산기가 두 이름을 폴백 조회** (`Total Debt` → `Total Liabilities` 방식과 동일) | **재수집 불필요, 기존 폴백 패턴과 일관** |

같은 성격의 폴백이 이미 있습니다: `EBIT` → `Operating Income`, `Interest Expense` → `Finance Costs`.

---

## 3. 단계별 작업

### Phase 1 — 가치 지표 산출 (핵심)

`analysis/calculator.py`에 지표 추가, `global_value`에 저장.

| 지표 | 산식 | 미국 | 한국 |
|------|------|:---:|:---:|
| `PER` | 시총 ÷ 당기순이익 | ✅ | ✅ |
| `PBR` | 시총 ÷ 자본총계 | ✅ | ✅ |
| `PSR` | 시총 ÷ 매출액 | ✅ | ✅ |
| `ROE` | 당기순이익 ÷ 자본총계 × 100 | ✅ | ✅ |
| `OPM` | 영업이익 ÷ 매출액 × 100 | ✅ | ✅ |
| `EV_EBITDA` | (시총 + 순부채) ÷ EBITDA | ✅ | ❌ EBITDA 없음 |
| `MKTCAP` | 시총 (파생값 캐시) | ✅ | ✅ |

- **적자 기업의 PER/PBR은 `None`** — 음수 지표가 정렬 시 "저평가"로 올라오는 것을 막습니다.
  (P/E 리포트에서 이미 같은 처리를 했습니다.)
- 한국 시총은 `global_ticker.Market Cap` 스냅샷이라 티커 재수집 시점 기준입니다.
  주가 변동을 반영하려면 `collect_all_tickers.py`를 주기적으로 돌려야 합니다.

작업량: 계산기 메서드 6개 + `_INDICATOR_TO_METRIC` 확장 + 테스트

### Phase 2 — 가치 조건 등록

`filters/criteria.py`에 클래스 추가 → `filters/registry.py`에 등록.
기존 8개와 동일한 `check()` / `describe()` 인터페이스라 엔진 수정은 없습니다.

| 조건 키 | 기본 임계값 | 근거 |
|---------|------------|------|
| `per` | ≤ 15.0 | Graham 기준 |
| `pbr` | ≤ 1.5 | Graham 기준 |
| `graham_number` | PER × PBR ≤ 22.5 | Graham 복합 기준 |
| `roe` | ≥ 10.0% | 자본효율 하한 |
| `operating_margin` | ≥ 5.0% | 수익성 하한 |

`FinancialMetrics`에 `per`/`pbr`/`roe`/`operating_margin` 필드 추가
(이미 선언만 되어 있고 아무도 채우지 않는 `per`/`pbr` 필드가 있으므로 그것을 활용).

작업량: 조건 클래스 5개 + 등록 + 테스트

### Phase 3 — 전략 프리셋

```
configs/dividend.json   # 기존 8개 조건 (현행 default.json 과 동일)
configs/value.json      # per, pbr, roe, operating_margin, debt_ratio, quick_ratio
```

가치주 프리셋에서 배당 조건 3개를 빼고 밸류에이션 조건을 넣습니다.
부채비율·당좌비율은 양쪽 공통(재무 건전성)입니다.

작업량: JSON 2개 (코드 변경 없음)

### Phase 4 — 리포트 분리

`recommend_stocks.py`에 `--strategy {dividend,value}` 추가.
프리셋 자동 선택 + 리포트 제목·파일명·Slack 메시지에 전략 표기.

```bash
python scripts/recommend_stocks.py --strategy dividend --market KR --excel --notify slack
python scripts/recommend_stocks.py --strategy value    --market US --excel --notify slack
```

엑셀 컬럼도 전략에 따라 달라집니다:

| 전략 | 지표 컬럼 |
|------|-----------|
| 배당주 | Div Yield, Div Years, Debt Ratio, Quick Ratio (현행) |
| 가치주 | PER, PBR, ROE, OPM, Debt Ratio |

작업량: CLI 옵션 + 컬럼 세트 분기 + 테스트

---

## 4. 순서와 예상 규모

```
Phase 1 (지표)  ──> Phase 2 (조건) ──> Phase 3 (프리셋) ──> Phase 4 (리포트)
   가장 큼            중간              작음               중간
```

Phase 1 안에 **선행 과제(계정명 폴백)** 를 포함해 먼저 처리합니다.
Phase 3까지 끝나면 `--config configs/value.json`으로 이미 사용 가능하고,
Phase 4는 편의성 개선입니다.

재수집은 **필요 없습니다.** 모든 지표가 이미 저장된 데이터에서 나옵니다.

---

## 5. 확인이 필요한 결정

1. **가치 조건 임계값** — 위 표는 Graham 기준입니다. 한국 시장은 PBR이 전반적으로
   낮아 `PBR ≤ 1.5`면 통과 종목이 과다할 수 있습니다. 실행 후 분포를 보고
   조정하는 편이 실용적입니다 (임계값은 `--set`으로 즉시 변경 가능).

2. **가치주에 배당 조건을 넣을지** — "배당도 주는 가치주"를 원하시면
   `dividend_yield`를 낮은 임계값(예 2%)으로 포함할 수 있습니다.

3. **리포트 전달 방식** — 전략별 별도 메시지·파일 vs 한 파일에 시트 2개.

---

## 6. 범위 밖

- 업종 상대 밸류에이션(동종업계 PER 대비) — `Industry`가 DB에 없고 리포트 시점에만 조회됨
- EV/EBITDA 한국 지원 — DART에서 EBITDA를 직접 공시하지 않아 감가상각비 별도 수집 필요
- 백테스트로 전략 성과 비교 — 지표 이력이 축적된 이후
