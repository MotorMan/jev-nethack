"""The play loop. Code reads the screen, lists legal concrete options and executes them;
Jev chooses every option. No LLM anywhere."""
import heapq, json, os, re, threading, time
from datetime import datetime, timezone

from .nh import (DIRS, DIR_OF, DIR_NAME, MAP_TOP, MAP_BOT, OBJECT_CHARS, Snapshot, top_prompt, messages_from)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEVER_EAT = ('cockatrice', 'chickatrice', 'Medusa', 'green slime', 'Rider', 'Death', 'Pestilence', 'Famine')
LOW_HP = lambda s: s.get('hp', 1) < 6 or s.get('hp', 1) * 7 < s.get('hpmax', 1)
STRATEGY = ("You are a dwarven Valkyrie: strong melee, cold resistant, stealthy, infravision. Survive first. "
            "Fight weak monsters in melee; do not melee floating eyes (blue 'e') or cockatrices ('c' yellow) bare-handed. "
            "Prayer fixes low HP (below 1/7 max or below 6) and weakness from hunger, but only about once per 1000 turns; "
            "the first prayer is safe after roughly turn 300. Elbereth engraved in the dust scares most melee monsters "
            "(not @ humans or minotaurs) until you attack from it. Eat when Hungry. Explore each level for useful items, "
            "then take the downstairs. A good pace is dungeon level no deeper than experience level + 2 early on. "
            "Wear armor you find if it covers an empty slot. The ultimate goal is to retrieve the Amulet and ascend.")


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def compass(frm, to):
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    ns = 'north' if dy < 0 else 'south' if dy > 0 else ''
    ew = 'west' if dx < 0 else 'east' if dx > 0 else ''
    if ns and ew and min(abs(dx), abs(dy)) * 3 < max(abs(dx), abs(dy)):
        return ns if abs(dy) > abs(dx) else ew
    return '-'.join(x for x in (ns, ew) if x) or 'here'


class Level:
    def __init__(self):
        self.near = set()      # squares we have stood on or next to
        self.searched = {}     # square -> turns searched there
        self.blocked = set()   # squares that turned out impassable (locked doors, boulders we could not push)
        self.locked = set()
        self.dead = set()      # exploration targets we gave up on
        self.corpses = {}      # square -> turn the corpse was first seen


class Bot:
    def __init__(self, launcher, jev, mode='local'):
        self.avoid = set()  # squares never to step into (floating eyes, molds)
        self.launcher, self.jev, self.mode = launcher, jev, mode
        self.lock = threading.Lock()
        self.paused, self.step_once, self.delay_ms, self.stop = False, False, 250, False
        self.order = 'Play carefully to stay alive while making steady progress downward.'
        self.phase = 'starting'
        self.messages, self.logs, self.history = [], [], []
        self.decision = None
        self.runs = self._load_runs()
        self.run = None
        self.t = None
        self.snap = None
        self.inventory = []
        self.version = 0

    # ---------- bookkeeping ----------
    def log(self, text, level='info'):
        with self.lock:
            self.logs.append(dict(at=now(), level=level, text=text))
            del self.logs[:-300]
            self.version += 1
        print(f'[{level}] {text}', flush=True)

    quiet = False

    def add_msg(self, text):
        text = text.strip()
        if not text or self.quiet:
            return
        turn = (self.snap.status.get('turn') if self.snap else None) or 0
        with self.lock:
            if not (self.messages and self.messages[-1]['text'] == text):
                self.messages.append(dict(turn=turn, text=text))
                del self.messages[:-300]
            self.version += 1
        if self.run is not None:
            self.run['recent'].append(text)
            del self.run['recent'][:-12]

    def _load_runs(self):
        try:
            return json.load(open(os.path.join(ROOT, 'runs', 'runs.json')))
        except (OSError, ValueError):
            return []

    def _save_runs(self):
        os.makedirs(os.path.join(ROOT, 'runs'), exist_ok=True)
        json.dump(self.runs, open(os.path.join(ROOT, 'runs', 'runs.json'), 'w'), indent=1)

    def touch(self):
        with self.lock:
            self.version += 1

    # ---------- screen handling ----------
    def settle(self, limit=40):
        """Clear --More--, stray menus and prompts until the game waits for a command."""
        for _ in range(limit):
            if not self.t.alive:
                return
            lines = self.t.lines()
            kind, text = top_prompt(lines)
            if any('Hit return to continue' in l for l in lines):
                self.t.send('\r')
                continue
            if kind is None:
                if lines[0].strip():
                    self.add_msg(lines[0])
                return
            if kind == 'more':
                msg = messages_from(text)
                self.add_msg(msg)
                self.on_message(msg)
                self.t.send('\r')
            elif kind == 'menu':
                self.capture_endgame(text)
                self.t.send('\x1b')
            elif kind == 'yn':
                self.t.send(self.answer_yn(text))
            else:
                self.add_msg(text)
                self.t.send(self.answer_ask(text))
        self.log('settle: gave up after too many prompts', 'warn')

    def answer_yn(self, q):
        self.add_msg(q)
        rules = [('Really attack', 'n'), ('pray', 'y'), ('no return', 'n'), ('possessions identified', 'n'),
                 ('Stop eating', 'y'), ('Continue eating', 'n'), ('add to the current engraving', 'n'),
                 ('Do you want to keep the save file', 'n'), ('Dump core', 'n'), ('eat it', 'n')]
        for pat, ans in rules:
            if pat.lower() in q.lower():
                if pat == 'Really attack' and self.snap:
                    self.peaceful_hint = True
                return ans
        return '\x1b'

    def answer_ask(self, q):
        if 'who are you' in q.lower():
            return 'Jev\r'
        return '\x1b'

    def on_message(self, msg):
        if self.run is not None and re.search(r'You die|killed by|You starve|You drown', msg):
            self.run['death_msgs'].append(msg)

    def capture_endgame(self, text):
        if self.run is not None and ('Vanquished' in text or 'Goodbye' in text or 'killed by' in text):
            self.run['death_msgs'].append(text[:2000])

    def observe(self):
        self.settle()
        self.snap = Snapshot(self.t)
        s = self.snap.status
        if self.snap.me and s.get('dlvl'):
            lv = self.level()
            x, y = self.snap.me
            lv.near.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            for p in self.snap.find('%'):
                lv.corpses.setdefault(p, s.get('turn') or 0)
            if self.run is not None:
                self.run['max_dlvl'] = max(self.run['max_dlvl'], s['dlvl'])
                self.run['turns'] = s.get('turn') or self.run['turns']
        self.touch()
        return self.snap

    def level(self):
        return self.run['levels'].setdefault(self.snap.status.get('dlvl', 0), Level())

    # ---------- pathing ----------
    def dijkstra(self, snap=None):
        snap = snap or self.snap
        lv = self.level()
        start = snap.me
        dist, prev = {start: 0}, {}
        pq = [(0, start)]
        while pq:
            d, p = heapq.heappop(pq)
            if d > dist.get(p, 1e9):
                continue
            for (dx, dy) in DIRS.values():
                q = (p[0] + dx, p[1] + dy)
                if q in lv.blocked or q in self.avoid or not snap.walkable(*q):
                    continue
                if dx and dy and not snap.diag_ok(p, q):
                    continue
                nd = d + snap.cost(*q)
                if nd < dist.get(q, 1e9):
                    dist[q], prev[q] = nd, p
                    heapq.heappush(pq, (nd, q))
        return dist, prev

    @staticmethod
    def first_step(prev, start, goal):
        p = goal
        while prev.get(p) != start:
            if p not in prev:
                return None
            p = prev[p]
        return DIR_OF[(p[0] - start[0], p[1] - start[1])]

    def frontiers(self, dist):
        lv, snap = self.level(), self.snap
        out = []
        for p, d in dist.items():
            if p in lv.dead or p == snap.me:
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (p[0] + dx, p[1] + dy)
                    g = snap.at(*q)
                    if g is not None and g.ch == ' ' and q not in lv.near:
                        out.append((d, p))
                        break
                else:
                    continue
                break
        return sorted(out)

    # ---------- monsters ----------
    def farlook(self, pos):
        me = self.snap.me
        keys = ';'
        dx, dy = pos[0] - me[0], pos[1] - me[1]
        while dx or dy:
            sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
            k = DIR_OF[(sx, sy)]
            if abs(dx) >= 8 and (abs(dy) >= 8 or not sy) and (sy == 0 or abs(dy) >= 8):
                keys += k.upper(); dx -= 8 * sx; dy -= 8 * sy
            else:
                keys += k; dx -= sx; dy -= sy
        self.t.send(keys + '.')
        for _ in range(20):
            if not self.t.lines()[0].startswith('Pick a'):
                break
            self.t.pump(0.2)
        lines = self.t.lines()
        kind, text = top_prompt(lines)
        desc = messages_from(text) if kind == 'more' else lines[0].strip()
        self.quiet = True
        self.settle()
        self.quiet = False
        desc = re.sub(r'^\S\s+', '', desc)
        desc = re.sub(r'\s*\[seen:.*$', '', desc)
        # "tame a dog or other canine (little dog called Kiki)" -> "tame little dog called Kiki"
        m = re.match(r'^((?:tame|peaceful)\s+)?.*\((.+)\)$', desc)
        return (m[1] or '') + m[2] if m else desc

    def monsters(self):
        snap, me = self.snap, self.snap.me
        out = []
        for y in range(MAP_TOP, MAP_BOT + 1):
            for x in range(80):
                if snap.is_monster(x, y):
                    g = snap.at(x, y)
                    d = cheb(me, (x, y))
                    out.append(dict(pos=(x, y), ch=g.ch, fg=g.fg, dist=d, pet=g.reverse, name=None, peaceful=False))
        out.sort(key=lambda m: m['dist'])
        for m in out[:6]:
            if m['pet'] and m['dist'] > 1:
                m['name'] = 'your pet'
                continue
            if m['dist'] <= 9:
                desc = self.farlook(m['pos'])
                m['name'] = desc or f"unknown '{m['ch']}'"
                m['pet'] = m['pet'] or 'tame' in desc
                m['peaceful'] = 'peaceful' in desc
        for m in out:
            m['name'] = m['name'] or f"unidentified '{m['ch']}' ({m['fg']})"
            m['hostile'] = not m['pet'] and not m['peaceful'] and m['ch'] not in ('I',)
            # sessile, only hurt you if you hit them: never a reason to hold still, and never walk into them
            m['passive'] = bool(re.search(r'floating eye|mold|shrieker', m['name'])) or (m['ch'] == 'e' and m['fg'] == 'blue')
            m['where'] = f"{m['dist']} step{'s' if m['dist'] != 1 else ''} {compass(me, m['pos'])}"
        return out

    # ---------- inventory ----------
    def read_inventory(self):
        items = []
        self.t.send('i')
        for _ in range(6):
            lines = self.t.lines()
            kind, _ = top_prompt(lines)
            for l in lines:
                for m in re.finditer(r'(?:^|\s)([a-zA-Z$#]) - (.+?)\s*$', l):
                    items.append(dict(letter=m[1], text=m[2]))
            if kind == 'menu' and any(re.search(r'\((\d+) of (\d+)\)', l) and not re.search(r'\((\d+) of \1\)', l) for l in lines):
                self.t.send('>')
            else:
                break
        self.t.send('\x1b')
        self.settle()
        seen, uniq = set(), []
        for it in items:
            if it['letter'] not in seen:
                seen.add(it['letter']); uniq.append(it)
        self.inventory = uniq
        return uniq

    def look_here(self):
        """':' look, free action. Returns item descriptions on this square."""
        self.t.send(':')
        texts = []
        for _ in range(8):
            lines = self.t.lines()
            kind, text = top_prompt(lines)
            if kind in ('more', 'menu'):
                texts.append(text)
                self.t.send('\r')
            else:
                texts.append('\n'.join(lines[:1]))
                break
        self.settle()
        blob = '\n'.join(texts)
        items = []
        m = re.search(r'You (?:see|feel) here (.+?)\.', blob.replace('\n', ' '))
        if m:
            items.append(m[1])
        if 'Things that are here' in blob or 'Things that you feel here' in blob:
            block = blob.split('here:', 1)[1]
            for l in block.split('\n'):
                l = l.replace('--More--', '').strip()
                if l and not l.startswith('Things') and len(l) > 2:
                    items.append(l)
        return [i for i in items if not re.search(r'engraving|written|There is|Dlvl|St:', i)]

    # ---------- options ----------
    def build_options(self):
        """Every legal, concrete thing worth doing now: id -> (label, detail, run())."""
        snap, s, lv = self.snap, self.snap.status, self.level()
        me = snap.me
        mons = self.monsters()
        self.visible = mons
        hostiles = [m for m in mons if m['hostile']]
        self.avoid = {m['pos'] for m in hostiles if m['passive'] and 'shrieker' not in m['name']}
        near = [m for m in hostiles if m['dist'] <= 6 and not m['passive']]
        dist, prev = self.dijkstra()
        opts = {}

        for m in hostiles:
            if m['dist'] == 1 and m['pos'] not in self.avoid:
                d = DIR_OF[(m['pos'][0] - me[0], m['pos'][1] - me[1])]
                opts[f'attack_{d}'] = (f"Attack {m['name']} ({DIR_NAME[d]})", f"Melee the adjacent {m['name']} to the {DIR_NAME[d]}.", lambda d=d: self.act_fight(d))
        for m in near[:2]:
            if m['dist'] > 1 and m['pos'] in dist:
                opts[f"approach_{m['pos'][0]}_{m['pos'][1]}"] = (f"Close in on {m['name']}", f"Step toward {m['name']} {m['where']}.", lambda m=m: self.act_go(m['pos'], dist_prev=None, steps=1, adjacent_ok=True))
        if near:
            opts['wait'] = ('Hold position one turn', 'Search in place for one turn and let monsters come to you (you get the first hit when they step adjacent).', lambda: self.act_keys('s', 'waited'))
            opts['retreat'] = ('Retreat one step', 'Step to the adjacent square farthest from visible hostiles.', lambda: self.act_retreat(hostiles))
            if not self.engraved_here():
                opts['elbereth'] = ('Engrave Elbereth', 'Write Elbereth in the dust here with a finger (1 turn). Most monsters will not melee you while you stand on it; attacking from it erases it.', self.act_elbereth)
            if snap.lines[me[1]] and self.standing_on() == '<' and s.get('dlvl', 1) > 1:
                opts['upstairs'] = ('Flee up the stairs', 'Climb the up staircase you are standing on; adjacent monsters may follow.', lambda: self.act_keys('<', 'went up'))

        trouble = LOW_HP(s) or s.get('hunger') in ('Weak', 'Fainting')
        if trouble:
            last = self.run.get('prayed_turn')
            opts['pray'] = ('Pray to Tyr', f"You are in trouble ({'low HP' if LOW_HP(s) else s.get('hunger')}). Last prayer: {'never' if last is None else 'turn ' + str(last)}. Current turn {s.get('turn')}. A successful prayer fully heals.", self.act_pray)

        if s.get('hunger') in ('Hungry', 'Weak', 'Fainting'):
            for it in self.inventory:
                if re.search(r'food ration|cram|lembas|biscuit|pancake|apple|orange|banana|melon|carrot|egg|tin |fortune|candy|K-ration|C-ration|kelp|slime mold|tripe|meatball|corpse', it['text']) and not any(n in it['text'] for n in NEVER_EAT):
                    opts[f"eat_{it['letter']}"] = (f"Eat {it['text']}", f"Eat item {it['letter']} from your pack.", lambda l=it['letter']: self.act_eat(l))
            here = [i for i in self.here_items() if 'corpse' in i and not any(n in i for n in NEVER_EAT)]
            age = s.get('turn', 0) - lv.corpses.get(me, s.get('turn', 0))
            if here and age < 40:
                opts['eat_corpse'] = (f"Eat the {here[0]} here", f"Eat {here[0]} on this square. It appeared about {age} turns ago (old corpses can be rotten or poisonous).", self.act_eat_corpse)

        for i, item in enumerate(self.here_items()[:4]):
            if 'for sale' in item or 'corpse' in item or 'boulder' in item:
                continue
            opts[f'pickup_{i}'] = (f"Pick up {item}", f"Pick up {item} from this square.", lambda item=item: self.act_pickup(item))
        if not near:
            for it in self.inventory:
                t = it['text']
                if re.search(r'\b(armor|mail|helmet|helm|cap|hat|cloak|boots|shoes|gloves|gauntlets|shield|robe|apron|shirt|coat|jacket|tunic)\b', t) and 'being worn' not in t:
                    opts[f"wear_{it['letter']}"] = (f"Wear {t}", "Put on this armor (takes a few turns; may be cursed if unidentified).", lambda l=it['letter']: self.act_keys('W' + l, 'wore armor'))

        for d, p in [(k, (me[0] + v[0], me[1] + v[1])) for k, v in DIRS.items() if not (v[0] and v[1])]:
            if p in lv.locked:
                opts[f'kick_{d}'] = (f"Kick the locked door {DIR_NAME[d]}", 'Kick the locked door to break it open (may take several tries).', lambda d=d: self.act_kick(d))

        for door in list(lv.locked)[:2]:
            if cheb(door, me) <= 1:
                continue
            spots = [q for q in ((door[0] + dx, door[1] + dy) for dx, dy in DIRS.values() if not (dx and dy)) if q in dist]
            if spots:
                q = min(spots, key=dist.get)
                opts[f'kickdoor_{door[0]}_{door[1]}'] = (f"Go kick open the locked door {compass(me, door)}", f"Walk {dist[q]} steps to the locked door {compass(me, door)} and kick it until it breaks (what lies behind is unexplored).", lambda q=q, door=door: self.act_kick_door(q, door))
        fr = self.frontiers(dist)
        picked = []
        for d, p in fr:
            if all(cheb(p, q) >= 8 for q in picked):
                picked.append(p)
                k = len(picked)
                opts[f'explore_{k}'] = (f"Explore {compass(me, p)} ({d} steps)", f"Walk to the unexplored edge {d} steps away to the {compass(me, p)} and see what is there.", lambda p=p: self.act_explore(p))
            if len(picked) == 3:
                break
        downs = [p for p in snap.find('>') if p in dist or p == me]
        if self.standing_on() == '>':
            opts['descend'] = ('Go down the stairs', f"You are on the down staircase to Dlvl {s.get('dlvl', 0) + 1}.", lambda: self.act_keys('>', 'descended'))
        elif downs:
            opts['descend'] = ('Head for the downstairs', f"Walk to the known down staircase ({dist[downs[0]]} steps {compass(me, downs[0])}) and descend to Dlvl {s.get('dlvl', 0) + 1}.", lambda p=downs[0]: self.act_descend(p))
        pick = next((it for it in self.inventory if re.search(r'pick-axe|dwarvish mattock', it['text'])), None)
        if pick and not near and self.standing_on() not in ('<', '>', '_', '{'):
            opts['dig_down'] = ('Dig down with the pick-axe', f"Apply {pick['text']} downward to dig a hole to Dlvl {s.get('dlvl', 0) + 1} (takes several turns; skips the rest of this level).", lambda l=pick['letter']: self.act_dig(l))
        if not near:
            hurt = s.get('hp', 1) < s.get('hpmax', 1)
            opts['rest'] = ('Rest and search 15 turns' if hurt else 'Search here 15 turns', 'Stay put for up to 15 turns: regain HP and find hidden doors next to you. Interrupted if a monster appears.', lambda: self.act_search(15))
        if not fr and not downs and not near:
            spot = self.search_spot(dist)
            if spot:
                opts['search_hidden'] = ('Search for hidden passages', f"No unexplored edges or downstairs are known. Walk {dist[spot]} steps {compass(me, spot)} to a likely spot (dead end or wall) and search there.", lambda: self.act_search_at(spot))
        # stall guard: an option picked 3 times in a row without the game clock moving is not working
        last = self.history[-3:]
        if len(last) == 3 and len({h['choice'] for h in last}) == 1 and all(h['turn'] == s.get('turn') for h in last) and len(opts) > 1:
            opts.pop(last[0]['choice'], None)
        if not opts:
            opts['wait'] = ('Wait one turn', 'Nothing else is possible right now; search in place for one turn.', lambda: self.act_keys('s', 'waited'))
        return opts, mons

    def search_spot(self, dist):
        snap, lv = self.snap, self.level()
        best = None
        for p, d in dist.items():
            walls = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and (g := snap.at(p[0] + dx, p[1] + dy)) is not None and g.ch in ' |-')
            exits = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and snap.walkable(p[0] + dx, p[1] + dy))
            if walls < 3:
                continue
            score = lv.searched.get(p, 0) * 2 + d / 4 - (8 if snap.at(*p).ch == '#' and exits <= 1 else 0) - walls
            if best is None or score < best[0]:
                best = (score, p)
        return best and best[1]

    def standing_on(self):
        """What is under us, from level memory of the map (the @ hides it)."""
        return self.run.get('under', {}).get((self.snap.status.get('dlvl'), self.snap.me))

    def here_items(self):
        return self.run.get('here', {}).get((self.snap.status.get('dlvl'), self.snap.me), [])

    def engraved_here(self):
        return (self.snap.status.get('dlvl'), self.snap.me) in self.run.setdefault('elbereth', set())

    # ---------- motors ----------
    def after_move(self, before):
        """Remember the glyph we stepped onto and what lies here."""
        snap = self.observe()
        key = (snap.status.get('dlvl'), snap.me)
        if snap.me != before.me and before.at(*snap.me):
            g = before.at(*snap.me).ch
            if g in '<>_{':
                self.run['under'][key] = g
            if g in OBJECT_CHARS or g == '0':
                self.run['here'][key] = self.look_here()
            else:
                self.run['here'].pop(key, None)
        return snap

    def act_keys(self, keys, what):
        before = self.snap
        self.t.send(keys)
        self.after_move(before)
        return what

    def act_fight(self, d):
        before = self.snap
        self.t.send('F' + d)
        self.after_move(before)
        self.run['elbereth'].discard((before.status.get('dlvl'), before.me))
        return f'attacked {DIR_NAME[d]}'

    def act_go(self, target, dist_prev=None, steps=40, adjacent_ok=False):
        """Walk toward target one step at a time; stop on new threats, damage or arrival."""
        taken = 0
        seen = {m['pos'] for m in getattr(self, 'visible', []) if m['hostile']}
        hp0 = self.snap.status.get('hp', 0)
        for _ in range(steps):
            me = self.snap.me
            if me is None or me == target or (adjacent_ok and cheb(me, target) <= 1):
                return f'arrived after {taken} steps'
            _, prev = self.dijkstra()
            d = self.first_step(prev, me, target)
            if d is None:
                self.level().dead.add(target)
                return f'no path after {taken} steps'
            before = self.snap
            nmsg = len(self.messages)
            self.t.send(d)
            snap = self.after_move(before)
            taken += 1
            news = [m['text'] for m in self.messages[nmsg:]]
            if any('locked' in m for m in news):
                door = (me[0] + DIRS[d][0], me[1] + DIRS[d][1])
                self.level().locked.add(door)
                self.level().blocked.add(door)
                return 'found a locked door'
            if snap.me == me and not any('door opens' in m or 'open' in m for m in news):
                step = (me[0] + DIRS[d][0], me[1] + DIRS[d][1])
                if before.is_door(*step) and before.at(*step).ch == '+':
                    self.level().locked.add(step)  # locked, stuck or resisting: kicking is the way through
                if not snap.is_monster(*step):
                    self.level().blocked.add(step)
                return f'blocked after {taken} steps' + (f": {news[-1]}" if news else '')
            if snap.status.get('hp', 0) < hp0:
                return f'took damage after {taken} steps'
            new = [p for p in self.hostile_glyphs() if p not in seen and cheb(p, snap.me) <= 7]
            if new:
                return f'stopped after {taken} steps: a monster came into view'
            if any(re.search(r'You (see|feel) here|There are (several|many) objects|trap|You fall|stairs', m) for m in news):
                return f'stopped after {taken} steps: {news[-1]}'
        return f'walked {taken} steps'

    def hostile_glyphs(self):
        snap = self.snap
        return [(x, y) for y in range(MAP_TOP, MAP_BOT + 1) for x in range(80) if snap.is_monster(x, y) and not snap.at(x, y).reverse]

    def act_explore(self, p, budget=40):
        """Walk to the chosen edge, then keep taking the nearest new edge until something happens."""
        total, r = 0, ''
        while budget > 0:
            n0 = self.snap.status.get('turn') or 0
            r = self.act_go(p, steps=budget)
            if self.snap.me == p or r.startswith('no path'):
                self.level().dead.add(p)
            m = re.search(r'(\d+) steps', r)
            total += int(m[1]) if m else 0
            budget -= max(1, int(m[1]) if m else 1)
            if not r.startswith('arrived'):
                break
            dist, _ = self.dijkstra()
            fr = self.frontiers(dist)
            if not fr:
                r = 'no unexplored edges left'
                break
            p = fr[0][1]
        return f'explore ({total} steps): {r}'

    def act_descend(self, p):
        r = self.act_go(p)
        if self.snap.me == p:
            dl = self.snap.status.get('dlvl')
            self.act_keys('>', '')
            return f'walked to the stairs and descended (Dlvl {dl} -> {self.snap.status.get("dlvl")})'
        return 'heading downstairs: ' + r

    def act_retreat(self, hostiles):
        me, snap = self.snap.me, self.snap
        best = None
        for d, (dx, dy) in DIRS.items():
            q = (me[0] + dx, me[1] + dy)
            if not snap.walkable(*q) or snap.is_monster(*q) or snap.at(*q).ch in '^0' or (dx and dy and not snap.diag_ok(me, q)):
                continue
            score = min(cheb(q, m['pos']) for m in hostiles)
            if best is None or score > best[0]:
                best = (score, d)
        if not best:
            return 'nowhere to retreat'
        self.act_keys(best[1], '')
        return f'retreated {DIR_NAME[best[1]]}' if self.snap.me != me else 'tried to retreat but did not move'

    def act_elbereth(self):
        self.t.send('E')
        if 'write with' in self.t.lines()[0]:
            self.t.send('-')
        for _ in range(4):
            top = self.t.lines()[0]
            if 'add to the current engraving' in top:
                self.t.send('n')
            elif 'What do you want to write' in top:
                self.t.send('Elbereth\r')
                break
            elif '--More--' in '\n'.join(self.t.lines()):
                self.add_msg(messages_from('\n'.join(self.t.lines())))
                self.t.send('\r')
            else:
                break
        self.observe()
        self.run['elbereth'].add((self.snap.status.get('dlvl'), self.snap.me))
        return 'engraved Elbereth'

    def act_pray(self):
        self.t.send('#pray\r')
        self.observe()
        self.run['prayed_turn'] = self.snap.status.get('turn')
        return 'prayed'

    def act_eat(self, letter):
        self.t.send('e')
        if 'eat it?' in self.t.lines()[0] or 'eat one?' in self.t.lines()[0]:
            self.t.send('n')
        if 'What do you want to eat' in self.t.lines()[0]:
            self.t.send(letter)
        self.observe()
        self.read_inventory()
        return 'ate'

    def act_eat_corpse(self):
        self.t.send('e')
        top = self.t.lines()[0]
        if ('eat it?' in top or 'eat one?' in top) and not any(n in top for n in NEVER_EAT):
            self.t.send('y')
        else:
            self.t.send('\x1b')
        self.observe()
        key = (self.snap.status.get('dlvl'), self.snap.me)
        self.run['here'][key] = self.look_here()
        return 'ate corpse'

    def act_pickup(self, item):
        self.t.send(',')
        lines = self.t.lines()
        if top_prompt(lines)[0] == 'menu':
            want = item.split(' (')[0][-25:]
            for l in lines:
                m = re.search(r'([a-zA-Z]) - (.+)$', l)
                if m and want in m[2]:
                    self.t.send(m[1])
                    break
            self.t.send('\r')
        self.observe()
        key = (self.snap.status.get('dlvl'), self.snap.me)
        self.run['here'][key] = self.look_here()
        self.read_inventory()
        return f'picked up {item}'

    def act_dig(self, letter):
        weapon = next((it['letter'] for it in self.inventory if 'weapon in' in it['text'] and it['letter'] != letter), None)
        dl = self.snap.status.get('dlvl')
        self.t.send('a' + letter)
        for _ in range(4):
            top = self.t.lines()[0]
            if 'direction' in top:
                self.t.send('>', timeout=10)
                break
            if 'You are now wielding' in top or '--More--' in '\n'.join(self.t.lines()):
                self.t.send('\r')
            else:
                break
        self.t.pump(3)
        self.observe()
        new = self.snap.status.get('dlvl')
        if weapon:
            self.t.send('w' + weapon)
            self.observe()
        self.read_inventory()
        return f'dug through to Dlvl {new}' if new != dl else 'dug but did not fall through (interrupted?)'

    def act_kick_door(self, spot, door):
        r = self.act_go(spot)
        if self.snap.me != spot:
            return 'going to the locked door: ' + r
        d = DIR_OF[(door[0] - spot[0], door[1] - spot[1])]
        for i in range(6):
            self.act_kick(d)
            if door not in self.level().locked or self.hostile_glyphs():
                break
        return 'kicked the door open' if door not in self.level().locked else 'kicked the door; still shut'

    def act_kick(self, d):
        self.t.send('\x04' + d)
        self.observe()
        door = (self.snap.me[0] + DIRS[d][0], self.snap.me[1] + DIRS[d][1])
        g = self.snap.at(*door)
        if g and not (g.ch == '+' and g.fg in ('brown', 'yellow')):
            self.level().locked.discard(door)
            self.level().blocked.discard(door)
        return 'kicked the door'

    def act_search(self, n):
        self.t.send(f'{n}s')
        self.observe()
        lv = self.level()
        lv.searched[self.snap.me] = lv.searched.get(self.snap.me, 0) + n
        return f'searched {n} turns'

    def act_search_at(self, spot):
        r = self.act_go(spot)
        if self.snap.me == spot:
            return self.act_search(15)
        return 'going to search: ' + r

    # ---------- Jev ----------
    def state_text(self, mons):
        s, snap = self.snap.status, self.snap
        lv = self.level()
        inv = '; '.join(f"{i['letter']} - {i['text']}" for i in self.inventory) or 'unknown'
        seen = '; '.join(f"{m['name']} {m['where']}" + (' (pet)' if m['pet'] else ' (peaceful)' if m['peaceful'] else '') for m in mons[:8]) or 'none'
        hist = '\n'.join(f"- T{h['turn']} {h['label']} -> {h['outcome']}" for h in self.history[-8:]) or '- (start of game)'
        recent = ' | '.join(self.run['recent'][-6:]) or 'none'
        return (
            f"NetHack 5.0.0. You decide for {s.get('name', 'the hero')}, a {s.get('align', 'lawful').lower()} dwarven Valkyrie.\n"
            f"Standing order from the operator: {self.order}\n"
            f"Strategy notes: {STRATEGY}\n\n"
            f"Status: Dlvl {s.get('dlvl')}, HP {s.get('hp')}/{s.get('hpmax')}, Pw {s.get('pw')}/{s.get('pwmax')}, AC {s.get('ac')}, "
            f"XL {s.get('xl')} ({s.get('exp')} exp), turn {s.get('turn')}, gold {s.get('gold')}, hunger: {s.get('hunger')}, "
            f"conditions: {', '.join(s.get('conditions') or []) or 'none'}. Str {s.get('st')} Dex {s.get('dx')} Con {s.get('co')}.\n"
            f"Last prayer: {'never' if self.run.get('prayed_turn') is None else 'turn ' + str(self.run['prayed_turn'])}.\n"
            f"Monsters in view: {seen}.\n"
            f"Items on this square: {', '.join(self.here_items()) or 'none'}. Standing on: {self.standing_on() or 'floor'}.\n"
            f"Inventory: {inv}\n"
            f"Level: downstairs {'known' if snap.find('>') or self.standing_on() == '>' else 'not found yet'}; "
            f"deepest level reached this game {self.run['max_dlvl']}.\n"
            f"Recent game messages: {recent}\n"
            f"Recent decisions:\n{hist}\n\n"
            f"Map around you (@ is you; # corridor, + or orange | - doors, < > stairs, letters are monsters):\n{snap.crop()}\n"
        )

    def decide(self):
        opts, mons = self.build_options()
        state = self.state_text(mons)
        question = ('Choose the single best action for the Valkyrie right now. Staying alive comes first; after that, '
                    'make steady progress (explore, gear up, descend). Use the status, monsters, recent outcomes and the standing order.')
        criteria = {k: f"{v[0]}. {v[1]}" for k, v in opts.items()}
        s = self.snap.status
        self.decision = dict(id=self.run['decisions'] + 1, at=now(), turn=s.get('turn') or 0, pending=True, question=question,
                             options=[dict(id=k, label=v[0], detail=v[1], p=None) for k, v in opts.items()],
                             choice=None, confidence=None, latency_ms=None, state_text=state)
        self.phase = 'thinking'
        self.touch()
        if len(opts) == 1:
            key, answers, meta = next(iter(opts)), {}, dict(latency_ms=0, model=None)
            probs, conf = {key: 1.0}, 1.0
        else:
            qs = {'action': dict(type='choice', instructions=question, criteria=criteria),
                  'danger': dict(type='noul', instructions='Is the Valkyrie in serious danger of dying within the next few turns?')}
            answers, meta = self.jev.ask(state, qs)
            key = answers['action']['choice']
            probs, conf = answers['action'].get('probabilities', {}), answers['action'].get('confidence')
        for o in self.decision['options']:
            o['p'] = probs.get(o['id'])
        self.decision.update(pending=False, choice=key, confidence=conf, latency_ms=meta['latency_ms'],
                             danger=(answers.get('danger') or {}).get('noul'))
        self.run['decisions'] += 1
        self.phase = 'acting'
        self.touch()
        label = opts[key][0]
        try:
            outcome = opts[key][2]() or ''
        except Exception as e:  # a motor tripping over an unexpected screen should not kill the run
            self.log(f'motor {key} failed: {e!r}', 'error')
            self.t.send('\x1b')
            outcome = f'error: {e}'
        h = dict(id=self.decision['id'], at=now(), turn=s.get('turn') or 0, dlvl=s.get('dlvl') or 0, choice=key, label=label,
                 p=probs.get(key, 1.0), confidence=conf, n_options=len(opts), latency_ms=meta['latency_ms'], outcome=outcome)
        with self.lock:
            self.history.append(h)
            del self.history[:-200]
        with open(os.path.join(self.run_dir, 'decisions.jsonl'), 'a') as f:
            f.write(json.dumps(dict(h, state=state, criteria=criteria, answers=answers, model=meta.get('model'))) + '\n')
        self.log(f"T{h['turn']} {key} p={h['p']:.2f} -> {outcome}")

    # ---------- lifecycle ----------
    def new_run(self):
        rid = datetime.now().strftime('%Y%m%d-%H%M%S')
        self.run_dir = os.path.join(ROOT, 'runs', rid)
        os.makedirs(self.run_dir, exist_ok=True)
        self.run = dict(id=rid, started=now(), ended=None, character='dwarven Valkyrie', turns=0, max_dlvl=1, death=None, score=None,
                        decisions=0, levels={}, under={}, here={}, elbereth=set(), prayed_turn=None, recent=[], death_msgs=[])
        self.history.clear()
        self.runs.append({k: self.run[k] for k in ('id', 'started', 'ended', 'character', 'turns', 'max_dlvl', 'death', 'score')})
        self._save_runs()
        self.log(f'new run {rid} ({self.mode})')

    def end_run(self):
        blob = ' '.join(self.run['death_msgs'])
        m = re.search(r'(killed by [^.\n]+?|died of [^.\n]+|starved to death|drowned [^.\n]+|choked [^.\n]+|quit|escaped)\s*(?:$|\s{2}|\n|\.)', blob)
        self.run['death'] = m[1].strip() if m else ('died' if 'You die' in blob else 'game ended')
        self.run['ended'] = now()
        self.runs[-1] = {k: self.run[k] for k in ('id', 'started', 'ended', 'character', 'turns', 'max_dlvl', 'death', 'score')}
        self._save_runs()
        self.log(f"run {self.run['id']} over: {self.run['death']} on T{self.run['turns']}, max Dlvl {self.run['max_dlvl']}", 'warn')

    def play(self):
        """Run games forever: start, decide until death, record, repeat."""
        while not self.stop:
            self.new_run()
            self.phase = 'starting'
            self.t = self.launcher()
            self.t.pump(3)
            self.observe()
            self.read_inventory()
            while self.t.alive and not self.stop:
                if self.paused and not self.step_once:
                    self.phase = 'paused'
                    self.touch()
                    time.sleep(0.1)
                    continue
                self.step_once = False
                self.observe()
                if not self.t.alive:
                    break
                if self.snap.me is None and any('Logged in as' in l for l in self.snap.lines):
                    break  # hardfought: game over, back at the dgamelaunch menu
                if self.snap.me is None:
                    self.log('cannot find the hero on screen; Esc + redraw', 'warn')
                    self.t.send('\x1b')
                    self.t.send('\x12')  # ^R: repaints if our emulated screen drifted (e.g. scrolled)
                    time.sleep(0.2)
                    continue
                try:
                    self.decide()
                except RuntimeError as e:
                    self.log(str(e), 'error')
                    self.paused = True
                if self.run['decisions'] % 25 == 0:
                    self.read_inventory()
                time.sleep(self.delay_ms / 1000)
            self.phase = 'dead'
            self.t.close()
            self.end_run()
            self.touch()
            time.sleep(3)

    def state(self):
        t, snap = self.t, self.snap
        with self.lock:
            return dict(
                mode=self.mode, paused=self.paused, phase=self.phase, delay_ms=self.delay_ms, order=self.order,
                screen=dict(rows=t.runs() if t else [], cursor=list(t.cursor()) if t else [0, 0], cols=80, lines=24),
                status=snap.status if snap else {'conditions': []},
                decision=self.decision, history=list(self.history), messages=list(self.messages), log=list(self.logs),
                jev=self.jev.summary(),
                run=dict(id=self.run['id'], started=self.run['started'], character=self.run['character'],
                         max_dlvl=self.run['max_dlvl'], decisions=self.run['decisions']) if self.run else None,
                runs=list(self.runs), inventory=list(self.inventory),
                level=dict(dlvl=snap.status.get('dlvl', 0), explored=min(1.0, sum(1 for l in snap.lines[MAP_TOP:MAP_BOT + 1] for c in l if c != ' ') / 700),  # ponytail: ~700 drawn cells is a typical fully seen level
                           downstairs=bool(snap.find('>')), upstairs=bool(snap.find('<'))) if snap and self.run else None,
            )
