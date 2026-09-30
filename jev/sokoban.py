"""Sokoban solver for NetHack 5.0 levels.

Rules modelled: orthogonal pushes only, a boulder pushed into a pit/hole fills it (both vanish),
a boulder pushed onto a rolling boulder trap keeps rolling that way until a wall or boulder stops it
or a pit swallows it (Sokoban traps have no launch spot, trap.c find_random_launch_coord).
The hero never steps into pits. Goal: every pit filled.
"""
import heapq, re

DIRS = {'h': (-1, 0), 'l': (1, 0), 'k': (0, -1), 'j': (0, 1)}


class Level:
    def __init__(self, floor, boulders, pits, rollers):
        self.floor, self.rollers = frozenset(floor), frozenset(rollers)  # floor includes pit/roller squares
        self.boulders, self.pits = frozenset(boulders), frozenset(pits)
        self.live = self._live()

    def _live(self):
        """Push distance from each square to a pit for a lone boulder; missing = dead square (deadlock pruning)."""
        live = dict.fromkeys(self.pits, 0)
        changed = True
        while changed:
            changed = False
            for c in self.floor:
                for dx, dy in DIRS.values():
                    if (c[0] - dx, c[1] - dy) not in self.floor:
                        continue
                    land = self._land(c, dx, dy, frozenset(), self.pits)
                    d = 1 if land is None else live[land] + 1 if land in live else None
                    if d is not None and d < live.get(c, 1e9) and c not in self.pits:
                        live[c] = d; changed = True
        return live

    def h(self, boulders, pits):
        return len(pits) * 5 + sum(sorted(self.live[b] for b in boulders)[:len(pits)])

    def _land(self, b, dx, dy, boulders, pits):
        """Where a boulder at b pushed by (dx,dy) ends up: a square, None (fell in a pit), or False (can't move)."""
        t = (b[0] + dx, b[1] + dy)
        if t not in self.floor or t in boulders:
            return False
        if t in pits:
            return None
        if t in self.rollers:  # rolls on until something stops it
            while True:
                n = (t[0] + dx, t[1] + dy)
                if n not in self.floor or n in boulders:
                    return t
                if n in pits:
                    return None
                t = n
        return t

    def reach(self, me, boulders, pits):
        seen, todo = {me}, [me]
        for c in todo:
            for dx, dy in DIRS.values():
                n = (c[0] + dx, c[1] + dy)
                if n in self.floor and n not in boulders and n not in pits and n not in seen:
                    seen.add(n); todo.append(n)
        return seen

    def pushes(self, me, boulders, pits):
        """(push, player_after, boulders, pits) for every legal, non-deadlocking push."""
        area = self.reach(me, boulders, pits)
        for b in boulders:
            for k, (dx, dy) in DIRS.items():
                if (b[0] - dx, b[1] - dy) not in area:
                    continue
                land = self._land(b, dx, dy, boulders, pits)
                if land is False or (land is not None and land not in self.live):
                    continue
                nb = boulders - {b} | ({land} if land else set())
                np = pits if land else pits - {self._pit_hit(b, dx, dy, boulders, pits)}
                if len(nb) - (land is not None and self._frozen(land, nb, np) and sum(self._frozen(x, nb, np) for x in nb)) < len(np):  # spare boulders may freeze
                    continue
                yield (b, k), b, nb, np

    def _frozen(self, c, boulders, pits):
        """A 2x2 of boulders/walls around c (and no pit) never moves again."""
        for ox in (0, -1):
            for oy in (0, -1):
                sq = [(c[0] + ox + i, c[1] + oy + j) for i in (0, 1) for j in (0, 1)]
                if all(q in boulders or q not in self.floor for q in sq) and not any(q in pits for q in sq):
                    return True
        return False

    def fill_one(self, me, boulders, pits, limit, want=3):
        """Up to `want` distinct shortest-ish push sequences that fill one more pit."""
        todo = [(0, 0, me, boulders, [])]
        seen, found, n = set(), [], 0
        while todo and n < limit and len(found) < want:
            _, _, me, bs, path = heapq.heappop(todo)
            for push, me2, nb, np in self.pushes(me, bs, pits):
                if len(np) < len(pits):
                    found.append((path + [push], me2, nb, np))
                    continue
                key = (nb, min(self.reach(me2, nb, np)))
                if key in seen:
                    continue
                seen.add(key); n += 1
                heapq.heappush(todo, (len(path) + 1 + 2 * min(self.live[x] for x in nb), n, me2, nb, path + [push]))
        return found

    def solve(self, me, limit=20000):
        """List of pushes [(boulder_pos, dir_key)] that fills every pit, or None. Depth-first over pit fills."""
        dead = set()

        def go(me, bs, ps):
            if not ps:
                return []
            key = (bs, ps)
            if key in dead:
                return None
            for path, me2, nb, np in self.fill_one(me, bs, ps, limit):
                rest = go(me2, nb, np)
                if rest is not None:
                    return path + rest
            dead.add(key)
            return None
        return go(me, self.boulders, self.pits)

    def _pit_hit(self, b, dx, dy, boulders, pits):
        t = (b[0] + dx, b[1] + dy)
        while t not in pits:
            t = (t[0] + dx, t[1] + dy)
        return t


def from_lua(path):
    src = open(path).read()
    rows = re.search(r'des\.map\(\[\[\n(.*?)\]\]', src, re.S)[1].split('\n')
    floor = {(x, y) for y, r in enumerate(rows) for x, c in enumerate(r) if c == '.'}
    num = r'(\d+),\s*(\d+)'
    boulders = {(int(x), int(y)) for x, y in re.findall(r'des\.object\("boulder",\s*' + num, src)}
    traps = re.findall(r'des\.trap\("([a-z ]+)",\s*' + num, src)
    pits = {(int(x), int(y)) for t, x, y in traps if t in ('pit', 'hole')}
    rollers = {(int(x), int(y)) for t, x, y in traps if t == 'rolling boulder'}
    br = re.search(r'des\.levregion\(\{ region = \{' + num, src) or re.search(r'des\.stair\("down",\s*' + num, src)  # where you arrive
    return Level(floor, boulders, pits, rollers), (int(br[1]), int(br[2]))


WIKI_DIR = {'r': 'l', 'l': 'h', 'u': 'k', 'd': 'j'}


def wiki_solutions(xml_gz):
    """{title: (diagram_lines, [(letter, moves)])} from the 'Sokoban Level NX' wiki pages."""
    import gzip, html
    out, title, text = {}, None, None
    for line in gzip.open(xml_gz, 'rt'):
        if '<title>' in line:
            m = re.search(r'<title>(Sokoban Level \d[ab])</title>', line)
            title = m and m[1]
            text = [] if title else None
        elif text is not None:
            text.append(html.unescape(line.rstrip('\n')))
            if '</text>' in line:
                moves = [m for l in text for m in re.findall(r"\'\'\'([A-Z])\'\'\'\s+([udlr* ]+)", l)]
                out[title] = (text, moves)
                title = text = None
    return out


def first_lettered_map(text):
    """The first wiki diagram that names boulders with letters, as {(x, y): ch}."""
    block = []
    for l in text + ['']:
        if re.match(r' +[-|]', l):
            block.append(l[1:].split("\'\'\'")[0].rstrip())
        elif block:
            if any(re.search(r'[A-Z]', b) for b in block):
                return {(x, y): c for y, r in enumerate(block) for x, c in enumerate(r)}
            block = []


def flip(pos, f, w, h):
    x, y = pos
    return (w - 1 - x if f & 1 else x, h - 1 - y if f & 2 else y)


def build(xml_gz, lua_glob='build/NetHack50/dat/soko*.lua'):
    """Replay every wiki solution on the matching 5.0 level; {lua_name: {'me': start, 'pushes': [[x, y, dir]]}}."""
    import glob, os
    pages = wiki_solutions(xml_gz)
    result = {}
    for f in sorted(glob.glob(lua_glob)):
        lv, me = from_lua(f)
        src = open(f).read()
        rows = re.search(r'des\.map\(\[\[\n(.*?)\]\]', src, re.S)[1].split('\n')
        walls = {(x, y) for y, r in enumerate(rows) for x, c in enumerate(r) if c in '-|'}
        w, h = max(map(len, rows)), len([r for r in rows if r])
        for title, (text, moves) in pages.items():
            grid = first_lettered_map(text)
            if not grid:
                continue
            for fl in range(4):
                gw = {flip(p, fl, w, h) for p, c in grid.items() if c in '-|'}
                if len(gw ^ walls) <= 0.05 * len(walls):  # 5.0 retouched some maps; the replay below checks every push
                    break
            else:
                continue
            letters = {c: flip(p, fl, w, h) for p, c in grid.items() if c.isupper()}
            if set(letters.values()) != set(lv.boulders):
                print(os.path.basename(f), title, 'boulders differ', sorted(set(letters.values()) ^ set(lv.boulders))); continue
            fdir = {'l': 'h' if fl & 1 else 'l', 'h': 'l' if fl & 1 else 'h', 'k': 'j' if fl & 2 else 'k', 'j': 'k' if fl & 2 else 'j'}
            bs, ps, where, pushes, ok = lv.boulders, lv.pits, dict(letters), [], True
            cur = me
            for letter, mv in moves:
                for ch in mv.replace(' ', '').replace('*', ''):
                    b = where.get(letter)
                    if b is None or not ps:  # rolled into a pit already (5.0 rolling boulder traps), or all pits are full
                        break  # already rolled into a pit (5.0 rolling boulder traps)
                    k = fdir[WIKI_DIR[ch]]
                    legal = {p: (m2, nb, np) for p, m2, nb, np in lv.pushes(cur, bs, ps)}
                    if (b, k) not in legal:
                        dx, dy = DIRS[k]
                        if (b[0] - dx, b[1] - dy) in lv.reach(cur, bs, ps) and lv._land(b, dx, dy, bs, ps) is not False:
                            legal[(b, k)] = None  # deadlock pruning disagrees with the wiki: trust the wiki
                            land = lv._land(b, dx, dy, bs, ps)
                            nb = bs - {b} | ({land} if land else set())
                            np = ps if land else ps - {lv._pit_hit(b, dx, dy, bs, ps)}
                            legal[(b, k)] = (b, nb, np)
                        else:
                            print(os.path.basename(f), title, 'illegal', letter, mv, b, k); ok = False; break
                    cur, nb, np = legal[(b, k)]
                    dx, dy = DIRS[k]
                    where[letter] = next(iter(nb - bs), None) if len(nb) == len(bs) else None
                    bs, ps = nb, np
                    pushes.append([b[0], b[1], k])
                if not ok:
                    break
            print(os.path.basename(f), title, 'flip', fl, len(pushes), 'pushes', 'SOLVED' if ok and not ps else f'{len(ps)} pits left')
            if ok and not ps:
                result[os.path.basename(f)[:-4]] = {'me': me, 'pushes': pushes}
            break
    return result


if __name__ == '__main__':  # python -m jev.sokoban: rebuild jev/sokoban.json from the wiki dump + solver
    import glob, json, os
    sols = build('nethackwiki_current.xml.gz')
    out = {}
    for f in sorted(glob.glob('build/NetHack50/dat/soko*.lua')):
        name = os.path.basename(f)[:-4]
        lv, me = from_lua(f)
        if name not in sols:
            o = lv.fill_one
            lv.fill_one = lambda *a, **k: o(*a[:4], want=8)
            path = lv.solve(me, limit=30000)
            assert path, name
            sols[name] = {'me': me, 'pushes': [[b[0], b[1], k] for b, k in path]}
        src = open(f).read()
        rows = re.search(r'des\.map\(\[\[\n(.*?)\]\]', src, re.S)[1].rstrip('\n').split('\n')
        out[name] = dict(map=rows, **sols[name])
        print(name, len(out[name]['pushes']), 'pushes')
    json.dump(out, open('jev/sokoban.json', 'w'), indent=None, separators=(',', ':'))
