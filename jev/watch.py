"""Watch Jev play in a terminal: python -m jev.watch [URL ...]   (default: ports 8770-8772; keys 1-9, tab or arrows switch games, q quits)"""
import json, select, shutil, sys, termios, time, tty, urllib.request

URLS = [u.rstrip('/') + '/api/state' for u in sys.argv[1:]] or [f'http://127.0.0.1:{p}/api/state' for p in (8770, 8771, 8772)]
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


def frame(s, tabs=''):
    w, rows = shutil.get_terminal_size()
    st, d, j, run = s['status'], s['decision'], s['jev'], s['run']
    model = (run.get('models') or [run.get('engine') or j.get('last_model') or 'Jev'])[-1]  # the version the engine reports (jev-1.13.0, a Jeff checkpoint...)
    recent = [h['latency_ms'] for h in s['history'] if h.get('latency_ms')][-10:]  # single-option turns skip the engine: 0 ms
    lines = [f"{BOLD}{st.get('name') or 'Jev'} plays NetHack{RST} on {BOLD}\x1b[96m{model}{RST}{f' {sum(recent) // len(recent)}ms' if recent else ''}  {DIM}{s['mode']} · run {run['id']} · {s['phase']}{' · PAUSED' if s['paused'] else ''}{RST}",
             tabs or f"{DIM}{'─' * min(w, 80)}{RST}"]
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
    lines.append(f"{BOLD}{model}{RST} {j['calls']} calls{'' if run.get('engine') not in (None, 'jev') else f' · ${j[chr(99) + "ost_usd"]:.2f}'} · avg {j['avg_latency_ms']} ms   "
                 f"{BOLD}Run{RST} max Dlvl {run['max_dlvl']} · {run['decisions']} decisions")
    for r in deaths[::-1]:
        lines.append(f"  {DIM}✝ T{r['turns']} Dlvl {r['max_dlvl']}: {r['death'][:w - 24]}{RST}")
    return '\x1b[H' + '\n'.join(l + RST + '\x1b[K' for l in lines[:rows]) + '\x1b[J'  # never taller than the terminal: scrolling pushed the title off


def label(url):
    try:
        s = json.load(urllib.request.urlopen(url, timeout=1))
        return f"{s['status'].get('name') or '?'}·{(s['run'].get('models') or [s['run'].get('engine') or 'jev'])[-1]} T{s['status'].get('turn') or 0}"
    except (OSError, ValueError, KeyError):
        return url.split(':')[-1].split('/')[0] + ' down'


def main():
    names, seen = {i: label(u) for i, u in enumerate(URLS)}, time.time()
    cur = next((i for i, n in names.items() if not n.endswith(' down')), 0)  # start on a live game, not a stopped engine
    tty_ok = sys.stdin.isatty()
    old = termios.tcgetattr(sys.stdin) if tty_ok else None
    if tty_ok:
        tty.setcbreak(sys.stdin)
    sys.stdout.write('\x1b[?25l\x1b[?7l\x1b[2J')  # no auto-wrap: a long line wrapping also scrolled
    try:
        while True:
            while tty_ok and select.select([sys.stdin], [], [], 0)[0]:
                k = sys.stdin.read(1)
                if k == 'q':
                    return
                if k == '\x1b' and select.select([sys.stdin], [], [], 0.05)[0]:
                    k += sys.stdin.read(2)  # arrow keys: ESC [ A-D
                if k in ('\t', '\x1b[C', '\x1b[B'):
                    cur = (cur + 1) % len(URLS)
                elif k in ('\x1b[D', '\x1b[A'):
                    cur = (cur - 1) % len(URLS)
                elif k.isdigit() and 0 < int(k) <= len(URLS):
                    cur = int(k) - 1
                sys.stdout.write('\x1b[2J')
            if time.time() - seen > 5:  # the other games' turn counters
                names, seen = {i: label(u) for i, u in enumerate(URLS)}, time.time()
            tabs = '  '.join((f'{BOLD}\x1b[7m {i + 1} {n} {RST}' if i == cur else f'{DIM}{i + 1} {n}{RST}') for i, n in names.items()) if len(URLS) > 1 else ''
            try:
                s = json.load(urllib.request.urlopen(URLS[cur], timeout=5))
                sys.stdout.write(frame(s, tabs))
            except OSError as e:
                sys.stdout.write(f'\x1b[H\x1b[2J{tabs}\nwaiting for server at {URLS[cur]}: {e}')
            sys.stdout.flush()
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        if tty_ok:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
        sys.stdout.write('\x1b[?25h\x1b[?7h' + RST + '\n')


if __name__ == '__main__':
    main()
