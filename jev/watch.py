"""Watch Jev play in a terminal: python -m jev.watch [http://127.0.0.1:8770]"""
import json, shutil, sys, time, urllib.request

URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8770') + '/api/state'
FG = {'black': 30, 'red': 31, 'green': 32, 'brown': 33, 'yellow': 93, 'blue': 34, 'magenta': 35, 'cyan': 36, 'white': 37,
      'brightblack': 90, 'brightred': 91, 'brightgreen': 92, 'brightyellow': 93, 'brightblue': 94, 'brightmagenta': 95,
      'brightcyan': 96, 'brightwhite': 97}
DIM, BOLD, RST = '\x1b[2m', '\x1b[1m', '\x1b[0m'


def screen(rows):
    out = []
    for row in rows:
        line = ''
        for text, fg, _bg, bold, rev in row:
            codes = [str(FG[fg])] if fg in FG else []
            codes += ['1'] if bold else []
            codes += ['7'] if rev else []
            line += (f"\x1b[{';'.join(codes)}m{text}{RST}" if codes else text)
        out.append(line)
    return out


def bar(p, w=20):
    n = round(p * w)
    return '█' * n + '·' * (w - n)


def frame(s):
    w, rows = shutil.get_terminal_size()
    st, d, j, run = s['status'], s['decision'], s['jev'], s['run']
    lines = [f"{BOLD}Jev plays NetHack{RST}  {DIM}{s['mode']} · run {run['id']} · {s['phase']}{' · PAUSED' if s['paused'] else ''}{RST}",
             f"{DIM}{'─' * min(w, 80)}{RST}"]
    lines += screen(s['screen']['rows'])
    lines.append(f"{DIM}{'─' * min(w, 80)}{RST}")
    opts = sorted(d.get('options') or [], key=lambda o: -(o.get('p') or 0))[:6]
    if d.get('pending'):
        lines.append(f"{BOLD}Decision T{d.get('turn')}{RST}  {DIM}Jev is deciding between {len(d.get('options') or [])} options…{RST}")
        opts = [dict(o, p=0) for o in opts]
    else:
        lines.append(f"{BOLD}Decision T{d.get('turn')}{RST}  confidence {d.get('confidence') or 0:.2f}  danger {d.get('danger') or 0:.2f}  {DIM}{d.get('latency_ms') or 0} ms{RST}")
    for o in opts:
        mark = f'{BOLD}\x1b[92m▶{RST}' if o['id'] == d.get('choice') else ' '
        lines.append(f" {mark} {bar(o.get('p') or 0)} {(o.get('p') or 0):.2f}  {o['label'][:w - 34]}")
    lines.append(f"{BOLD}Recent{RST}")
    for h in s['history'][-5:][::-1]:
        lines.append(f"  {DIM}T{h['turn']:<6}{RST} {h['label'][:38]:<38} {DIM}→ {h['outcome'][:w - 52]}{RST}")
    deaths = [r for r in s['runs'] if r.get('death')][-3:]
    lines.append(f"{BOLD}Jev{RST} {j['calls']} calls · ${j['cost_usd']:.2f} · avg {j['avg_latency_ms']} ms   "
                 f"{BOLD}Run{RST} max Dlvl {run['max_dlvl']} · {run['decisions']} decisions")
    for r in deaths[::-1]:
        lines.append(f"  {DIM}✝ T{r['turns']} Dlvl {r['max_dlvl']}: {r['death'][:w - 24]}{RST}")
    return '\x1b[H' + '\n'.join(l + RST + '\x1b[K' for l in lines[:rows]) + '\x1b[J'  # never taller than the terminal: scrolling pushed the title off


def main():
    sys.stdout.write('\x1b[?25l\x1b[?7l\x1b[2J')  # no auto-wrap: a long line wrapping also scrolled
    try:
        while True:
            try:
                s = json.load(urllib.request.urlopen(URL, timeout=5))
                sys.stdout.write(frame(s))
            except OSError as e:
                sys.stdout.write(f'\x1b[H\x1b[2Jwaiting for server at {URL}: {e}')
            sys.stdout.flush()
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write('\x1b[?25h\x1b[?7h' + RST + '\n')


if __name__ == '__main__':
    main()
