#!/usr/bin/env bash
# Canary the challenger (S8): move serving traffic to serving-challenger step by step, compare the two
# aliases in Grafana Cloud at every step, and put everything back on the champion if the challenger is
# worse. Runs on the app host (.github/workflows/canary.yaml runs it, with traffic going).
#
#   deploy/canary.sh [RESULT_FILE]
#
# Exit 0: the challenger held every step and now takes 100% of serving traffic; promote it
# (promote.yaml) or send traffic back (deploy/web.sh serving-weights 100 0). Exit 1: aborted, traffic is
# back on the champion. RESULT_FILE (default canary-result.json) records each step's numbers either way.
#
# Prometheus queries use lab/grafana from Secrets Manager (the token needs metrics:read). Metrics reach
# Grafana Cloud about a minute after they happen, so each step holds long enough to see itself.
# No data is never a pass: a step where Grafana saw no challenger requests aborts, and so does any exit
# that isn't a held canary (traffic goes back to the champion). CHAMPION_BASELINE_MS is the champion's
# p95 over the 10 minutes before the first step: at 100% the champion serves nothing, so its current
# p95 is NaN.
set -euo pipefail
cd "$(dirname "$0")/.."
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
RESULT=${1:-canary-result.json}

secret=$(aws secretsmanager get-secret-value --secret-id lab/grafana --query SecretString --output text)
QUERY_URL="$(jq -r '.url | sub("/push$"; "")' <<<"$secret")/api/v1/query"
GRAFANA_USER=$(jq -r .user <<<"$secret") GRAFANA_TOKEN=$(jq -r .token <<<"$secret")
unset secret

promql() { # QUERY -> the first value, or NaN
  { curl -fsS -G -u "$GRAFANA_USER:$GRAFANA_TOKEN" "$QUERY_URL" --data-urlencode "query=$1" || echo '{}'; } | jq -r '.data.result[0].value[1] // "NaN"'
}
p95_ms() { # ALIAS WINDOW: serving's own latency for that alias (contracts/metrics.yaml)
  promql "1000 * histogram_quantile(0.95, sum by (le) (rate(lab_model_predict_duration_seconds_bucket{alias=\"$1\"}[$2])))"
}
error_ratio() { # ALIAS WINDOW: 5xx share of what Traefik sent that alias
  promql "sum(rate(traefik_service_requests_total{service=\"serving-$1@file\",code=~\"5..\"}[$2])) / sum(rate(traefik_service_requests_total{service=\"serving-$1@file\"}[$2]))"
}
requests() { # ALIAS WINDOW: requests served by that alias
  promql "sum(increase(lab_model_predict_duration_seconds_count{alias=\"$1\"}[$2]))"
}
gt() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a != "NaN" && b != "NaN" && a + 0 > b + 0) }'; }
round() { awk -v v="$1" 'BEGIN { if (v == "NaN") print v; else printf "%.1f", v }'; } # for messages

# Decision 020: 10 -> 25 -> 50 -> 100% of serving traffic, 4 minutes each (one minute of Grafana lag plus
# a 2-minute rate window with fresh samples, plus margin). At 5 requests/s, 10% is ~60 challenger
# requests per window: enough for a p95, not for a rare error, so errors abort on any 5xx share over 1%.
STEPS=(10 25 50 100)
HOLD_SECONDS=240
WINDOW=2m

should_abort() { # STEP%: print why and return 0 to abort, return 1 to go on
  local cp95 hp95 cerr
  cp95=$(p95_ms challenger "$WINDOW") hp95=$(p95_ms champion "$WINDOW") cerr=$(error_ratio challenger "$WINDOW")
  [[ $hp95 == NaN ]] && hp95=$CHAMPION_BASELINE_MS # at 100% the champion serves nothing
  if gt "$cerr" 0.01; then echo "challenger 5xx ratio $cerr over 1%"; return 0; fi
  # Relative and absolute: 1.5x the champion's p95 is a regression even when both are fast; 50 ms is the
  # offline gate's budget, so being over it in production means the gate's measurement was wrong.
  if gt "$cp95" "$(awk -v h="$hp95" 'BEGIN { print h * 1.5 }')"; then echo "challenger p95 $(round "$cp95") ms is over 1.5x the champion's $(round "$hp95") ms"; return 0; fi
  if gt "$cp95" 50; then echo "challenger p95 $(round "$cp95") ms is over the 50 ms budget"; return 0; fi
  return 1
}

(( ${#STEPS[@]} )) || { echo "no STEPS: set them in deploy/canary.sh (S8)" >&2; exit 2; }
# serving-challenger loaded what `challenger` pointed at when it started: load what it points at now.
deploy/web.sh reload challenger >/dev/null
status=$(deploy/web.sh status)
champion=$(jq -r '.serving.champion.version // empty' <<<"$status")
challenger=$(jq -r '.serving.challenger.version // empty' <<<"$status")
[[ -n $challenger ]] || { echo "serving-challenger has no model: is there a challenger alias?" >&2; exit 2; }
[[ $challenger != "$champion" ]] || { echo "challenger and champion are the same version (v$champion): nothing to canary" >&2; exit 2; }
CHAMPION_BASELINE_MS=$(p95_ms champion 10m)
echo "canary: challenger v$challenger against champion v$champion (p95 $(round "$CHAMPION_BASELINE_MS") ms), steps ${STEPS[*]}%, ${HOLD_SECONDS}s each"
held=0
restore() { (( held )) || deploy/web.sh serving-weights 100 0; }
trap restore EXIT

steps='[]'
record() { # STEP OUTCOME REASON
  steps=$(jq --argjson w "$1" --arg o "$2" --arg r "$3" --arg cp "$(p95_ms challenger "$WINDOW")" --arg hp "$(p95_ms champion "$WINDOW")" \
    --arg ce "$(error_ratio challenger "$WINDOW")" --arg cn "$(requests challenger "$WINDOW")" \
    '. + [{weight: $w, outcome: $o, reason: $r, challenger_p95_ms: $cp, champion_p95_ms: $hp, challenger_error_ratio: $ce, challenger_requests: $cn}]' <<<"$steps")
}
finish() { # OUTCOME
  jq -n --arg o "$1" --arg ch "$challenger" --arg cv "$champion" --argjson steps "$steps" --arg at "$(date -u +%FT%TZ)" \
    '{outcome: $o, challenger_version: $ch, champion_version: $cv, steps: $steps, finished_at: $at}' > "$RESULT"
  cat "$RESULT"
}

for w in "${STEPS[@]}"; do
  deploy/web.sh serving-weights $((100 - w)) "$w"
  sleep "$HOLD_SECONDS"
  seen=$(requests challenger "$WINDOW")
  if ! gt "$seen" 0; then
    reason="Grafana saw no challenger requests in the last $WINDOW: nothing to judge (is Alloy sending? is traffic running?)"
  elif ! reason=$(should_abort "$w"); then
    reason=""
  fi
  if [[ -n $reason ]]; then
    record "$w" aborted "$reason"
    deploy/web.sh serving-weights 100 0
    echo "ABORTED at ${w}%: $reason. Serving traffic is back on the champion." >&2
    finish aborted
    exit 1
  fi
  record "$w" passed ""
  echo "step ${w}%: passed"
done
held=1
finish held
echo "challenger v$challenger held at 100%. Promote it (promote.yaml) or send traffic back: deploy/web.sh serving-weights 100 0"
