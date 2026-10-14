"""Play on hardfought.org: log in through dgamelaunch and start NetHack 5.0.

Transport is the site's web terminal (wss://, via jev.wsbridge) because port 22 is often firewalled;
set HARDFOUGHT_SSH=1 to use ssh instead. One-time setup: paste jev/nethackrc into the NetHack 5.0 rc
at https://www.hardfought.org/nethack/rcedit/ (the bot relies on number_pad:0, menustyle:full, etc).
"""
import os, re, sys, time
from .term import Term


# NEVER more than 2-3 actions/sec on a public server (HF, NAO): every send, including the login keys, waits at least this long.
# Term.floor enforces it below the UI delay, so the delay slider cannot go faster. Any NAO launcher must pass the same floor.
REMOTE_GAP = 0.4  # 2.5 sends/sec


def wait_for(t, pattern, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        t.pump(0.5)
        text = '\n'.join(t.lines())
        m = re.search(pattern, text, re.M)
        if m:
            return m
        if not t.alive:
            break
    raise RuntimeError(f'hardfought: timed out waiting for {pattern!r}; screen:\n' + '\n'.join(l.rstrip() for l in t.lines() if l.strip()))


def game_key(text):
    """dgamelaunch menu letter for NetHack 5.0 play (not watch/edit)."""
    for line in text.split('\n'):
        m = re.match(r'\s*([a-zA-Z0-9])\)\s+(?:Play\s+)?NetHack\s+5\.0', line, re.I)
        if m:
            return m[1]
    return None


def launcher(username, password):
    if not username or not password:
        raise SystemExit('HARDFOUGHT_USERNAME / HARDFOUGHT_PASSWORD are empty in .env')

    def launch():
        if os.environ.get('HARDFOUGHT_SSH'):
            t = Term(['ssh', '-o', 'StrictHostKeyChecking=accept-new', 'nethack@hardfought.org'], idle=0.3, floor=REMOTE_GAP)
        else:
            t = Term([sys.executable, '-m', 'jev.wsbridge'], idle=0.3, floor=REMOTE_GAP)
        wait_for(t, r'l\) Login')
        t.send('l')
        wait_for(t, r'enter your username')
        t.send(username + '\r')
        wait_for(t, r'(?i)password')
        t.send(password + '\r')
        m = wait_for(t, r'Logged in as|incorrect|Login failed')
        if 'Logged in' not in m[0]:
            raise RuntimeError('hardfought: login failed')
        key = game_key('\n'.join(t.lines()))
        if not key:  # the 5.0 entry may sit on a sub-menu of variants
            raise RuntimeError('hardfought: no NetHack 5.0 entry on the menu:\n' + '\n'.join(t.lines()))
        t.send(key)
        t.idle = 0.08  # in game: the bot's own pumping takes over
        t.pump(5)
        return t

    return launch


if __name__ == '__main__':
    assert game_key('  p) Play NetHack 3.6.7\n  x) Play NetHack 5.0.0\n  o) Edit NetHack 5.0 options') == 'x'
    assert game_key('  a) NetHack 3.7') is None
    assert 1 / 3 <= REMOTE_GAP <= 1 / 2  # 2-3 actions/sec at most
    print('ok')
