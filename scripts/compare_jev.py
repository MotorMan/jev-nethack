"""Replay logged Jev decisions against another /v1/systemone endpoint (e.g. a local clone) and compare.

  JEV_ENDPOINT=http://127.0.0.1:11435/v1/systemone .venv/bin/python scripts/compare_jev.py [runs/*/decisions.jsonl ...] [-n 200]

Reports latency p50/p90 plus agreement with the hosted Jev's logged answers: top-1 action, safest pick,
mean |danger delta| and agreement on the bot's 0.6 danger trigger.
"""
import glob, json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jev.bot import questions
from jev.jevapi import Jev

args = sys.argv[1:]
n = int(args.pop(args.index('-n') + 1)) if '-n' in args else 200
args = [a for a in args if a != '-n'] or sorted(glob.glob('runs/*/decisions.jsonl'))[-5:]
rows = [d for f in args for d in map(json.loads, open(f)) if d.get('n_options', 1) > 1 and d.get('answers') and d.get('criteria')][-n:]
jev = Jev(os.environ.get('JEV_API_KEY', ''), 0, os.path.join('runs', 'budget-compare.json'))
lat, act, safe, dd, trig, errs = [], [], [], [], [], 0
for i, d in enumerate(rows):
    try:
        a, meta = jev.ask(d['state'], questions(d['criteria']), timeout=60)
    except RuntimeError as e:
        errs += 1
        print('error:', e, file=sys.stderr)
        continue
    old = d['answers']
    lat.append(meta['latency_ms'])
    act.append(a['action']['choice'] == old['action']['choice'])
    safe.append(a['safest']['choice'] == old['safest']['choice'])
    x, y = a['danger'].get('noul') or 0, old['danger'].get('noul') or 0
    dd.append(abs(x - y))
    trig.append((x >= 0.6) == (y >= 0.6))
    print(f"{i + 1}/{len(rows)} {meta['latency_ms']}ms action {a['action']['choice']} vs {old['action']['choice']}", file=sys.stderr)
if lat:
    q = statistics.quantiles(lat, n=10) if len(lat) > 1 else lat * 9
    pct = lambda v: f'{100 * sum(v) / len(v):.0f}%'
    print(f"{jev.endpoint} ({jev.model}): {len(lat)} decisions, {errs} errors")
    print(f"latency p50 {statistics.median(lat):.0f}ms p90 {q[8]:.0f}ms (hosted logged p50 {statistics.median(d['latency_ms'] for d in rows):.0f}ms)")
    print(f"action agree {pct(act)}, safest agree {pct(safe)}, danger |delta| {statistics.mean(dd):.2f}, >=0.6 trigger agree {pct(trig)}")
