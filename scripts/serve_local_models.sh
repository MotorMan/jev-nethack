#!/usr/bin/env bash
# Start local Jev-protocol (/v1/systemone) decision servers side by side, one port each. Idempotent: a port that
# already answers is left alone; checkouts and downloads that exist are reused. Logs: runs/models/<name>.log.
#
#   scripts/serve_local_models.sh            # start everything, then smoke-test each port
#   ONLY=jeff-gemma scripts/serve_local_models.sh   # just one (downloads only its checkpoint)
#   scripts/serve_local_models.sh check      # smoke-test only
#   scripts/serve_local_models.sh stop       # stop everything this script started
#
# Point the bot at one:  JEV_ENDPOINT=http://127.0.0.1:<port>/v1/systemone JEV_MODEL=<model> ...
#   8781 jeff-0.8b    JEV_MODEL=jeff-latest   (MLX)
#   8782 jeff-2b      JEV_MODEL=jeff-latest   (MLX)
#   8783 jeff-gemma   JEV_MODEL=jeff-latest   (PyTorch on MPS: Jeff's MLX path runs Qwen only)
#   8784 kev-4b       JEV_MODEL=jev-latest    (MLX; Kev also accepts kev-latest)
#   8785 kev-0.8b     JEV_MODEL=jev-latest    (MLX)
#   8080 openjev      JEV_MODEL=jev-latest    (MLX, DiffusionGemma 26B-A4B 4-bit: ~16 GB disk + RAM; port is its fixed default)
# Must run outside the nono sandbox: MLX/MPS need the Metal GPU, and checkouts live in $MODELS_DIR (default ~/dev).
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
models_dir=${MODELS_DIR:-$HOME/dev}
logs=$repo/runs/models
jeff_dir=$models_dir/jeff
kev_dir=$models_dir/kev
JEFF_COMMIT=f06788292874c21a5b5c41549ac220dd9e15da7f   # v1.1 (2026-09-29); the commit local-jev-bench measured
KEV_COMMIT=90512f1c517d977741f2104470a40635408236c9    # main on 2026-09-30 (Kev-9B v2 release)
uv12=(uvx --from 'uv>=0.12.19' uv)                    # Jeff's pyproject requires uv >= 0.12.19 (brew uv may be older)
mkdir -p "$logs"

want() { [ -z "${ONLY:-}" ] || [ "$ONLY" = "$1" ]; }
up() { nc -z 127.0.0.1 "$1" 2>/dev/null; }

checkout() {  # checkout <dir> <url> <commit>
    [ -d "$1/.git" ] || git clone -q "$2" "$1"
    if [ "$(git -C "$1" rev-parse HEAD)" != "$3" ]; then
        git -C "$1" fetch -q origin
        git -C "$1" checkout -q "$3"
    fi
}

start() {  # start <name> <port> <dir> <command...>; env for the server comes from the caller
    local name=$1 port=$2 dir=$3; shift 3
    want "$name" || return 0
    if up "$port"; then echo "$name: port $port already serving, left alone"; return; fi
    (cd "$dir" && nohup "$@" >"$logs/$name.log" 2>&1 & echo $! >"$logs/$name.pid")
    echo "$name: starting on $port (log runs/models/$name.log)"
}

setup_jeff() {
    checkout "$jeff_dir" https://github.com/firelex/jeff "$JEFF_COMMIT"
    (cd "$jeff_dir" && "${uv12[@]}" sync -q --no-default-groups --extra mac)
    local repo_id dir
    for pair in Jeff-Qwen3.5-0.8B:jeff-0.8b Jeff-Qwen3.5-2B:jeff-2b Jeff-Gemma4-E2B:jeff-gemma4-e2b; do
        repo_id=${pair%%:*} dir=checkpoints/${pair#*:}
        want "${pair#*:}" || { [ "${pair#*:}" = jeff-gemma4-e2b ] && want jeff-gemma; } || continue
        [ -f "$jeff_dir/$dir/readout.safetensors" ] && continue
        # the 0.8B repo also holds demo videos; only the model files are needed
        (cd "$jeff_dir" && "${uv12[@]}" run -q --no-default-groups hf download "mstrasser/$repo_id" --local-dir "$dir" --exclude 'videos/*' --exclude 'assets/*')
    done
}

setup_kev() {
    checkout "$kev_dir" https://github.com/jaredpalmer/kev "$KEV_COMMIT"
    (cd "$kev_dir" && uv sync -q --extra serve)   # weights download on first start into the HF cache
}

jeff() {  # jeff <name> <port> <checkpoint dir> <backend>
    local dev=()
    [ "$4" = pytorch ] && dev=(JEFF_DEVICE=mps)
    start "$1" "$2" "$jeff_dir" env JEFF_BACKEND="$4" ${dev[@]+"${dev[@]}"} JEFF_CHECKPOINT="checkpoints/$3" JEFF_HOST=127.0.0.1 PORT="$2" \
        "${uv12[@]}" run --no-default-groups --extra mac jeff-serve
}

setup_openjev() {  # razorback16/openjev: weights (mlx-community/diffusiongemma-26B-A4B-it-4bit) download on first start
    [ -d "$models_dir/openjev/.git" ] || git clone -q https://github.com/razorback16/openjev "$models_dir/openjev"
    (cd "$models_dir/openjev" && { [ -d .venv ] || uv venv -q -p 3.12; } && uv pip install -q -e '.[mlx]')
}

kev() {  # kev <name> <port> <hub run>
    start "$1" "$2" "$kev_dir" env PYTHONUNBUFFERED=1 uv run --extra serve python -m kev.serve --run "$3" --host 127.0.0.1 --port "$2"
}

check() {  # POST one NetHack-shaped request (choice + noul + choice) to each port, as the bot does
    local name port model
    for spec in jeff-0.8b:8781:jeff-latest jeff-2b:8782:jeff-latest jeff-gemma:8783:jeff-latest kev-4b:8784:jev-latest kev-0.8b:8785:jev-latest openjev:8080:jev-latest; do
        IFS=: read -r name port model <<<"$spec"
        want "$name" || continue
        python3 - "$name" "$port" "$model" <<'EOF'
import json, sys, time, urllib.request
name, port, model = sys.argv[1:]
url = f'http://127.0.0.1:{port}/v1/systemone'
crit = {'attack': 'Attack the jackal. It is adjacent to the east and weak.', 'flee': 'Walk away west. Two steps to the stairs.',
        'rest': 'Search here 15 turns. Regain HP; interrupted if a monster appears.'}
body = dict(model=model, state='NetHack. You are a Valkyrie, HP 9/16, Dlvl 2. A jackal is adjacent to the east.', questions={
    'action': dict(type='choice', instructions='Choose the single best action.', criteria=crit),
    'danger': dict(type='noul', instructions='Is the Valkyrie in serious danger of dying within the next few turns?'),
    'safest': dict(type='choice', instructions='Which action is safest?', criteria=crit)})
deadline = time.time() + 600  # first start downloads weights and loads the model
while True:
    try:
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json'}), timeout=120).read())
        ms = []
        for _ in range(3):  # warm calls
            t = time.time(); urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json'}), timeout=120).read(); ms.append((time.time() - t) * 1000)
        a = r['answers']
        print(f"{name}: OK  JEV_ENDPOINT={url} JEV_MODEL={model}  warm {sorted(ms)[1]:.0f} ms (short state)  "
              f"action={a['action']['choice']} danger={a['danger']['noul']:.2f} safest={a['safest']['choice']}")
        break
    except Exception as e:
        if time.time() > deadline:
            print(f'{name}: FAILED on {url}: {e} (see runs/models/{name}.log)'); break
        time.sleep(5)
EOF
    done
}

case "${1:-start}" in
    stop)
        for f in "$logs"/*.pid; do [ -f "$f" ] && { pkill -P "$(cat "$f")" 2>/dev/null; kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; }; done
        echo stopped ;;
    check) check ;;
    start)
        case "${ONLY:-jeff}" in jeff*) setup_jeff ;; esac
        case "${ONLY:-kev}" in kev*) setup_kev ;; esac
        case "${ONLY:-openjev}" in openjev) setup_openjev ;; esac
        jeff jeff-0.8b 8781 jeff-0.8b mlx
        jeff jeff-2b 8782 jeff-2b mlx
        jeff jeff-gemma 8783 jeff-gemma4-e2b pytorch
        kev kev-4b 8784 jaredpalmer/kev-4b
        kev kev-0.8b 8785 jaredpalmer/kev-0.8b
        start openjev 8080 "$models_dir/openjev" env OPENJEV_BACKEND=mlx PYTHONUNBUFFERED=1 .venv/bin/python -m openjev
        check ;;
    *) echo "usage: $0 [start|check|stop]" >&2; exit 2 ;;
esac
