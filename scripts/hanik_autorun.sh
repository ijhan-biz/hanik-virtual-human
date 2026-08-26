#!/usr/bin/env bash

# Hanik의 비대화형 개선 세션을 반복 실행한다.
# 기본 동작은 로컬 파일만 바꾸며 커밋·푸시·PR은 하지 않는다.

set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
AUTO_DIR="${HANIK_AUTO_DIR:-$ROOT/.hanik-auto}"
LOG_DIR="$AUTO_DIR/logs"
PID_FILE="$AUTO_DIR/pid"
STOP_FILE="$AUTO_DIR/stop"
FINISH_FILE="$ROOT/state/finish"
INTERVAL="${HANIK_AUTO_INTERVAL:-10}"
# 세션이 쓸 모델. 반복이 남기는 글의 질은 전적으로 세션의 판단에 달려 있으므로
# 모델은 러너의 설정 가운데 가장 무거운 것이다. `auto`로 두면 반복마다 달라질 수
# 있어, 무엇이 이 문서를 썼는지 나중에 되짚을 수 없다.
MODEL="${HANIK_MODEL:-gpt-5.6-luna}"
# 이 로컬 러너는 셸에 주입된 GH_TOKEN보다 Copilot CLI의 저장된 로그인
# 자격 증명을 사용한다. GH_TOKEN에는 조직·엔터프라이즈 선택 정보가 없어
# "Usage billed to" 오류가 나므로, 세션을 시작할 때만 인증 환경 변수를
# 제거한다. 토큰 값은 로그에 쓰지 않는다.
COPILOT_AUTH_ENV=(env -u GH_TOKEN -u GITHUB_TOKEN -u COPILOT_GITHUB_TOKEN)
# 원시 로그가 이 크기를 넘으면 한 번만 회전시킨다. 러너는 세션마다 수천 줄을
# 쏟아내지만 남을 가치가 있는 것은 state/sessions.md와 SUMMARY.md에 추려진다.
LOG_MAX_BYTES="${HANIK_LOG_MAX_BYTES:-2000000}"
# 세션이 아예 실행되지 못한 채(인증 실패, 네트워크 단절 등) 끝나는 일이 이만큼
# 이어지면 러너를 멈춘다. 이것은 정체가 아니라 환경 고장이므로 따로 센다.
DEAD_LIMIT="${HANIK_DEAD_LIMIT:-10}"
# 죽은 세션 뒤 기다리는 시간. 회를 거듭할수록 늘려 잠깐의 단절에는 버티고
# 오래가는 고장에는 매달리지 않는다. 기본값으로 약 35분을 버틴다 — 잠든
# 노트북이 깨어나 네트워크를 되찾는 데 걸리는 시간을 관측해 잡았다.
DEAD_BACKOFF="${HANIK_DEAD_BACKOFF:-60}"
# 한 번에 기다리는 시간의 상한. 없으면 대기가 끝없이 길어져, 네트워크가 돌아와도
# 러너가 몇 시간 뒤에야 알아차린다.
DEAD_BACKOFF_MAX="${HANIK_DEAD_BACKOFF_MAX:-300}"

usage() {
    printf '%s\n' \
        "사용법: $0 [run|stop|finish|status|summary]" \
        "  run      수동으로 멈추거나 루프가 물러날 때까지 반복 실행 (기본값)" \
        "  stop     실행 중인 러너에 종료 신호를 보냄 (캠페인은 열어 둔 채)" \
        "  finish   캠페인을 마감함: 러너를 멈추고 마지막 결산을 남김" \
        "  status   러너 실행 상태와 결산 요약을 표시함" \
        "  summary  현재 결산(SUMMARY.md)의 요점을 표시함"
}

log() {
    printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$LOG_DIR/runner.log"
}

rotate_log() {
    local size
    [ -f "$LOG_DIR/runner.log" ] || return 0
    size="$(wc -c < "$LOG_DIR/runner.log" 2>/dev/null | tr -d ' ')"
    [ -n "$size" ] || return 0
    if [ "$size" -gt "$LOG_MAX_BYTES" ]; then
        mv -f "$LOG_DIR/runner.log" "$LOG_DIR/runner.log.1"
        log "이전 로그를 runner.log.1로 회전시켰습니다 (${size} bytes)."
    fi
}

read_pid() {
    if [ -f "$PID_FILE" ]; then
        read -r pid < "$PID_FILE"
        printf '%s' "$pid"
    fi
}

is_running() {
    local pid="${1:-}"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

stop_runner() {
    local pid
    mkdir -p "$AUTO_DIR"
    pid="$(read_pid)"
    if is_running "$pid"; then
        kill "$pid"
        printf '종료 신호를 보냈습니다 (PID %s).\n' "$pid"
    else
        printf '실행 중인 러너가 없습니다.\n'
        rm -f "$PID_FILE"
    fi
    touch "$STOP_FILE"
}

show_summary() {
    if [ ! -f "$ROOT/SUMMARY.md" ]; then
        printf '아직 결산이 없습니다. `python3 -m src.hanik_loop`을 한 번 실행하세요.\n'
        return 0
    fi
    awk '/^## 분량 회계/{exit} {print}' "$ROOT/SUMMARY.md"
    printf -- '---\n전문: SUMMARY.md · 세션별 기록: state/sessions.md\n'
}

finish_campaign() {
    mkdir -p "$AUTO_DIR" "$ROOT/state"
    printf '%s\n' \
        "사람이 이 캠페인을 마감했다." \
        "이 파일이 있는 한 루프는 반복을 기록한 뒤 물러난다." \
        "다시 열려면 이 파일을 지워라." > "$FINISH_FILE"
    stop_runner >/dev/null 2>&1 || true

    printf '캠페인을 마감합니다. 마지막 결산을 만듭니다...\n'
    ( cd "$ROOT" && python3 -m src.hanik_loop ) || true
    printf '\n'
    show_summary
}

show_status() {
    local pid
    pid="$(read_pid)"
    if is_running "$pid"; then
        printf '실행 중입니다 (PID %s).\n모델: %s\n로그: %s\n' "$pid" "$MODEL" "$LOG_DIR/runner.log"
    elif [ -f "$FINISH_FILE" ]; then
        printf '마감되었습니다. 다시 열려면 %s를 지우세요.\n' "$FINISH_FILE"
    else
        printf '실행 중이 아닙니다.\n'
    fi
    printf '\n'
    show_summary
}

artifact_fingerprint() {
    # Hanik.md와 반론 전체의 내용 해시. 세션이 산출물을 건드렸는지 가른다.
    ( cd "$ROOT" && python3 -c '
import hashlib
from pathlib import Path

digest = hashlib.sha256()
document = Path("Hanik.md")
digest.update(document.read_bytes() if document.is_file() else b"")
objections = Path("objections")
for path in sorted(objections.glob("*.md")) if objections.is_dir() else []:
    digest.update(path.name.encode("utf-8"))
    digest.update(path.read_bytes())
print(digest.hexdigest())
' 2>/dev/null ) || printf 'unknown\n'
}

run_iteration() {
    local before after agent_status verdict fingerprint_before fingerprint_after
    rotate_log
    fingerprint_before="$(artifact_fingerprint)"
    before="$(python3 -c '
import json
from pathlib import Path
path = Path("state/state.json")
try:
    print(json.loads(path.read_text(encoding="utf-8")).get("iteration", 0))
except (FileNotFoundError, json.JSONDecodeError, OSError):
    print(0)
')"

    log "Copilot 세션 시작 (모델 $MODEL · 직전 반복 $before)"
    "${COPILOT_AUTH_ENV[@]}" copilot \
        -C "$ROOT" \
        --prompt "$(cat <<'PROMPT'
이 저장소의 자동 Hanik 개선 러너가 시작한 단일 작업 세션이다.

1. 반드시 AGENTS.md와 state/next-session.md를 먼저 읽어라.
2. 브리프의 첫 번째 열린 반론 하나만 이번 세션의 주 작업으로 삼아라. 해소 조건이 요구하는 내용을 Hanik.md의 대상 조건에 실제로 다시 써라.
3. 반론의 본문·제목·대상·해소 조건을 약화하거나 수정하지 마라. 반론을 삭제·개명·재개방하지 마라. 구조 변경으로 대상이 사라지는 정당한 경우에만 superseded를 사용하고, 해소 항목에 후속 반론을 명시하라. 규칙을 통과시키려고 src/integrity.py나 tests/를 약화하지 마라.
4. 해소 뒤 방금 고친 논증에서 새 전제나 미해결 문제를 찾아 새 반론을 하나 이상 작성하라. 미해결 반론이 상한에 이르렀다고 브리프가 말할 때만 새 반론 의무가 면제된다.
5. python3 -m pytest tests/ -v를 실행하고, 마지막에 python3 -m src.hanik_loop을 실행하라. 실패하면 원인을 고친 뒤 다시 검증하라.
6. 이 러너가 반복과 로그를 관리하므로 커밋·푸시·풀 리퀘스트는 만들지 말고 작업 트리에 변경을 남겨라. 질문하지 말고 위 절차를 끝까지 자율적으로 수행하라.
PROMPT
)" \
        --mode autopilot \
        --model "$MODEL" \
        --no-ask-user \
        --allow-all-tools \
        --allow-all-paths \
        --deny-url='*' \
        --disable-builtin-mcps \
        --no-remote \
        --no-remote-export \
        --no-auto-update \
        --log-dir "$LOG_DIR/copilot" \
        --silent >> "$LOG_DIR/runner.log" 2>&1
    agent_status=$?

    after="$(python3 -c '
import json
from pathlib import Path
path = Path("state/state.json")
try:
    print(json.loads(path.read_text(encoding="utf-8")).get("iteration", 0))
except (FileNotFoundError, json.JSONDecodeError, OSError):
    print(0)
')"
    printf '[%s] Copilot 종료 코드 %s (현재 반복 %s)\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$agent_status" "$after" >> "$LOG_DIR/runner.log"

    fingerprint_after="$(artifact_fingerprint)"

    # 세션이 반복도 기록하지 않고 산출물도 건드리지 않았다면 아무 일도 일어나지
    # 않은 것이다. 이때 evaluator를 보완 실행하면 시도조차 없었던 반복이 위반으로
    # 원장에 남고, 그것이 쌓여 정체로 오판된다. 정체는 "세션이 문서를 고치지
    # 못한다"는 뜻이지 "세션이 실행되지 않았다"는 뜻이 아니다.
    if [ "$after" -eq "$before" ] && [ "$fingerprint_before" = "$fingerprint_after" ]; then
        log "세션이 아무것도 남기지 않았습니다 (종료 코드 $agent_status). 반복으로 세지 않습니다."
        return 4
    fi

    # 세션이 일은 했는데 evaluator를 실행하지 못하고 끝난 경우에만 러너가 보완한다.
    if [ "$after" -eq "$before" ]; then
        log "세션이 반복을 기록하지 않아 evaluator를 보완 실행합니다."
        python3 -m src.hanik_loop >> "$LOG_DIR/runner.log" 2>&1 || true
    fi

    # 세션이 스스로 루프를 돌리므로 러너는 그 종료 코드를 보지 못한다.
    # 물러나야 하는지는 따로 묻는다.
    verdict="$(python3 -m src.conclusion 2>&1)"
    if python3 -m src.conclusion --quiet; then
        return 0
    fi
    log "루프가 물러납니다: $verdict"
    printf '\n%s\n' "$verdict"
    return 3
}

command="${1:-run}"
case "$command" in
    stop)
        stop_runner
        exit 0
        ;;
    finish)
        mkdir -p "$LOG_DIR"
        finish_campaign
        exit 0
        ;;
    status)
        mkdir -p "$LOG_DIR"
        show_status
        exit 0
        ;;
    summary)
        show_summary
        exit 0
        ;;
    run)
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

case "$INTERVAL" in
    ''|*[!0-9]*)
        printf 'HANIK_AUTO_INTERVAL은 0 이상의 정수여야 합니다.\n' >&2
        exit 2
        ;;
esac

mkdir -p "$LOG_DIR"
existing_pid="$(read_pid)"
if is_running "$existing_pid"; then
    printf '이미 실행 중입니다 (PID %s).\n' "$existing_pid" >&2
    exit 1
fi
if [ -f "$FINISH_FILE" ]; then
    printf '이 캠페인은 마감되었습니다. 다시 열려면 %s를 지우세요.\n' "$FINISH_FILE" >&2
    exit 1
fi
rm -f "$STOP_FILE"
printf '%s\n' "$$" > "$PID_FILE"

cleanup() {
    rm -f "$PID_FILE"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

log "Hanik 자동 러너 시작 (PID $$, 간격 ${INTERVAL}s, 모델 $MODEL)"
concluded=0
dead=0
dead_streak=0
while [ ! -f "$STOP_FILE" ]; do
    run_iteration
    status=$?
    if [ "$status" -eq 3 ]; then
        concluded=1
        break
    fi
    if [ "$status" -eq 4 ]; then
        dead_streak=$((dead_streak + 1))
        if [ "$dead_streak" -ge "$DEAD_LIMIT" ]; then
            dead=1
            break
        fi
        wait_for=$((DEAD_BACKOFF * dead_streak))
        [ "$wait_for" -le "$DEAD_BACKOFF_MAX" ] || wait_for="$DEAD_BACKOFF_MAX"
        log "죽은 세션 ${dead_streak}/${DEAD_LIMIT}회 연속입니다. ${wait_for}s 뒤 다시 시도합니다."
        sleep "$wait_for"
        continue
    fi
    dead_streak=0
    [ "$INTERVAL" -eq 0 ] || sleep "$INTERVAL"
done

if [ "$concluded" -eq 1 ]; then
    log "루프가 물러나 러너를 멈춥니다. 결산은 SUMMARY.md에 있습니다."
    printf '\n루프가 물러났습니다. 결산:\n\n'
    show_summary
elif [ "$dead" -eq 1 ]; then
    log "세션이 ${DEAD_LIMIT}회 연속으로 실행되지 못해 러너를 멈춥니다."
    printf '\n세션이 %s회 연속으로 실행되지 못했습니다.\n\n' "$DEAD_LIMIT"
    printf '이것은 정체가 아니라 환경 고장입니다. 반복은 기록되지 않았습니다.\n'
    printf '네트워크와 인증을 확인한 뒤 다시 시작하세요:\n\n'
    printf '  gh auth status\n'
    printf '  %s run\n\n' "$0"
    printf '마지막 로그: %s\n' "$LOG_DIR/runner.log"
else
    log "Hanik 자동 러너 종료 (사람이 멈춤)"
fi
