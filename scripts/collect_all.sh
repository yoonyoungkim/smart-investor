#!/usr/bin/env bash
#
# Run the full pipeline: tickers -> prices/dividends/financials -> metrics.
#
# Every step records itself in a checkpoint file once it succeeds, so a re-run
# after a crash, a rate limit, or a Ctrl-C picks up where it stopped instead of
# re-downloading hours of data. Natural-key unique constraints make re-running a
# step harmless, so resuming can never duplicate rows.
#
# Usage:
#   scripts/collect_all.sh                      # everything, sequential
#   scripts/collect_all.sh --market KR          # Korea only
#   scripts/collect_all.sh --jobs 3             # 3 US batches in parallel
#   scripts/collect_all.sh --dry-run            # print the plan, run nothing
#   scripts/collect_all.sh --from-scratch       # ignore the checkpoint
#   scripts/collect_all.sh --status             # show progress and exit
#
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

PYTHON="$PROJECT_DIR/venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

LOG_DIR="$PROJECT_DIR/logs"
STATE_FILE="$LOG_DIR/collect_all.state"
LOG_FILE="$LOG_DIR/collect_all_$(date +%Y%m%d_%H%M%S).log"

MARKET="ALL"
JOBS=1
BATCH=1000
US_DELAY=0.5
KR_DELAY=0.15
PRICE_DAYS=400
DRY_RUN=0
FROM_SCRATCH=0
SHOW_STATUS=0
SKIP_TICKERS=0

# ---------------------------------------------------------------- arguments

while [[ $# -gt 0 ]]; do
  case "$1" in
    --market)       MARKET="${2:-ALL}"; shift 2 ;;
    --jobs)         JOBS="${2:-1}"; shift 2 ;;
    --batch)        BATCH="${2:-1000}"; shift 2 ;;
    --delay)        US_DELAY="${2:-0.5}"; shift 2 ;;
    --days)         PRICE_DAYS="${2:-400}"; shift 2 ;;
    --dry-run)      DRY_RUN=1; shift ;;
    --from-scratch) FROM_SCRATCH=1; shift ;;
    --status)       SHOW_STATUS=1; shift ;;
    --skip-tickers) SKIP_TICKERS=1; shift ;;
    -h|--help)      awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$MARKET" in ALL|KR|US) ;; *) echo "--market must be ALL, KR or US" >&2; exit 2 ;; esac

mkdir -p "$LOG_DIR"
[[ $FROM_SCRATCH -eq 1 ]] && rm -f "$STATE_FILE"
touch "$STATE_FILE"

# ---------------------------------------------------------------- helpers

log() { printf '%s | %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

done_already() { grep -qxF "$1" "$STATE_FILE"; }
mark_done()    { echo "$1" >> "$STATE_FILE"; }

# Run one pipeline step unless the checkpoint says it already finished.
# Args: step name, then the command to execute.
run_step() {
  local step="$1"; shift

  if done_already "$step"; then
    log "SKIP  $step (already done)"
    return 0
  fi

  if [[ $DRY_RUN -eq 1 ]]; then
    log "PLAN  $step: $*"
    return 0
  fi

  log "START $step"
  local began=$SECONDS
  if "$@" >>"$LOG_FILE" 2>&1; then
    mark_done "$step"
    log "OK    $step ($((SECONDS - began))s)"
    return 0
  fi

  log "FAIL  $step - see $LOG_FILE. Re-run this script to resume."
  return 1
}

# Number of rows in global_ticker for a country, used to size the US batches.
count_tickers() {
  "$PYTHON" - "$1" <<'PY' 2>/dev/null
import sys
sys.path.insert(0, "src")
from sqlalchemy import text
from smart_investor.db.config import DatabaseConfig
from smart_investor.db.connection import DatabaseConnection
with DatabaseConnection(DatabaseConfig.from_env()) as db:
    session = db.get_session()
    print(session.execute(
        text("SELECT COUNT(*) FROM global_ticker WHERE country = :c"),
        {"c": sys.argv[1]},
    ).scalar())
PY
}

# ---------------------------------------------------------------- status

if [[ $SHOW_STATUS -eq 1 ]]; then
  echo "Checkpoint: $STATE_FILE"
  if [[ -s "$STATE_FILE" ]]; then
    echo "Completed steps ($(wc -l < "$STATE_FILE" | tr -d ' ')):"
    sed 's/^/  ✓ /' "$STATE_FILE"
  else
    echo "  (nothing completed yet)"
  fi
  exit 0
fi

# ---------------------------------------------------------------- preflight

log "=============================================================="
log "Smart Investor full collection"
log "market=$MARKET jobs=$JOBS batch=$BATCH us_delay=$US_DELAY"
log "log=$LOG_FILE"
log "=============================================================="

if [[ $DRY_RUN -eq 0 ]]; then
  if ! "$PYTHON" scripts/test_db_connection.py >>"$LOG_FILE" 2>&1; then
    log "FAIL  database connection - check .env and that MySQL is running"
    exit 1
  fi
  log "OK    database reachable"

  # Korean financials and dividends come from DART; stop before a long run
  # rather than discovering the missing key partway through.
  if [[ "$MARKET" != "US" ]]; then
    if ! grep -q '^DART_API_KEY=.\+' .env 2>/dev/null; then
      log "FAIL  DART_API_KEY missing in .env - required for Korean data"
      log "      Get a free key at https://opendart.fss.or.kr/"
      exit 1
    fi
    log "OK    DART_API_KEY present"
  fi
fi

# ---------------------------------------------------------------- step 1

if [[ $SKIP_TICKERS -eq 0 ]]; then
  run_step "tickers:stocks" "$PYTHON" scripts/collect_all_tickers.py --market "$MARKET" || exit 1
  run_step "tickers:etfs"   "$PYTHON" scripts/collect_all_etfs.py    --market "$MARKET" || exit 1
fi

# ---------------------------------------------------------------- step 2 (KR)

if [[ "$MARKET" != "US" ]]; then
  # Prices come from pykrx and are cheap; DART carries a 20,000 request/day
  # quota and the full market needs roughly 17,000, so financials and dividends
  # get one shot per day. If either fails on quota, resume tomorrow.
  run_step "kr:price" "$PYTHON" scripts/collect_kr_stocks.py \
      --from-db --type price --days "$PRICE_DAYS" --save || exit 1

  run_step "kr:dividend" "$PYTHON" scripts/collect_kr_stocks.py \
      --from-db --type dividend --save --delay "$KR_DELAY" || exit 1

  run_step "kr:financial" "$PYTHON" scripts/collect_kr_stocks.py \
      --from-db --type financial --save --delay "$KR_DELAY" || exit 1
fi

# ---------------------------------------------------------------- step 2 (US)

if [[ "$MARKET" != "KR" ]]; then
  US_TOTAL="$(count_tickers "United States")"
  if [[ -z "$US_TOTAL" || "$US_TOTAL" == "0" ]]; then
    log "FAIL  no US tickers in global_ticker - run without --skip-tickers first"
    exit 1
  fi
  log "US tickers to process: $US_TOTAL (batch=$BATCH, jobs=$JOBS)"

  pids=()
  failed=0

  for (( offset = 0; offset < US_TOTAL; offset += BATCH )); do
    step="us:batch:$offset"

    if [[ $JOBS -le 1 ]]; then
      run_step "$step" "$PYTHON" scripts/collect_us_stocks.py \
          --from-db --type all --save \
          --offset "$offset" --limit "$BATCH" --delay "$US_DELAY" || exit 1
      continue
    fi

    # Parallel batches are safe: the natural-key unique constraints mean two
    # writers touching the same row update it rather than duplicating it.
    run_step "$step" "$PYTHON" scripts/collect_us_stocks.py \
        --from-db --type all --save \
        --offset "$offset" --limit "$BATCH" --delay "$US_DELAY" &
    pids+=($!)

    while (( $(jobs -rp | wc -l) >= JOBS )); do sleep 2; done
  done

  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && { wait "$pid" || failed=1; }
  done

  if [[ $failed -eq 1 ]]; then
    log "FAIL  one or more US batches failed - re-run to resume"
    exit 1
  fi
fi

# ---------------------------------------------------------------- step 3

run_step "metrics" "$PYTHON" scripts/calculate_metrics.py --only-with-data || exit 1

# ---------------------------------------------------------------- done

log "=============================================================="
if [[ $DRY_RUN -eq 1 ]]; then
  log "Dry run complete - nothing was executed"
else
  log "Collection complete. Next:"
  log "  $PYTHON scripts/recommend_stocks.py --use-cache"
  log "  $PYTHON scripts/recommend_stocks.py --market KR --use-cache --disable quick_ratio"
fi
log "=============================================================="
