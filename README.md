# Smart Investor

배당주 분석 및 필터링 시스템 - 미국/한국 주식 및 ETF 지원

- 버전: 0.2.0 (Alpha)
- Python 3.10+ / MySQL 8.0+
- 테스트: 275개 통과 (커버리지 55%)

## 개요

Smart Investor는 재무 기준을 통해 우량 배당주를 선별하는 시스템입니다.
다음 4단계로 동작하며, 스케줄러가 이 흐름을 자동 실행합니다.

| 단계 | 내용 | 대상 테이블 | 실행 |
|------|------|-------------|------|
| **1. 티커 수집** | 한국/미국 주식·ETF 티커 | `global_ticker`, `global_etf` | `collect_all_tickers.py`, `collect_all_etfs.py` |
| **2. 수치 수집** | 주식의 가격·배당·재무제표 (ETF 제외) | `global_price`, `global_dividends`, `global_fs` | `collect_us_stocks.py`, `collect_kr_stocks.py` |
| **3. 지표 생성** | 수집값에서 DY/DR/QR/ICR 계산 | `global_value` | `calculate_metrics.py` |
| **4. 추천** | 조건을 적용해 종목 선별 (조건 추가·제거 가능) | - | `recommend_stocks.py` |

### 8가지 기본 필터 기준

기준은 고정이 아닙니다 — 각 조건은 키로 등록되어 있어 실행할 때
**넣고 뺄 수 있고 임계값도 바꿀 수 있습니다** ([조건 추가·제거](#조건-추가제거-step-4) 참조).

| # | 필터 | 기준 | 설명 |
|---|------|------|------|
| 1 | 배당수익률 | ≥ 4% | 최근 12개월 정기배당 합계 / 현재가 |
| 2 | 연속 배당 | ≥ 5년 | 연속 배당 지급 년수 |
| 3 | 배당 성장 | 양(+) 기울기 & R² ≥ 0.3 | 최근 5년 연간 배당금 선형회귀 |
| 4 | 영업이익 성장 | 양(+) 기울기 & R² ≥ 0.3 | 최근 3년 영업이익 선형회귀 |
| 5 | 매출 성장 | 양(+) 기울기 & R² ≥ 0.3 | 최근 3년 매출 선형회귀 |
| 6 | 부채비율 | ≤ 200% | Total Debt / Total Assets |
| 7 | 당좌비율 | ≥ 100% | (현금 + 매출채권) / 유동부채 |
| 8 | 이자보상배율 | ≥ 100% | EBIT / 이자비용 |

기본값은 `src/smart_investor/filters/criteria.py`의 클래스 상수로 정의되고,
조건 등록은 `filters/registry.py`, 선택·오버라이드는 `filters/config.py`가 담당합니다.
추세 판정의 R² 임계값은 `MetricsCalculator._is_increasing_trend(min_r_squared=0.3)`입니다.

### 지표 계산 특징

- **특별배당 제외**: 배당수익률 계산 시 중앙값의 2배를 초과하는 배당은 특별배당으로 간주해 제외
  합니다. 단, 제외 대상이 전체의 30%를 넘으면 배당 증액으로 보고 원본을 그대로 사용합니다.
- **추세 판정**: 단순 증감 카운트가 아닌 선형회귀(scipy `linregress`)로 기울기와 R²를 함께 확인합니다.
- **진행 중인 해 제외**: 배당 성장 추세는 **완료된 연도만** 사용합니다. 진행 중인 당해년도는
  배당 횟수가 모자라 합계가 낮게 나오므로, 포함하면 거의 모든 배당성장주가 하락 추세로 판정됩니다.
- **이자비용 없음 처리**: 이자비용이 없는 무차입 기업은 "갚을 이자가 없음"으로 보아 통과시키고,
  재무데이터 자체가 없는 종목은 "판정 불가"로 탈락시킵니다
  (`FinancialMetrics.has_interest_expense`가 `True`/`False`/`None` 3-상태).
- **지표 캐시**: 계산된 `DY`/`DR`/`QR`/`ICR`은 `global_value` 테이블에 날짜별로 저장됩니다.
  `calculate_metrics.py`가 이 값을 채우고, 추천 시 `--use-cache`로 재사용합니다.
  추세 지표(boolean)와 배당 연수는 캐시 대상이 아니라 매번 재계산됩니다.

## 기능

- **미국 주식**: 티커·가격 FinanceDataReader / 배당·재무 yfinance (약 7,000여 종목)
- **한국 주식**: 티커 FinanceDataReader / 가격 pykrx / **배당·재무 DART OpenAPI** (약 2,700여 종목)
- **미국 ETF**: FinanceDataReader 목록 + yfinance 상세 (약 5,500여 종목)
- **한국 ETF**: FinanceDataReader (약 1,100여 종목)
- **조건 구성**: 추천 조건을 JSON 설정이나 CLI 플래그로 넣고 빼고 임계값 조정
- **알림 시스템**: Slack, Telegram, Email (설정된 채널만 자동 활성화)
- **스케줄러**: 평일 18시 일일 스캔, 일요일 10시 주간 리포트 (Asia/Seoul)

> **한국 재무제표·배당은 DART OpenAPI가 필요합니다.** pykrx와 FinanceDataReader는 재무제표를
> 제공하지 않고, pykrx의 배당 API는 존재하지 않습니다. [무료 인증키](https://opendart.fss.or.kr/)를
> 발급받아 `.env`의 `DART_API_KEY`에 설정하세요. 키가 없으면 한국 종목은 가격만 수집되고
> 재무 기반 조건을 통과할 수 없습니다.

> 종목 수는 거래소 상장/폐지에 따라 계속 변합니다. 위 수치는 2026년 8월 기준 조회값입니다.

## 설치

### 요구사항

- Python 3.10+ (3.13까지 지원)
- MySQL 8.0+ (Docker 권장)

### 설치 방법

```bash
cd /Users/tiffany/workspace/smart-investor

# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 개발 모드로 패키지 설치
pip install -e .
```

### 데이터베이스 설정 (Docker)

```bash
# MySQL 컨테이너 실행
docker run -d \
  --name smart-investor-db \
  -e MYSQL_ROOT_PASSWORD=rootpass \
  -e MYSQL_DATABASE=smart_investor \
  -e MYSQL_USER=investor \
  -e MYSQL_PASSWORD=investor123 \
  -p 3306:3306 \
  mysql:8.0
```

### 환경변수 설정

```bash
# .env.example을 복사하여 .env 생성
cp .env.example .env

# .env 파일 수정
vi .env
```

한국 주식을 다루려면 DART 인증키가 필요합니다:

```bash
# https://opendart.fss.or.kr/ 에서 무료 발급 후
DART_API_KEY=발급받은키
```

최초 사용 시 종목코드 매핑표(약 20MB)를 내려받아
`~/.cache/smart-investor/dart_corp_codes.tsv`에 30일간 캐시합니다.

### 데이터베이스 테이블 생성

`.env` 설정 후, 최초 1회 테이블을 생성합니다. ORM 모델(`db/models.py`) 기준으로
없는 테이블만 생성하며, 기존 테이블은 건드리지 않습니다.

```bash
python scripts/init_db.py
```

**기존 DB를 쓰고 있다면** 자연키 유니크 제약을 추가하세요. `init_db.py`의 `create_all`은
이미 있는 테이블을 변경하지 않으므로 별도 마이그레이션이 필요합니다. 멱등적이라 여러 번
실행해도 안전합니다.

```bash
python scripts/migrate_add_unique_constraints.py --dry-run   # 변경 내용 미리보기
python scripts/migrate_add_unique_constraints.py             # 적용
python scripts/migrate_add_unique_constraints.py --dedupe    # 기존 중복이 있을 때
```

## 사용법

### 가상환경 활성화

```bash
cd /Users/tiffany/workspace/smart-investor
source venv/bin/activate
```

### 전체 수집 (한 번에)

개별 스크립트를 순서대로 부르는 대신 `scripts/collect_all.sh`가 전 구간을 실행합니다.
단계마다 체크포인트를 남기므로 **중단되면 다시 실행하는 것만으로 이어서 진행**됩니다.
유니크 제약 덕분에 이미 끝난 단계를 다시 돌려도 중복이 생기지 않습니다.

```bash
# 실행 계획만 확인 (아무것도 실행하지 않음)
./scripts/collect_all.sh --dry-run

# 전체 실행
./scripts/collect_all.sh

# 한쪽 시장만
./scripts/collect_all.sh --market KR
./scripts/collect_all.sh --market US

# 미국 배치를 3개씩 병렬로 (병렬 저장은 유니크 제약으로 안전)
./scripts/collect_all.sh --market US --jobs 3

# 진행 상황 확인
./scripts/collect_all.sh --status

# 체크포인트 무시하고 처음부터
./scripts/collect_all.sh --from-scratch
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--market` | `ALL` | `ALL` / `KR` / `US` |
| `--jobs` | `1` | 미국 배치 병렬 수 (yfinance Rate Limit 고려해 2~3 권장) |
| `--batch` | `1000` | 미국 배치 크기 |
| `--delay` | `0.5` | yfinance 요청 간 딜레이(초) |
| `--days` | `400` | 한국 가격 이력 일수 |
| `--skip-tickers` | off | 티커 수집 단계 건너뛰기 |
| `--status` | - | 완료된 단계 출력 후 종료 |
| `--from-scratch` | off | 체크포인트 삭제 후 처음부터 |
| `--dry-run` | off | 계획만 출력 |

실행 전 DB 연결과 (한국 포함 시) `DART_API_KEY` 존재를 먼저 확인하고, 없으면 긴 작업을
시작하기 전에 중단합니다. 로그는 `logs/collect_all_<타임스탬프>.log`,
체크포인트는 `logs/collect_all.state`에 남습니다.

**예상 소요 시간** (실측 기준)

| 구간 | 시간 | 비고 |
|------|------|------|
| 티커 (KR+US, 주식+ETF) | 2~3분 | FinanceDataReader 일괄 조회 |
| 한국 가격·배당·재무 | 약 35분 | DART 약 17,000콜 (일일 한도 20,000) |
| 미국 전체 (`--jobs 1`) | 약 3시간 50분 | 재무 수집이 대부분 |
| 미국 전체 (`--jobs 3`) | 약 1시간 30분 | Rate Limit 발생 시 딜레이를 올릴 것 |
| 지표 계산 | 2~3분 | DB 연산만 |

> DART 일일 한도가 20,000콜인데 한국 전체가 약 17,000콜을 씁니다. 같은 날 재수집하면
> 한도를 넘길 수 있으니, 실패한 종목만 다시 받으려면 다음 날 실행하세요.
> 한도 초과 시 status `020`이 오고 해당 단계는 실패로 기록되어 재실행 시 이어집니다.

### 미국 주식 수집

`--type` 기본값은 `all`(ticker + price + dividend + financial)입니다.

```bash
# 기본 18개 배당주 수집
python scripts/collect_us_stocks.py

# 특정 종목만 수집
python scripts/collect_us_stocks.py AAPL MSFT GOOGL

# 티커 정보만 수집
python scripts/collect_us_stocks.py --type ticker

# 배당 내역만 수집
python scripts/collect_us_stocks.py --type dividend

# 가격 이력 기간 지정 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max — 기본 1y)
python scripts/collect_us_stocks.py AAPL --type price --period 5y

# 전체 미국 주식 수집
python scripts/collect_us_stocks.py --all --type ticker

# 전체 중 100개만 (배치 처리)
python scripts/collect_us_stocks.py --all --limit 100
python scripts/collect_us_stocks.py --all --offset 100 --limit 100
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--type` | `all` | `all` / `ticker` / `price` / `dividend` / `financial` |
| `--period` | `1y` | 가격 이력 기간 |
| `--all` | off | 전체 미국 종목 대상 |
| `--from-db` | off | `global_ticker`에 저장된 티커 대상 |
| `--limit` / `--offset` | `0` | 배치 처리 |
| `--delay` | `0.0` | 요청 간 딜레이(초) |
| `--save` | off | DB 저장 |

### 한국 주식 수집

배당·재무제표는 **DART OpenAPI**를 사용하므로 `.env`에 `DART_API_KEY`가 필요합니다.
가격은 pykrx, 티커는 FinanceDataReader라 키 없이도 동작합니다.

전 구간 실행 예시 (기본 20개 종목):

```bash
python scripts/collect_kr_stocks.py --type dividend  --save --delay 0.15   # 배당
python scripts/collect_kr_stocks.py --type financial --save --delay 0.15   # 재무제표
python scripts/collect_kr_stocks.py --type price --days 400 --save         # 가격
python scripts/calculate_metrics.py --market KR --only-with-data           # 지표
python scripts/recommend_stocks.py --market KR --use-cache                 # 추천
```

```bash
# 기본 20개 주요 종목 수집
python scripts/collect_kr_stocks.py

# 특정 종목만 수집
python scripts/collect_kr_stocks.py 005930 000660

# 가격 데이터만 수집
python scripts/collect_kr_stocks.py --type price

# 최근 30일 데이터만 (기본 365일)
python scripts/collect_kr_stocks.py --days 30

# 전체 한국 주식 수집
python scripts/collect_kr_stocks.py --all --type ticker

# KOSPI만 / KOSDAQ만 수집
python scripts/collect_kr_stocks.py --all --market KOSPI
python scripts/collect_kr_stocks.py --all --market KOSDAQ
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--type` | `all` | `all` / `ticker` / `price` / `dividend` / `financial` |
| `--market` | `ALL` | `ALL` / `KOSPI` / `KOSDAQ` |
| `--days` | `365` | 가격 이력 일수 |
| `--all` | off | 전체 한국 종목 대상 |
| `--from-db` | off | `global_ticker`에 저장된 티커 대상 |
| `--limit` / `--offset` | `0` | 배치 처리 |
| `--delay` | `0.0` | 요청 간 딜레이(초) |
| `--save` | off | DB 저장 |

### 미국 ETF 수집

`--type` 기본값은 `info`입니다(주식 스크립트와 다름).

```bash
# 기본 인기 ETF (19개) 정보 수집
python scripts/collect_us_etf.py

# 특정 ETF만
python scripts/collect_us_etf.py SPY QQQ IWM

# ETF 상세 정보 (자산, 비용, 수익률)
python scripts/collect_us_etf.py SPY QQQ --type info

# 배당(분배금) 내역 수집
python scripts/collect_us_etf.py SPY SCHD VOO --type dividend

# 전체 미국 ETF 목록 조회
python scripts/collect_us_etf.py --all --type list

# 보유종목 확인
python scripts/collect_us_etf.py SPY --type holdings
```

`--type`: `all` / `list` / `info` / `price` / `dividend` / `holdings`

### 한국 ETF 수집

```bash
# 기본 인기 ETF (20개) 정보 수집
python scripts/collect_kr_etf.py

# 특정 ETF만
python scripts/collect_kr_etf.py 069500 360750

# ETF 상세 정보
python scripts/collect_kr_etf.py 069500 --type info

# 배당(분배금) 내역 수집
python scripts/collect_kr_etf.py 069500 266360 211560 --type dividend

# 전체 한국 ETF 목록 조회
python scripts/collect_kr_etf.py --all --type list

# 가격 데이터 수집
python scripts/collect_kr_etf.py 069500 --type price --days 30
```

`--type`: `all` / `list` / `info` / `price` / `dividend` / `pdf`

### 전체 티커 수집 (한국 + 미국)

한국(KOSPI/KOSDAQ)과 미국(NASDAQ/NYSE/AMEX) **전체 종목**을 한 번에 수집하여
`global_ticker` 테이블에 저장합니다. FinanceDataReader로 시장별 목록을 일괄 조회합니다.

```bash
# 한국 + 미국 전체 티커 수집 후 저장 (약 9,800개)
python scripts/collect_all_tickers.py

# 한쪽 시장만
python scripts/collect_all_tickers.py --market KR
python scripts/collect_all_tickers.py --market US

# 저장 없이 미리보기 (건수만 확인)
python scripts/collect_all_tickers.py --dry-run
```

> 미국 목록에는 시가총액이 없어 `Market Cap`은 NULL로 저장됩니다(한국은 원화 시가총액 포함).
> 중복 심볼은 자동 제거되며, 기존 레코드는 심볼 기준으로 업데이트(upsert)됩니다.

#### 전체 티커 대상 가격/재무/배당 수집 (`--from-db`)

`collect_all_tickers.py`로 `global_ticker`를 채운 뒤, 수집 스크립트의 `--from-db`
옵션으로 **DB에 저장된 전체 티커**를 대상으로 가격·재무·배당을 수집합니다.

```bash
# 1) 전체 티커 목록 저장
python scripts/collect_all_tickers.py

# 2) DB의 전체 티커로 가격/재무/배당 수집·저장
#    (--type all 이면 ticker 단계는 건너뜀 - 이미 DB에 존재)
python scripts/collect_us_stocks.py --from-db --type all --save
python scripts/collect_kr_stocks.py --from-db --type all --save

# 배치 처리 (Rate Limit 대응): offset/limit/delay 병행 권장
python scripts/collect_us_stocks.py --from-db --type all --save --offset 0 --limit 500 --delay 0.5
python scripts/collect_us_stocks.py --from-db --type all --save --offset 500 --limit 500 --delay 0.5

# 특정 데이터만
python scripts/collect_kr_stocks.py --from-db --type dividend --save
```

> `--from-db`는 `global_ticker`가 비어 있으면 안내 메시지와 함께 종료합니다.
> 수천 종목을 종목별 API로 조회하므로 전체 수집에는 상당한 시간이 걸립니다 —
> `--offset`/`--limit`로 배치 처리하고 `--delay`로 Rate Limit을 완화하세요.

### 전체 ETF 티커 수집 (한국 + 미국)

ETF 티커는 주식과 필드/성격이 달라 **별도 테이블 `global_etf`**에 저장합니다
(재무 기반 필터 스캔 대상이 아니므로 주식과 분리).

```bash
# 한국 + 미국 전체 ETF 티커 수집 후 저장 (약 6,700개)
python scripts/collect_all_etfs.py

# 한쪽 시장만
python scripts/collect_all_etfs.py --market KR
python scripts/collect_all_etfs.py --market US

# 저장 없이 미리보기
python scripts/collect_all_etfs.py --dry-run
```

> 한국 ETF는 category/NAV/시가총액을 포함하며, 미국 ETF 목록은 Symbol·Name만 제공되어
> category/nav/market_cap은 NULL로 저장됩니다. 중복 심볼은 자동 제거, upsert로 갱신됩니다.

### 데이터베이스 저장 (`--save`)

모든 수집 스크립트는 `--save` 옵션으로 수집한 데이터를 데이터베이스에 저장합니다.
기존 레코드는 중복 없이 업데이트(upsert)됩니다.

```bash
# 미국 주식 수집 후 저장 (ticker/price/dividend/financial → 각 테이블)
python scripts/collect_us_stocks.py AAPL MSFT --save

# 한국 주식 전체를 배치로 수집하며 저장
python scripts/collect_kr_stocks.py --all --type ticker --save

# ETF 정보/가격/배당 저장 (info→global_ticker, price→global_price, dividend→global_dividends)
python scripts/collect_us_etf.py SPY SCHD --type dividend --save
python scripts/collect_kr_etf.py 069500 --type info --save
```

> `--save`는 `.env`의 DB 설정을 사용합니다. 저장 전 `python scripts/test_db_connection.py`로 연결을 확인하세요.
> 개별 ETF 스크립트의 `--type info --save`는 `global_ticker`로, `collect_all_etfs.py`는 `global_etf`로 저장됩니다.
> 수집 → 저장 후 스케줄러(`start_scheduler.py`)가 `global_*` 테이블을 스캔하여 필터링/알림을 수행합니다.

### 지표 생성 (step 3)

수집한 가격·배당·재무제표에서 `DY`(배당수익률), `DR`(부채비율), `QR`(당좌비율),
`ICR`(이자보상배율)을 계산해 `global_value`에 저장합니다.

```bash
# 전체 티커
python scripts/calculate_metrics.py

# 시장 지정
python scripts/calculate_metrics.py --market KR

# 수집 데이터가 있는 종목만 (권장 - 빈 종목 건너뜀)
python scripts/calculate_metrics.py --only-with-data

# 특정 종목만
python scripts/calculate_metrics.py AAPL MSFT

# 배치 처리
python scripts/calculate_metrics.py --offset 0 --limit 1000
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--market` | `ALL` | `ALL` / `US` / `KR` |
| `--only-with-data` | off | 재무 또는 배당 데이터가 있는 종목만 처리 |
| `--limit` / `--offset` | `0` | 배치 처리 |

### 종목 추천 (step 4)

```bash
# 기본 8개 조건 전부 적용
python scripts/recommend_stocks.py --market US

# 저장된 지표 재사용 (calculate_metrics.py 실행 후)
python scripts/recommend_stocks.py --market US --use-cache

# 근소하게 탈락한 종목과 사유 함께 보기
python scripts/recommend_stocks.py --market US --show-failures 5
```

출력 예시:

```
RECOMMENDED STOCKS
======================================================================
  MO       (US) DY=   6.45%  Years=65  DR=  73.42%  QR=  51.75%
  VZ       (US) DY=   5.77%  Years=43  DR=  44.93%  QR=  73.99%
```

#### Slack 알림

추천 결과를 Slack으로 받을 수 있습니다.

```bash
# .env 에 토큰 설정
SLACK_TOKEN=xoxb-...
SLACK_CHANNEL=#smart-investor
```

```bash
# 추천 결과를 Slack으로 전송
python scripts/recommend_stocks.py --market KR --use-cache --notify slack

# 채널 지정
python scripts/recommend_stocks.py --notify slack --notify-channel '#investing'

# 통과 종목이 없어도 전송 (기본은 조용히 넘어감)
python scripts/recommend_stocks.py --notify slack --notify-empty

# 여러 채널 동시 전송
python scripts/recommend_stocks.py --notify slack,telegram
```

| 옵션 | 설명 |
|------|------|
| `--notify` | `slack` / `telegram` / `email` (쉼표로 복수 지정). **생략 시 `SLACK_TOKEN`이 있으면 slack** |
| `--no-notify` | 전송하지 않음 |
| `--notify-channel` | Slack 채널 재지정 (기본: `SLACK_CHANNEL`) |
| `--notify-empty` | 통과 종목 0건일 때도 전송 |

**전송과 엑셀 생성이 기본값입니다.** 예약 실행에 플래그를 붙일 필요가 없도록 한 것이며,
`SLACK_TOKEN`이 없으면 전송 없이 안내만 남기고 넘어갑니다 — 미설정 환경에서 매 실행이
오류가 되는 것을 막기 위함입니다.

```bash
# 아래 두 줄은 동일합니다
python scripts/recommend_stocks.py --market KR --use-cache
python scripts/recommend_stocks.py --market KR --use-cache --excel --notify slack

# 끄려면
python scripts/recommend_stocks.py --market KR --use-cache --no-notify --no-excel
```

전송되는 메시지에는 **적용된 조건이 함께 포함됩니다.** 임계값을 바꿔가며 실행할 수 있는
구조라, 어떤 기준으로 뽑힌 목록인지 모르면 결과 자체가 무의미하기 때문입니다.

```
🎯 종목 추천 (KR)
2026-08-16 07:24

적용 조건 (3개)
  · dividend_yield: 배당수익률 >= 4.0%
  · consecutive_dividends: 연속 배당 >= 5년
  · debt_ratio: 부채비율 <= 200.0%

────────────────────────────────────────
통과: 4 / 2,763 (0.1%)

• 030200 (KR)  배당 4.49%  5년  부채 19.3%  당좌 80.0%
• 316140 (KR)  배당 4.04%  5년  부채 93.7%
```

토큰이 없거나 채널명이 잘못되면 **스크리닝을 시작하기 전에** 즉시 실패합니다
(전체 스캔을 마친 뒤 전송 단계에서 실패하는 것을 막기 위함).

Slack 앱은 [api.slack.com/apps](https://api.slack.com/apps)에서 만들고,
`chat:write` 권한을 준 뒤 워크스페이스에 설치해 봇 토큰(`xoxb-`)을 발급받습니다.
봇을 대상 채널에 초대해야 전송됩니다.

**매일 자동 발송**하려면 cron에 등록하세요.

```bash
# 평일 18:10에 한국 추천 알림
10 18 * * 1-5 \
  ./venv/bin/python scripts/recommend_stocks.py --market KR --use-cache --notify slack
```

#### 전략: 배당주 / 가치주

조건 세트를 전략으로 묶어 선택합니다. 프리셋은 `configs/dividend.json`, `configs/value.json`입니다.

```bash
# 배당주 (기본값 — 옵션 없이 실행한 것과 동일)
python scripts/recommend_stocks.py --strategy dividend --market KR --use-cache

# 가치주
python scripts/recommend_stocks.py --strategy value --market US --use-cache

# 둘 다 — 지표는 한 번만 계산하고 한 파일 2개 시트로 저장
python scripts/recommend_stocks.py --strategy both --market KR --use-cache --excel --notify slack
```

| 전략 | 조건 |
|------|------|
| `dividend` | 배당수익률, 연속배당, 배당성장, 영업이익성장, 매출성장, 부채비율, 당좌비율, 이자보상배율 |
| `value` | PER, PBR, PER×PBR(그레이엄), ROE, 영업이익률, 부채비율, 당좌비율 |

**가치 조건 기본 임계값** (Graham 기준, `--set`으로 조정 가능)

| 조건 키 | 파라미터 | 기본값 |
|---------|----------|--------|
| `per` | `max_per` | 15.0 |
| `pbr` | `max_pbr` | 1.5 |
| `graham_number` | `max_product` | 22.5 |
| `roe` | `min_roe` | 10.0% |
| `operating_margin` | `min_operating_margin` | 5.0% |

가치 조건은 **등록은 되어 있지만 기본 세트에는 빠져 있습니다**(`FilterSpec.in_default=False`).
배당·가치 조건을 동시에 요구하면 통과 종목이 거의 없기 때문에, 옵션 없이 실행하면
기존 배당 8조건만 적용됩니다. `--enable per` 처럼 명시하면 개별 사용도 가능합니다.

엑셀 시트는 전략별로 컬럼이 다릅니다 — 배당주는 `Div Yield/Div Years/Debt/Quick`,
가치주는 `PBR/ROE/Op Margin/Debt`. 정렬도 배당주는 수익률 높은 순, 가치주는 PER 낮은 순입니다.

##### 가치 지표의 신뢰성 장치

밸류에이션 비율은 **시가총액 ÷ 재무제표 값**이라, 두 값의 기준이 어긋나면 항상
*실제보다 싸게* 나옵니다. 그래서 오류가 가치주 상위권에 몰립니다. 세 겹으로 막습니다.

1. **통화 불일치 차단** — 미국 상장 외국기업(ADR)은 USD로 거래되지만 본국 통화로 공시합니다.
   `GRVY`는 KRW 순이익 때문에 PER이 8.07 대신 **0.01**로 나왔습니다.
   `global_ticker.financial_currency`에 공시 통화를 기록하고, 거래통화와 다르면 비율을 내지 않습니다.
2. **0으로 반올림된 비율 거부** — PER 0.00044가 소수점 2자리 저장에서 `0.00`이 되어
   `PER ≤ 15`를 **가장 싼 종목으로 통과**했습니다. 시총이 이익의 0.5% 미만이면 데이터 오류로 보아
   `None` 처리합니다.
3. **후보군 실시간 재검증** — 연간 재무제표의 발행주식수는 대량 희석 후 낡습니다
   (`WHLR`: 저장 시총 $3,844 vs 실제 $916,022). 추천을 통과한 수십 종목만 실시간 시총으로
   비율을 재계산해 조건을 다시 적용합니다. 확인한 통화는 DB에 캐시되어 다음 실행에서 재사용됩니다.

> 시가총액은 상장 통화 기준입니다 — 미국은 USD, 한국은 KRW. 엑셀의 `Country` 컬럼으로 구분하세요.

**공시 통화 사전 수집** (선택) — 후보군 검증만으로 충분하지만, 미리 채워두면 조회가 생략됩니다.

```bash
python scripts/migrate_add_financial_currency.py    # 컬럼 추가 (최초 1회)
python scripts/collect_financial_currency.py --market US
```

#### 엑셀 리포트

추천 결과를 xlsx로 만들고 Slack에 첨부할 수 있습니다.

```bash
# 기본 실행 — 엑셀 생성 + Slack 전송
python scripts/recommend_stocks.py --market KR --use-cache

# 엑셀만 생성 (전송 안 함)
python scripts/recommend_stocks.py --market KR --use-cache --no-notify

# 경로 지정
python scripts/recommend_stocks.py --market US --use-cache --excel /tmp/us.xlsx

# 엑셀 + Slack 첨부
python scripts/recommend_stocks.py --market KR --use-cache --excel --notify slack
```

| 옵션 | 설명 |
|------|------|
| `--excel [PATH]` | xlsx 생성 (**기본 on**). 경로 생략 시 `reports/recommendations_<시장>_<날짜시각>.xlsx` |
| `--no-excel` | 리포트를 만들지 않음 |
| `--enrich-delay` | 프로필 조회 간 딜레이(초). yfinance Rate Limit 발생 시 사용 |

**시트 1 (Recommendations)** — 15개 컬럼

```
No. | Ticker | Company | Sector | Industry | Country | Market Cap | P/E |
Price | Change | Volume | Div Yield | Div Years | Debt Ratio | Quick Ratio
```

헤더 고정·자동필터·숫자 서식이 적용되어 있고, 값이 없는 칸은 `-`로 둡니다
(0으로 채우면 실제 측정값처럼 정렬되기 때문).

**시트 2 (Criteria)** — 적용된 조건 목록과 생성 시각. 임계값을 실행마다 바꿀 수 있는 구조라
종목 목록만으로는 재현이 되지 않기 때문에 함께 기록합니다.

##### 없는 데이터는 리포트 시점에 채웁니다

`Sector`(한국) · `Industry` · `Market Cap`(미국) · `P/E`는 어떤 필터도 읽지 않아
수집 파이프라인에 없습니다. 스키마를 늘리고 9,800종목을 재수집하는 대신,
**추천을 통과한 종목에만** yfinance 프로필을 조회합니다 (20~30종목이라 몇 초).

| 항목 | 출처 |
|------|------|
| Sector / Industry | yfinance `info` (한국은 KOSPI→`.KS`, KOSDAQ→`.KQ` 접미사) |
| Market Cap | yfinance `marketCap` (DB의 미국 시가총액은 비어 있음) |
| P/E (미국) | yfinance `trailingPE` |
| P/E (한국) | `marketCap ÷ netIncomeToCommon` — 한국은 `trailingPE`가 항상 비어 있음 |

적자 기업의 P/E는 공란입니다. 음수 P/E는 정렬 시 "저평가"로 올라오기 때문입니다.
yfinance에 프로필이 없는 소형주는 해당 칸만 `-`로 남습니다.

> **Slack 첨부에는 `files:write` 권한이 필요합니다.** 또한 업로드 API는 채널 **이름**이 아닌
> **ID**(`C…`)를 요구하는데, 이름→ID 변환에 필요한 `channels:read` 없이도 되도록
> 요약 메시지 전송 응답에 담겨 오는 채널 ID를 재사용합니다.

#### 조건 추가·제거 (step 4)

조건은 각각 키로 등록되어 있어 실행 시 선택할 수 있습니다.

```bash
# 사용 가능한 조건과 조정 가능한 파라미터 확인
python scripts/recommend_stocks.py --list-filters

# 조건 빼기
python scripts/recommend_stocks.py --disable quick_ratio,revenue_growth

# 특정 조건만 사용
python scripts/recommend_stocks.py --enable dividend_yield,consecutive_dividends,debt_ratio

# 임계값 조정
python scripts/recommend_stocks.py --set dividend_yield.min_dividend_yield=3.0
python scripts/recommend_stocks.py --set debt_ratio.max_debt_ratio=150

# 설정 파일 사용
python scripts/recommend_stocks.py --config configs/income.json

# 지금 선택한 조건을 파일로 저장
python scripts/recommend_stocks.py --disable quick_ratio --save-config configs/my.json
```

| 조건 키 | 조정 가능한 파라미터 | 기본값 |
|---------|---------------------|--------|
| `dividend_yield` | `min_dividend_yield` | 4.0 |
| `consecutive_dividends` | `min_years` | 5 |
| `dividend_growth` | (없음) | - |
| `operating_income_growth` | (없음) | - |
| `revenue_growth` | (없음) | - |
| `debt_ratio` | `max_debt_ratio` | 200.0 |
| `quick_ratio` | `min_quick_ratio` | 100.0 |
| `interest_coverage` | `min_coverage_ratio` | 100.0 |

설정 파일 형식 (`configs/` 에 `default.json`, `income.json` 예시 포함):

```json
{
  "enabled": ["dividend_yield", "consecutive_dividends", "debt_ratio"],
  "params": {
    "dividend_yield": {"min_dividend_yield": 3.0},
    "debt_ratio": {"max_debt_ratio": 150.0}
  }
}
```

`enabled`를 생략하면 등록된 모든 조건이 적용되며, `disabled`로 일부만 뺄 수도 있습니다.
없는 조건 키나 없는 파라미터를 지정하면 DB 작업 전에 즉시 오류로 알려줍니다.

#### 새 조건 추가 (코드)

`filters/registry.py`에 등록하면 엔진 수정 없이 조건이 추가됩니다.

```python
from smart_investor.filters import FilterSpec, register

class MarketCapFilter:
    def __init__(self, min_market_cap: float = 1e9) -> None:
        self.min_market_cap = min_market_cap

    def check(self, metrics) -> tuple[bool, str]:
        ...  # (통과 여부, 사유)

    def describe(self) -> str:
        return f"시가총액 >= {self.min_market_cap}"

register(FilterSpec(
    key="market_cap",
    label="Market Cap",
    factory=MarketCapFilter,
    params={"min_market_cap": 1e9},
    description="시가총액 하한",
))
```

### 필터 실행 (레거시)

`recommend_stocks.py` 이전에 쓰던 단순 실행 경로입니다. 조건 선택 기능은 없습니다.

```bash
python scripts/run_filter.py --market US --limit 100
```

### 스케줄러 실행

```bash
# 포그라운드 실행 (평일 18:00 일일 스캔, 일요일 10:00 주간 리포트)
python scripts/start_scheduler.py

# 스캔 시각 변경
python scripts/start_scheduler.py --daily-hour 17
python scripts/start_scheduler.py --weekly-day sat

# 스케줄 없이 즉시 1회 스캔 후 종료
python scripts/start_scheduler.py --run-now

# 백그라운드 실행
python scripts/start_scheduler.py > scheduler.log 2>&1 &

# 로그 확인
tail -f scheduler.log

# 종료
pkill -f start_scheduler.py
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--daily-hour` | `18` | 일일 스캔 시각 (24시간제, 평일 mon-fri) |
| `--weekly-day` | `sun` | 주간 리포트 요일 (10:00 고정) |
| `--run-now` | off | 즉시 1회 스캔 후 종료 |
| `--filter-config` | 없음 | 스캔에 적용할 조건 JSON 파일 (기본: 전체 조건) |

스케줄러는 `.env`에 설정된 알림 채널만 자동으로 활성화합니다
(Slack은 `SLACK_TOKEN`, Telegram은 `TELEGRAM_TOKEN`, Email은 `SMTP_USERNAME` 기준).
설정된 채널이 없으면 경고 로그를 남기고 알림 없이 동작합니다.
직전 스캔 대비 **신규 통과(new_qualifiers)** 와 **탈락(disqualified)** 종목만 알림으로 전송합니다.

### 데이터베이스 연결 테스트

```bash
python scripts/test_db_connection.py
```

### 테스트 실행

`pyproject.toml`의 `addopts`에 커버리지 옵션이 이미 포함되어 있어, 별도 플래그 없이도
터미널 리포트와 `htmlcov/` HTML 리포트가 생성됩니다.

```bash
# 전체 테스트 (커버리지 포함)
pytest tests/ -v

# 커버리지 없이
pytest tests/ -v --no-cov
```

현재 상태: **275개 통과 / 전체 커버리지 55%.**

| 테스트 파일 | 대상 |
|-------------|------|
| `test_filters.py` | 8개 조건의 통과/탈락 판정 |
| `test_models.py` | 데이터 모델 |
| `test_trend_analysis.py` | 선형회귀 추세 판정, 특별배당 제외 |
| `test_filter_registry.py` | 조건 등록·선택·임계값 오버라이드·설정 파일 (step 4) |
| `test_kr_dart.py` | DART 계정 매핑, 금액/기간 파싱, 배당 파싱 (step 2) |
| `test_persistence.py` | 중복 방지 upsert, 자연키 제약 (MySQL 없으면 자동 skip) |
| `test_notifications.py` | 추천 메시지 형식, Slack 전송·파일 업로드 (SDK 목킹) |
| `test_reporting.py` | 엑셀 생성(전략별 컬럼·다중 시트), 프로필 조회·P/E 산출 |
| `test_recommend_cli.py` | CLI 기본값 (전송·엑셀 on, 토큰 없을 때 동작) |
| `test_dividend_yield_reconciliation.py` | 액면분할 미보정 배당수익률 탐지, 통화 불일치 차단 |

DART 테스트는 응답을 스텁으로 대체하므로 **네트워크와 API 키 없이 실행**됩니다.
알림(notifications)과 스케줄러(scheduler)는 아직 테스트가 없습니다.

## 프로젝트 구조

```
smart-investor/
├── src/smart_investor/
│   ├── models/              # 데이터 모델
│   │   └── stock.py         # Market, Stock, FinancialMetrics, FilterResult
│   ├── filters/             # 조건 로직
│   │   ├── criteria.py      # 8가지 조건 클래스 (임계값 파라미터화)
│   │   ├── registry.py      # 조건 등록소 - 여기 등록하면 조건 추가됨
│   │   ├── config.py        # 조건 선택/임계값 오버라이드 (JSON)
│   │   └── engine.py        # StockFilterEngine (탈락 사유 통계 포함)
│   ├── analysis/            # 분석 도구
│   │   └── calculator.py    # MetricsCalculator (선형회귀, 특별배당 제외, 지표 캐시)
│   ├── collectors/          # 데이터 수집
│   │   ├── base.py          # 공통 수집기 베이스
│   │   ├── us/              # 미국 (yfinance): ticker/price/dividend/financial
│   │   └── kr/              # 한국
│   │       ├── dart.py      # DART OpenAPI 클라이언트 (corp_code 캐시 포함)
│   │       ├── accounts.py  # DART/IFRS 계정 → 영문 계정명 매핑
│   │       ├── ticker.py    # FinanceDataReader 상장목록
│   │       ├── price.py     # pykrx OHLCV
│   │       ├── dividend.py  # DART 배당 공시
│   │       └── financial.py # DART 재무제표
│   ├── notifications/       # 알림 시스템
│   │   ├── base.py          # NotificationService, NotificationResult
│   │   ├── email.py
│   │   ├── slack.py
│   │   └── telegram.py
│   ├── db/                  # 데이터베이스
│   │   ├── config.py        # DatabaseConfig.from_env()
│   │   ├── connection.py    # DatabaseConnection (컨텍스트 매니저)
│   │   ├── models.py        # ORM 모델 (global_* 6개 테이블)
│   │   ├── persistence.py   # DataPersistence (upsert 저장)
│   │   └── saver.py         # save_collected_data() — 스크립트↔퍼시스턴스 브리지
│   ├── reporting/           # 리포트 생성
│   │   ├── enrichment.py    # yfinance 프로필 조회 (Sector/Industry/MktCap/PE)
│   │   └── excel.py         # xlsx 워크북 생성
│   └── scheduler/           # 스케줄러
│       └── jobs.py          # StockScannerJob, ScannerScheduler (APScheduler)
├── scripts/                    # 실행 스크립트
│   ├── collect_all.sh          # 전 구간 실행 (체크포인트 재개 지원)
│   ├── init_db.py              # 테이블 생성 (최초 1회)
│   ├── migrate_add_unique_constraints.py  # 자연키 유니크 제약 추가 (기존 DB용)
│   ├── migrate_add_financial_currency.py  # 공시 통화 컬럼 추가
│   ├── collect_financial_currency.py      # 공시 통화 수집 (ADR 판별용)
│   ├── collect_all_tickers.py  # 한국+미국 전체 주식 티커 → global_ticker
│   ├── collect_all_etfs.py     # 한국+미국 전체 ETF 티커 → global_etf
│   ├── collect_us_stocks.py    # 미국 주식 수집
│   ├── collect_kr_stocks.py    # 한국 주식 수집
│   ├── collect_us_etf.py       # 미국 ETF 수집
│   ├── collect_kr_etf.py       # 한국 ETF 수집
│   ├── calculate_metrics.py    # step 3: 지표 생성 → global_value
│   ├── recommend_stocks.py     # step 4: 조건 적용 종목 추천
│   ├── run_filter.py           # 필터 실행 (레거시)
│   ├── start_scheduler.py      # 스케줄러
│   ├── test_db_connection.py   # DB 연결 확인
│   └── test_kr_collector.py    # 한국 수집기 수동 점검
├── tests/                   # 테스트
│   ├── test_filters.py
│   ├── test_models.py
│   ├── test_trend_analysis.py
│   ├── test_filter_registry.py  # 조건 등록·선택·오버라이드
│   ├── test_persistence.py      # 중복 방지 upsert (DB 필요, 없으면 skip)
│   └── test_kr_dart.py          # DART 파싱 (스텁, 네트워크 불필요)
├── configs/                 # 조건 세트 예시
│   ├── default.json         # 8개 조건 전부
│   ├── dividend.json        # 배당주 전략
│   ├── value.json           # 가치주 전략
│   └── income.json          # 고배당 중심 5개 조건
├── docker/mysql/init/       # MySQL 초기화 SQL 배치 위치
├── .env.example             # 환경변수 예시
├── pyproject.toml           # 프로젝트 설정 (pytest/black/ruff/mypy)
└── requirements.txt         # 의존성
```

## 환경변수

`.env.example`을 복사해 사용합니다. DB 3개 항목만 필수이며 나머지는 기본값이 있습니다.

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `DB_NAME` | ✅ | | 데이터베이스 이름 |
| `DB_USER` | ✅ | | 데이터베이스 사용자 |
| `DB_PASSWORD` | ✅ | | 데이터베이스 비밀번호 |
| `DB_HOST` | | `localhost` | 호스트 |
| `DB_PORT` | | `3306` | 포트 |
| `DB_CHARSET` | | `utf8mb4` | 문자셋 |
| `DB_POOL_SIZE` | | `5` | 커넥션 풀 크기 |
| `DB_POOL_RECYCLE` | | `3600` | 커넥션 재활용 주기(초) |
| `DB_ECHO` | | `false` | SQLAlchemy SQL 로깅 |
| `DART_API_KEY` | 한국 종목 필수 | | DART 인증키 (https://opendart.fss.or.kr/) |
| `SLACK_TOKEN` | | | Slack Bot 토큰 (설정 시 알림 활성화) |
| `SLACK_CHANNEL` | | | Slack 채널 |
| `TELEGRAM_TOKEN` | | | Telegram Bot 토큰 (설정 시 알림 활성화) |
| `TELEGRAM_CHAT_ID` | | | Telegram 채팅 ID |
| `SMTP_HOST` | | | SMTP 서버 |
| `SMTP_PORT` | | `587` | SMTP 포트 |
| `SMTP_USERNAME` | | | 이메일 사용자 (설정 시 알림 활성화) |
| `SMTP_PASSWORD` | | | 이메일 비밀번호 (Gmail은 앱 비밀번호) |
| `SMTP_FROM` | | | 발신 주소 |
| `SMTP_TO` | | | 수신 주소 (쉼표 구분) |

## 데이터베이스 테이블

### 테이블 구조

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| `global_ticker` | 종목(주식) 기본 정보 | Symbol, Name, Exchange, Sector, Market Cap, country, date |
| `global_etf` | ETF 기본 정보 | Symbol, Name, Exchange, category, nav, Market Cap, country, date |
| `global_price` | 가격 이력 | ticker, Date, Open, High, Low, Close, Adj Close, Volume |
| `global_dividends` | 배당 내역 | ticker, Ex-Dividend Date, Cash Amount, Record Date, Pay Date |
| `global_fs` | 재무제표 | ticker, date, account, value, freq |
| `global_value` | 계산 지표 + 공시값 | ticker, date, indicator(`DY`/`DR`/`QR`/`ICR`/`PER`/`PBR`/`PSR`/`ROE`/`OPM`/`MKTCAP`/`DY_DART`), value |

`global_fs.freq`는 연간이 `y`이며, 지표 계산은 연간(`y`) 데이터를 사용합니다.
사용하는 계정명(yfinance 기준): `Total Debt`, `Total Assets`, `Cash And Cash Equivalents`,
`Accounts Receivable`, `Current Liabilities`, `EBIT`, `Interest Expense`, `Total Revenue`,
`Operating Income`.

### 중복 데이터 관리

모든 테이블에 자연키 유니크 제약이 걸려 있고, 저장은
`INSERT ... ON DUPLICATE KEY UPDATE`로 처리합니다. 같은 수집을 몇 번 반복해도
행이 늘지 않고 값만 갱신됩니다.

| 테이블 | 자연키 | 제약명 | 재저장 시 갱신 컬럼 |
|--------|--------|--------|---------------------|
| `global_ticker` | `Symbol` | `uq_ticker_symbol` | Name, Exchange, Sector, Market Cap, country, date |
| `global_etf` | `Symbol` | `uq_etf_symbol` | Name, Exchange, category, nav, Market Cap, country, date |
| `global_price` | `ticker + Date` | `uq_price_ticker_date` | OHLC, Volume, Adj Close |
| `global_fs` | `ticker + date + account + freq` | `uq_fs_ticker_date_account_freq` | value |
| `global_dividends` | `ticker + Ex-Dividend Date` | `uq_dividend_ticker_exdate` | Cash Amount, Pay/Record Date |
| `global_value` | `ticker + date + indicator` | `uq_value_ticker_date_ind` | value |

- **배치 내 중복도 제거됩니다** — 한 번의 저장 요청에 같은 키가 두 번 들어오면 마지막 값이 남습니다.
- **병렬 실행이 안전합니다** — DB가 키를 강제하므로, 여러 프로세스가 같은 구간을 동시에
  저장해도 중복이 생기지 않습니다. (4개 프로세스 × 동일 28행 → 28행 확인)
- **`global_value`만 추가 처리가 있습니다** — 이번 실행에서 계산되지 않은 지표는 삭제해,
  이전 실행에 남은 값이 최신값으로 오인되지 않게 합니다.

> 제약 도입 전에 만들어진 DB에는 중복이 남아 있을 수 있습니다.
> `scripts/migrate_add_unique_constraints.py`가 적용 전에 중복을 검사하고,
> 발견되면 중단합니다. `--dedupe`를 주면 각 그룹의 최소 `id`만 남기고 정리합니다.

### 스크립트별 수집 데이터

| 스크립트 | `--type` | 테이블 | 설명 |
|----------|----------|--------|------|
| `collect_all_tickers.py` | - | `global_ticker` | 한국+미국 전체 주식 티커 |
| `collect_all_etfs.py` | - | `global_etf` | 한국+미국 전체 ETF 티커 |
| `collect_us_stocks.py` | `ticker` | `global_ticker` | 미국 주식 기본 정보 |
| | `price` | `global_price` | 미국 주식 가격 이력 |
| | `dividend` | `global_dividends` | 미국 주식 배당 내역 |
| | `financial` | `global_fs` | 미국 주식 재무제표 |
| `collect_kr_stocks.py` | `ticker` | `global_ticker` | 한국 주식 기본 정보 |
| | `price` | `global_price` | 한국 주식 가격 이력 |
| | `dividend` | `global_dividends` | 한국 주식 배당 내역 |
| | `financial` | `global_fs` | 한국 주식 재무제표 |
| `collect_us_etf.py` | `list` | - | ETF 목록 조회 (출력만) |
| | `info` | `global_ticker` | 미국 ETF 기본 정보 |
| | `price` | `global_price` | 미국 ETF 가격 이력 |
| | `dividend` | `global_dividends` | 미국 ETF 배당(분배금) 내역 |
| | `holdings` | - | ETF 보유종목 (출력만) |
| `collect_kr_etf.py` | `list` | - | ETF 목록 조회 (출력만) |
| | `info` | `global_ticker` | 한국 ETF 기본 정보 |
| | `price` | `global_price` | 한국 ETF 가격 이력 |
| | `dividend` | `global_dividends` | 한국 ETF 배당(분배금) 내역 |
| | `pdf` | - | ETF NAV/PDF (출력만) |
| `calculate_metrics.py` | - | `global_value` | 계산 지표 저장 (step 3) |
| `recommend_stocks.py` | - | - | 조건 적용 후 추천 출력 (step 4) |

### 국가 구분

`global_ticker.country` / `global_etf.country` 필드로 국가를 구분하며,
필터·스캔에서 시장(`Market.US` / `Market.KR`) 판별에 사용됩니다.

- **미국**: `United States`
- **한국**: `South Korea`

## 수집 가능 데이터

2026년 8월 기준 FinanceDataReader 조회값입니다. 상장/폐지에 따라 변동됩니다.

| 구분 | 미국 | 한국 |
|------|------|------|
| 주식 | 약 7,085개 (NASDAQ 3,973 / NYSE 2,796 / AMEX 316) | 약 2,763개 (KOSPI 942 / KOSDAQ 1,821) |
| ETF | 약 5,555개 | 약 1,163개 |
| **합계** | **약 12,640개** | **약 3,926개** |

## 기본 수집 종목

인자 없이 실행할 때 사용되는 종목 목록입니다.

### 미국 주식 (18개)

```
JNJ, PG, KO, PEP, MMM, ABT, ABBV, T, VZ, XOM,
CVX, IBM, MCD, WMT, HD, O, AAPL, MSFT
```

### 한국 주식 (20개)

```
005930 삼성전자    000660 SK하이닉스   035420 NAVER
005380 현대차      051910 LG화학       006400 삼성SDI
035720 카카오      105560 KB금융       055550 신한지주
086790 하나금융    316140 우리금융     017670 SK텔레콤
030200 KT         032830 삼성생명     000810 삼성화재
096770 SK이노베이션 034730 SK          003550 LG
066570 LG전자      012330 현대모비스
```

### 미국 ETF (19개)

```
SPY, QQQ, IWM, DIA, VTI, VOO, VEA, VWO, BND, GLD,
SLV, USO, XLF, XLK, XLE, XLV, ARKK, SOXL, TQQQ
```

### 한국 ETF (20개)

```
069500 KODEX 200            102110 TIGER 200
360750 TIGER 미국S&P500      133690 TIGER 미국나스닥100
371460 TIGER 차이나전기차     305720 KODEX 2차전지산업
091160 KODEX 반도체          091180 KODEX 자동차
117700 KODEX 건설            228790 TIGER 화장품
139260 TIGER 미디어콘텐츠     157450 TIGER 헬스케어
143850 TIGER 200IT           139220 TIGER 200건설
266360 KODEX 배당성장         211560 TIGER 배당성장
329200 TIGER 미국테크TOP10    381170 TIGER 미국필라델피아반도체
379800 KODEX 미국S&P500TR    379810 KODEX 미국나스닥100TR
```

## 배치 처리 예시

대량 데이터 수집 시 `--offset`과 `--limit`를 활용하여 배치 처리:

```bash
# 미국 전체 주식을 1000개씩 배치 처리
python scripts/collect_us_stocks.py --all --offset 0 --limit 1000
python scripts/collect_us_stocks.py --all --offset 1000 --limit 1000
python scripts/collect_us_stocks.py --all --offset 2000 --limit 1000
# ... 전체 종목 수까지 반복

# 한국 전체 주식을 500개씩 배치 처리
python scripts/collect_kr_stocks.py --all --offset 0 --limit 500
python scripts/collect_kr_stocks.py --all --offset 500 --limit 500
# ... 전체 종목 수까지 반복
```

## Rate Limit 대응

API Rate Limit 오류 발생 시 `--delay` 옵션으로 요청 간 딜레이 설정:

```bash
# 미국 주식: 0.5초 딜레이 (yfinance Rate Limit 대응)
python scripts/collect_us_stocks.py --all --delay 0.5

# 미국 ETF: 0.5초 딜레이
python scripts/collect_us_etf.py --all --delay 0.5

# 한국 주식: 0.3초 딜레이 (pykrx/KRX API 대응)
python scripts/collect_kr_stocks.py --all --delay 0.3

# 한국 ETF: 0.3초 딜레이
python scripts/collect_kr_etf.py --all --delay 0.3
```

| 스크립트 | 권장 딜레이 | 사유 |
|----------|-------------|------|
| `collect_us_stocks.py` | 0.5초 | yfinance API Rate Limit |
| `collect_us_etf.py` | 0.5초 | yfinance API Rate Limit |
| `collect_kr_stocks.py` | 0.3초 | KRX API 안정성 |
| `collect_kr_etf.py` | 0.3초 | KRX API 안정성 |

## 개발

코드 스타일 설정은 `pyproject.toml`에 정의되어 있습니다 (line-length 100).

```bash
# 개발 의존성 설치
pip install -e ".[dev]"

# 포매팅 / 린트 / 타입 체크
black src tests scripts
ruff check src tests scripts
mypy src
```

## 알려진 제약

- **한국 재무·배당은 `DART_API_KEY` 필수** — 키가 없으면 한국 종목은 가격만 수집되고
  재무 기반 조건(4~8번)을 통과할 수 없습니다.
- **한국 배당은 액면분할 보정이 필요** — `global_price`는 pykrx의 **수정주가**인데
  `global_dividends.Cash Amount`는 DART 공시 원문(공시 시점 주식 수 기준)이라, 분할이 있으면
  두 테이블의 기준이 어긋나 배당수익률이 분할 비율만큼 부풀려집니다
  (미원화학 41.40% vs 실제 4.14%).

  같은 공시의 `현금배당수익률(%)`을 `DY_DART` 지표로 함께 저장하고,
  `DPS ÷ 공시수익률`로 역산한 공시 당시 주가를 수정주가와 비교해 **분할 비율을 측정**합니다.
  측정값을 액면가 사다리(2/5/10/20/50/100)에 맞춰 반올림한 뒤 배당금을 나눕니다.

  측정은 잡음이 있습니다 — 공시수익률은 연평균 주가 기준이라 연말 종가와 비교하면
  무분할 종목도 0.93~2.4배로 흩어집니다. 그래서 **연도 간 일관성**을 요구하고
  (`SPLIT_CONSISTENCY`, 2개년 이상), 1개년뿐이면 주가 변동으로 설명 불가능한
  **5배 이상**만 인정합니다 (`_SINGLE_YEAR_MIN_FACTOR`).

  **1 미만 측정값은 보정하지 않습니다.** 검증 결과 전부 액면가 기준 배당률을 공시한 사례였고
  (흥국: 액면가 500원에 배당 280원 → 56% 공시), 이를 보정하면 배당을 10~20배로 부풀려
  가짜 고배당주를 만듭니다. 수익률을 낮게 잡는 실수는 후보를 놓칠 뿐이지만,
  높게 잡는 실수는 추천 상위에 엉터리 종목을 올립니다.
- **한국 특별배당 필터는 무력** — 연 1건만 공시되어 중앙값 기반 이상치 탐지(최소 2개 값 필요)가
  동작하지 않습니다. 미국은 분기배당 4건이라 정상 작동합니다.
- **한국 배당은 연 단위** — DART `alotMatter`는 개별 지급 건이 아니라 사업연도별
  주당 배당금을 공시합니다. 연 단위로 집계하는 지표(수익률·성장추세·연속연수)에는 영향이
  없지만, 지급 건별 분석은 이 소스로 불가능합니다. 배당 기준일은 사업연도 말로 기록됩니다.
- **한국 Total Debt는 차입금 합계** — DART가 차입금을 항목별로 공시하므로 이를 합산합니다.
  차입금 공시가 없으면 부채총계로 대체하며, 이 경우 부채비율이 보수적으로(높게) 나옵니다.
- **한국 이자비용은 금융비용으로 대체될 수 있음** — 상당수 한국 기업은 주요 재무제표에
  이자비용을 따로 공시하지 않고 `금융비용`(환차손 등 포함)만 표시합니다. 이 경우
  `Finance Costs`를 분모로 사용하므로 **이자보상배율이 실제보다 낮게** 나옵니다.
  무차입으로 오판해 통과시키는 것보다 보수적인 쪽을 택한 결과입니다.
  (예: 삼성전자 2025년 금융비용 11.7조 → ICR 371.59%)
- **금융지주·보험사는 당좌비율 산출 불가** — 은행권은 유동부채를 공시하지 않아 `QR`이
  `n/a`가 되고 당좌비율 조건에서 탈락합니다. 금융주를 보려면 `--disable quick_ratio`를
  사용하세요. 이자보상배율도 이자비용이 본업 원가라 구조적으로 낮게 나옵니다.
- **pykrx 일부 API는 KRX 로그인 필요** — `get_market_ticker_list`, `get_market_cap_by_ticker`,
  `get_market_fundamental`은 `KRX_ID`/`KRX_PW` 없이는 빈 값을 반환합니다. 이 때문에 티커 수집은
  FinanceDataReader를 사용합니다. 가격(`get_market_ohlcv_by_date`)은 로그인 없이 동작합니다.
- 주간 리포트(`run_weekly_report`)는 현재 일일 스캔을 그대로 실행한 뒤 리포트로 전송합니다.
- 신규/탈락 종목 추적(`_previous_passed`)은 프로세스 메모리에만 유지되어, 스케줄러를
  재시작하면 초기화됩니다.
- 스캔 대상은 `global_ticker`(주식)이며 `global_etf`는 재무 기반 조건 대상이 아닙니다.
- 알림(notifications)·스케줄러(scheduler)는 아직 자동 테스트가 없습니다.

## 라이선스

MIT License
