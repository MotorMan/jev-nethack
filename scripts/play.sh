#!/bin/sh
# (Re)start one bot instance: scripts/play.sh NAME PORT [ENDPOINT MODEL [LABEL]]   (LABEL names the engine in runs/watch)
#   scripts/play.sh Jev 8770                                   # hosted Jev, the main game (runs/)
#   scripts/play.sh Jeff08 8791 http://127.0.0.1:8781/v1/systemone Jeff-Qwen3.5-0.8B   # own save + runs/Jeff08/
#   scripts/play.sh Jev 8770 http://127.0.0.1:8781/v1/systemone Jeff-Qwen3.5-0.8B    # "use X": continue Jev's game on X
# NAME is the NetHack player name, so each instance keeps its own save file; a restart resumes it.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Load .env if present
if [ -f .env ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            ''|\#*) continue ;;
        esac
        # strip surrounding quotes
        value=$(printf '%s' "$value" | sed 's/^"\(.*\)"$/\1/; s/^'\''\(.*\)'\''$/\1/')
        export "$key=$value"
    done < .env
fi

NAME=$1 PORT=$2
[ -n "$NAME" ] && [ -n "$PORT" ] || { sed -n 2,6p "$0"; exit 1; }
LOG=runs/server.log; [ "$NAME" = Jev ] || { mkdir -p "runs/$NAME"; LOG=runs/$NAME/server.log; }
pids() { pgrep -f "jev.server --name $NAME --port" ; }
kill $(pids) 2>/dev/null
for i in $(seq 20); do pids >/dev/null || break; sleep 0.5; done
if [ -n "$3" ]; then export JEV_ENDPOINT=$3 JEV_MODEL=${4:-jev-latest} JEV_LABEL=$5; else unset JEV_ENDPOINT JEV_MODEL JEV_LABEL; fi
JEV_CHAR=${JEV_CHAR:-Valkyrie:dwarf:female:lawful} JEV_BUDGET_USD=${JEV_BUDGET_USD:-25} nohup .venv/bin/python -u -m jev.server --name "$NAME" --port "$PORT" --char "${JEV_CHAR}" >> "$LOG" 2>&1 &
for i in $(seq 30); do curl -s -XPOST "127.0.0.1:$PORT/api/control" -d '{"action":"speed","delay_ms":0}' >/dev/null && break; sleep 1; done
echo "$NAME on http://127.0.0.1:$PORT (${JEV_ENDPOINT:-hosted Jev}) char=${JEV_CHAR} log $LOG"
