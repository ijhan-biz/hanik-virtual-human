#!/usr/bin/env bash

# Hanik의 비대화형 개선 세션을 반복 실행한다.
# 기본 동작은 로컬 파일만 바꾸며 커밋·푸시·PR은 하지 않는다.

set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
AUTO_DIR="${HANIK_AUTO_DIR:-$ROOT/.hanik-auto}"
LOG_DIR="$AUTO_DIR/logs"
PID_FILE="$AUTO_DIR/pid"
STOP_FILE="$AUTO_DIR/stop"
INTERVAL="${HANIK_AUTO_INTERVAL:-10}"

usage() {
    printf '%s\n' \
        "사용법: $0 [run|stop|status]" \
        "  run     수동으로 멈출 때까지 반복 실행 (기본값)" \
        "  stop    실행 중인 러너에 종료 신호를 보냄" \
        "  status  러너 실행 상태를 표시함"
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

show_status() {
    local pid
    pid="$(read_pid)"
    if is_running "$pid"; then
        printf '실행 중입니다 (PID %s).\n로그: %s\n' "$pid" "$LOG_DIR/runner.log"
    else
        printf '실행 중이 아닙니다.\n'
    fi
}

run_iteration() {
    local before after agent_status
    before="$(python3 -c '
import json
from pathlib import Path
path = Path("state/state.json")
try:
    print(json.loads(path.read_text(encoding="utf-8")).get("iteration", 0))
except (FileNotFoundError, json.JSONDecodeError, OSError):
    print(0)
')"

    printf '\n[%s] Copilot 세션 시작 (직전 반복 %s)\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$before" >> "$LOG_DIR/runner.log"
    copilot \
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

    # 세션이 evaluator를 실행하지 못하고 끝난 경우에만 러너가 보완한다.
    if [ "$after" -eq "$before" ]; then
        printf '[%s] 세션이 반복을 기록하지 않아 evaluator를 보완 실행합니다.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$LOG_DIR/runner.log"
        python3 -m src.hanik_loop >> "$LOG_DIR/runner.log" 2>&1 || true
    fi
}

command="${1:-run}"
case "$command" in
    stop)
        stop_runner
        exit 0
        ;;
    status)
        show_status
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
rm -f "$STOP_FILE"
printf '%s\n' "$$" > "$PID_FILE"

cleanup() {
    rm -f "$PID_FILE"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

printf '[%s] Hanik 자동 러너 시작 (PID %s, 간격 %ss)\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$$" "$INTERVAL" >> "$LOG_DIR/runner.log"
while [ ! -f "$STOP_FILE" ]; do
    run_iteration
    [ "$INTERVAL" -eq 0 ] || sleep "$INTERVAL"
done
printf '[%s] Hanik 자동 러너 종료\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$LOG_DIR/runner.log"
