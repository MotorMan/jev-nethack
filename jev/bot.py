"""The play loop. Code reads the screen, lists legal concrete options and executes them;
Jev chooses every option. No LLM anywhere."""
import glob, heapq, json, os, random, re, threading, time, traceback
from datetime import datetime, timezone

from . import sokoban
from .nh import (DIRS, DIR_OF, DIR_NAME, MAP_TOP, MAP_BOT, OBJECT_CHARS, Snapshot, top_prompt, messages_from)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOOD = re.compile(r'\b(?:food ration|cram|lembas|biscuit|pancake|apple|orange(?! gem)|banana|melon|carrot|egg|tins?|fortune|candy|K-ration|C-ration|kelp|slime mold|tripe|meatball|corpse|wolfsbane|garlic|royal jelly|cookie|cream pie|pear|lichen)e?s?\b')  # word-bounded: 'dwarvish spear' is not a pear
MONSTERS = json.load(open(os.path.join(os.path.dirname(__file__), 'monsters.json')))  # name -> [difficulty, speed], from monsters.h
# objects.h ARMOR(... ac ...) is 10 - bonus; body armor only, best first matches first
SUIT = {'crystal plate mail': 7, 'bronze plate mail': 6, 'plate mail': 7, 'splint mail': 6, 'banded mail': 6, 'dwarvish mithril-coat': 6, 'elven mithril-coat': 5,
        'orcish chain mail': 4, 'crude chain mail': 4, 'chain mail': 5, 'scale mail': 4, 'studded leather armor': 3, 'orcish ring mail': 2, 'crude ring mail': 2, 'ring mail': 3,
        'leather armor': 2, 'leather jacket': 1}
suit_ac = lambda t: next((v for k, v in SUIT.items() if k in t), None)
HEAVY = re.compile(r'\b(chest|large box|ice box|boulder|statue|rocks?|iron ball|iron chain|lance|pole sickle|halberd|glaive|partisan|spetum|ranseur|bardiche|voulge|fauchard|guisarme|bill-guisarme|lucern hammer|bec de corbin|two-handed sword|dwarvish mattock)\b')  # carrying these left Jev Burdened
WEAPON_RANK = ['long sword', 'axe', 'broadsword', 'katana', 'scimitar', 'saber', 'short sword', 'spear', 'mace', 'morning star', 'war hammer', 'flail', 'trident', 'dagger', 'knife', 'club']
WEAPON = re.compile(r'\b(' + '|'.join(WEAPON_RANK) + r')s?\b(?! corpse)')
# pray.c: never offer own race (dwarf), a former pet, a co-aligned (white) unicorn; touching a cockatrice bare-handed stones you
NEVER_OFFER = ('cockatrice', 'chickatrice', 'dwarf', 'kitten', 'housecat', 'large cat', 'little dog', 'large dog', 'dog corpse', 'pony', 'horse', 'white unicorn', 'Medusa', 'Death', 'Pestilence', 'Famine', 'were')
UNKNOWN_BUC = lambda t: not re.search(r'\b(cursed|uncursed|blessed)\b|being worn|weapon in|gold piece|corpse', t)
NEVER_EAT = ('cockatrice', 'chickatrice', 'Medusa', 'green slime', 'Rider', 'Death', 'Pestilence', 'Famine', 'zombie', 'mummy', 'dwarf', 'were', 'kobold', 'bat', 'ghoul', 'vampire', 'chameleon', 'dog', 'cat', 'kitten', 'pony', 'acid blob', 'spotted jelly')  # undead corpses are pre-aged: always tainted
# pray.c critically_low_hp: the major-trouble line prayer fixes
LOW_HP = lambda s: s.get('hp', 1) <= 5 or s.get('hp', 1) * (5 if s.get('xl', 1) <= 5 else 6 if s.get('xl', 1) <= 13 else 7) <= min(s.get('hpmax', 1), 15 * s.get('xl', 1))
STRATEGY = ("You are a dwarven Valkyrie: strong melee, cold resistant, stealthy, infravision. Survive first. Monsters listed as weaker than you are easy experience: kill them rather than waiting or retreating. "
            "Fight weak monsters in melee; do not melee floating eyes (blue 'e') or cockatrices ('c' yellow) bare-handed. "
            "Prayer fixes low HP (below 1/7 max or below 6) and weakness from hunger, but only about once per 1000 turns; "
            "the first prayer is safe after roughly turn 300. Elbereth engraved in the dust scares most melee monsters "
            "(not @ humans or minotaurs) until you attack from it. Eat when Hungry. Food is scarce and fainting kills: eat fresh corpses of what you kill (not cockatrices, not old ones). Explore each level for useful items, "
            "then take the downstairs. A good pace is dungeon level no deeper than experience level + 1 early on. "
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
        self.traps = set()     # trap doors, holes, level teleporters: never path through (survives memory wipes)
        self.holes = set()     # the trap doors/holes among them: a way down when boxed in
        self.resets = 0        # times near/dead/blocked were wiped after fruitless searching
        self.corpses = {}      # square -> turn the corpse was first seen
        self.town = False      # a peaceful @ lives here (Izchak killed a run over a kicked shop door)
        self.arrival = None    # where we first stood here: the other '<' on the Oracle+1 level leads to Sokoban
        self.stairs = set()    # '>' found under objects by #terrain
        self.terrain_turn = -999


class Bot:
    def __init__(self, launcher, jev, mode='local'):
        self.fresh = False  # operator asked for a brand-new game
        self.refused_trap = False
        self.jump_hole = False
        self.frozen, self.frozen_turn = 0, None
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
            if re.search(r'Closed for inventory|stop damaging that door', text) and self.snap and self.snap.status.get('dlvl'):
                self.level().town = True
            if re.search(r'You feel feverish|You turn into a were', text):
                self.run['lycanthropy'] = True
            if re.search(r'You turn into a were|You find you must drop', text) and self.snap and self.snap.me:  # armor and weapon fall to the floor here (polyself.c break_armor/drop_weapon)
                self.run['dropped'] = (self.snap.status.get('dlvl'), self.snap.me)
            if re.search(r'is displeased|Thou durst call upon me|Then die, mortal|voice of \w+ (booms|rings out)', text):  # prayed too soon: god angry, Luck -3 (the quote after 'booms:' can be lost: wrath of Tyr killed T5998), praying again only makes it worse
                self.run['god_angry'] = True
            if re.search(r'grabs you|You are being choked|cannot escape from|swings itself around you', text) and self.snap:
                self.run['held'] = self.snap.status.get('turn') or 0
            if re.search(r'nymph stole|nymph steals|She stole', text) and self.snap:
                self.run['nymph_lvl'] = self.snap.status.get('dlvl')
            if 'You feel purified' in text:
                self.run['lycanthropy'] = False
            if re.search(r'no gold or credit|you pay for it|Usage fee|You owe|Pardon me, [A-Z]', text):
                self.run['debt'] = self.snap.status.get('dlvl') if self.snap else True
            if re.search(r'You do not owe|You have paid|You paid|Thank you for shopping|pay .* in full', text, re.I):
                self.run['debt'] = False
            if re.search(r'\b(throws|shoots|zaps|breathes|spits)\b|\b(arrow|dart|dagger|knife|bolt|spear|shuriken|missile|ray)s? (hits|misses|bounces)', text):
                self.run['shot_turn'] = self.snap.status.get('turn') or 0 if self.snap else 0
            if re.search(r'\b(hits|bites|stings|kicks|butts|claws|touches)!', text):
                self.run['hit_turn'] = self.snap.status.get('turn') or 0 if self.snap else 0
            ev = re.findall(r'(engulfs you|swallows you|The exit\?|laden with moisture|enveloped in a cloud of steam)|get expelled|regurgitates you|expels you|You (?:destroy|kill) (?:it|the)|dissipates|thin air|You get released', text)
            if ev:  # last event wins: "You kill the newt!  The fog cloud engulfs you!" is one message
                self.run['engulfed'] = bool(ev[-1])
            self.run['recent'].append(text)
            del self.run['recent'][:-12]

    def _load_runs(self):
        try:
            return [r for r in json.load(open(os.path.join(ROOT, 'runs', 'runs.json'))) if r.get('turns')]  # drop records of server restarts
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
        rules = [('Really attack', 'n'), ('Pay?', 'y'), ('Sell', 'y'), ('Itemized billing', 'n'), ('pray', 'y'), ('no return', 'n'), ('possessions identified', 'n'),
                 ('Stop eating', 'y'), ('Continue eating', 'n'), ('add to the current engraving', 'n'),
                 ('Do you want to keep the save file', 'n'), ('Dump core', 'n'), ('eat it', 'n')]
        if re.search(r'really \w+ (onto|into) that', q, re.I):  # paranoid trap confirmation: only drops and teleports are refused
            bad = re.search(r'trap door|hole|level teleporter|magic portal|polymorph|fire', q, re.I)
            if bad and self.jump_hole and bad.group(0).lower() in ('trap door', 'hole'):
                return 'y'
            if bad:
                self.refused_trap = bad.group(0).lower()
            return 'n' if bad else 'y'
        for pat, ans in rules:
            if pat.lower() in q.lower():
                if pat == 'Really attack' and self.snap:
                    self.peaceful_hint = True
                return ans
        return '\x1b'

    def answer_ask(self, q):
        if 'who are you' in q.lower():  # vault guard; wipe whatever movement keys already landed in the answer
            return '\b' * 200 + 'Jev\r'
        return '\x1b'

    def on_message(self, msg):
        if self.run is not None and re.search(r'You die|killed by|You starve|You drown', msg):
            self.run['death_msgs'].append(msg)

    def capture_endgame(self, text):
        if self.run is not None and ('Vanquished' in text or 'Goodbye' in text or 'killed by' in text):
            self.run['death_msgs'].append(text[:2000])

    def observe(self):
        self.settle()
        prev = self.snap
        self.snap = Snapshot(self.t, self.snap.me if self.snap else None)
        x, y = self.snap.cursor
        if len(self.snap.find('@')) > 1 and self.snap.lines[y][x] != '@' and top_prompt(self.snap.lines)[0] is None:
            self.t.send('\x12')  # redraw puts the cursor back on the hero (a shopkeeper @ was mistaken for Jev for 1800 turns)
            self.settle()
            self.snap = Snapshot(self.t, self.snap.me)
            x, y = self.snap.cursor
            if self.snap.lines[y][x] != '@':  # still ambiguous: getpos '@' (getpos.c NHKF_GETPOS_SELF) puts the cursor on the hero; took a Minetown @ for Jev, bumped walls until dead (T8716)
                self.t.send(';@')
                self.settle()
                pos = self.t.cursor()
                self.t.send('\x1b')
                self.settle()
                if MAP_TOP <= pos[1] <= MAP_BOT:
                    self.snap.me = pos
        s = self.snap.status
        if self.snap.me and s.get('dlvl'):
            lv = self.level()
            x, y = self.snap.me
            lv.near.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            recent = ' '.join(self.run['recent'][-3:]) if self.run else ''
            fresh = 'You kill' in recent and 'You destroy' not in recent
            for p in self.snap.find('%'):
                lv.corpses.setdefault(p, (s.get('turn') or 0) if fresh and cheb(p, self.snap.me) <= 2 and prev and prev.is_monster(*p) else -10**9 if 'You destroy' in recent and cheb(p, self.snap.me) <= 2 else -10**6)  # only where the kill stood: an old ape corpse next to a new kill was eaten tainted (T4763)
            if self.run is not None:
                self.run['max_dlvl'] = max(self.run['max_dlvl'], s['dlvl'])
                self.run['turns'] = s.get('turn') or self.run['turns']
        self.touch()
        return self.snap

    def level(self):
        dl = self.snap.status.get('dlvl', 0)
        lv = self.run['levels'].setdefault(('soko', dl) if self.soko() else dl, Level())  # Sokoban shares Dlvl numbers with the main dungeon
        lv.arrival = lv.arrival or self.snap.me
        return lv

    def soko(self):
        """(name, flip, ox, oy) when this is a Sokoban level (5.0 premaps them), else None; cached per screen."""
        snap = self.snap
        if getattr(self, '_soko_snap', None) is not snap:
            walls = {(x, y) for y in range(MAP_TOP, MAP_BOT + 1) for x in range(80)
                     if snap.at(x, y) is not None and snap.at(x, y).ch in '-|' and not snap.is_door(x, y)}
            self._soko_snap, self._soko = snap, sokoban.match(walls)
        return self._soko

    # ---------- pathing ----------
    def dijkstra(self, snap=None):
        snap = snap or self.snap
        lv = self.level()
        start = snap.me
        if start is None:  # @ hidden (invisible, --More-- over the map): no graph this tick
            return {}, {}
        dist, prev = {start: 0}, {}
        soko = self.soko() if snap is self.snap else None
        safe = sokoban.rollers(soko) if soko else set()  # a '^' roller walled Jev off from push 29 of soko4-1 three games running
        pq = [(0, start)]
        while pq:
            d, p = heapq.heappop(pq)
            if d > dist.get(p, 1e9):
                continue
            for (dx, dy) in DIRS.values():
                q = (p[0] + dx, p[1] + dy)
                if q in lv.blocked or q in lv.traps or q in self.avoid or not snap.walkable(*q):
                    continue
                if soko and (snap.at(*q).ch == '0' or snap.at(*q).ch == '^' and q not in safe or dx and dy and not all(snap.walkable(*c) and snap.at(*c).ch != '0' for c in ((p[0] + dx, p[1]), (p[0], p[1] + dy)))):
                    continue  # Sokoban: never shove a boulder off-plan or drop into a hole; no squeezing past boulders diagonally
                if dx and dy and (not snap.diag_ok(p, q) or (p == start and self.standing_on() == 'door')
                                  or not (snap.walkable(p[0] + dx, p[1]) or snap.walkable(p[0], p[1] + dy))):  # squeezing between two walls fails over 600 weight ("carrying too much to get through"): up to 2171 blocked moves a game
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
        before = self.t.lines()[0]
        self.t.send(keys + '.')
        for _ in range(20):  # wait for the answer itself: a stale "The 2nd elven arrow misses it." read as the reply made two adjacent elves "unknown '@'" (never attacked), dead (T7343)
            l0 = self.t.lines()[0]
            if re.match(r'^\S\s', l0) or '--More--' in ''.join(self.t.lines()[:3]) or l0 != before and not l0.startswith('Pick a'):
                break
            self.t.pump(0.2)
        lines = self.t.lines()
        kind, text = top_prompt(lines)
        desc = messages_from(text) if kind == 'more' else lines[0].strip()
        self.quiet = True
        self.settle()
        self.quiet = False
        if not re.match(r'^\S\s', desc):  # farlook answers "<glyph>   <what>"; anything else is a stale message ("The bugbear hits!" named a monster)
            return ''
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
                m['name'] = re.sub(r',.*$', '', desc) or f"unknown '{m['ch']}'"
                m['pet'] = m['pet'] or 'tame' in desc
                m['peaceful'] = 'peaceful' in desc
                if m['peaceful'] and m['ch'] == '@':  # shopkeeper, watchman or priest: breaking doors here gets us killed
                    self.level().town = True
        out = [m for m in out if not (m['name'] or '').startswith(('statue', 'a statue'))]
        for m in out:
            m['name'] = m['name'] or f"unidentified '{m['ch']}' ({m['fg']})"
            m['statue'] = m['name'].startswith(('statue', 'a statue'))
            if m['statue']:
                self.level().blocked.add(m['pos'])
            m['hostile'] = not m['pet'] and not m['peaceful'] and not m['statue'] and (m['ch'] != 'I' or m['dist'] <= 1)
            # sessile, only hurt you if you hit them: never a reason to hold still, and never walk into them
            m['passive'] = bool(re.search(r'floating eye|mold|shrieker|gas spore', m['name'])) or (m['ch'] == 'e' and m['fg'] in ('blue', 'white', 'gray'))
            m['where'] = f"{m['dist']} step{'s' if m['dist'] != 1 else ''} {compass(me, m['pos'])}"
        return out

    def species(self, m):
        if set(self.snap.status.get('conditions', [])) & {'Hallu', 'Hal', 'Hl'}:
            return 'hallucinated monster'  # names are random each turn: an 'Archon' (much stronger) got retreats, an 'acid blob' (much weaker) got hits; a pony killed Jev 60 -> 0 (T3336)
        name = re.sub(r'^(tame|peaceful)\s+', '', m['name'])
        return re.sub(r'\s+(called\s+.*|- .*)$', '', name)  # 'coyote - Overconfidentii Vulgaris'

    def threat(self, m):
        """' (level 0, much weaker than you)' etc. from the species' base level vs our XL."""
        name = self.species(m)
        lv = MONSTERS.get(name)
        if not lv or m['pet']:
            return ''
        d = lv[0] - (self.snap.status.get('xl') or 1)  # the -1 called an owlbear (difficulty 7) 'weaker' than XL 7; it killed Jev from 70 HP
        rel = 'much weaker than you' if d <= -3 else 'weaker than you' if d < 0 else 'about your level' if d <= 1 else 'stronger than you' if d <= 4 else 'much stronger than you'
        extra = {'floating eye': '; harmless, but never melee it (paralysis)', 'gas spore': '; explodes for 4d6 (up to 24 damage) when killed: throw things at it from 2+ squares away (the blast hits every square next to it) or walk away, melee only with 30+ HP'}.get(name, '')
        return f' (difficulty {lv[0]}, speed {lv[1]}, {rel}{extra})'

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
        alt = re.search(r'altar to .+? \((lawful|neutral|chaotic|unaligned)\)', blob.replace('\n', ' '))
        if alt and self.snap and self.snap.me:
            self.run.setdefault('altars', {})[(self.snap.status.get('dlvl'), self.snap.me)] = alt[1]
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
        # a gas spore's blast next to a shopkeeper has killed two runs: leave those alone entirely
        hostiles = [m for m in hostiles if not ('gas spore' in m['name'] and any(o['peaceful'] and cheb(o['pos'], m['pos']) <= 2 for o in mons))]
        dist, prev = self.dijkstra()
        # a monster we cannot reach (behind walls, across water) is not a reason to stand still
        # unless it is shooting: rested 15 turns on Elbereth while unreachable Uruk-hai shot it 29 -> 5, dead (T5766)
        shot = (s.get('turn') or 0) - self.run.get('shot_turn', -99) <= 3  # one volley is 3-4 messages: "shoots 2 arrows", "1st hits", "2nd misses" pushed 'shoots' out of a 3-line window; Jev waited on Elbereth at 4 HP under Uruk-hai fire (T7290)
        near = [m for m in hostiles if m['dist'] <= 6 and not m['passive'] and (m['dist'] <= 1 or m['pos'] in dist or shot)]
        opts = {}
        hp, hpmax = s.get('hp', 1), s.get('hpmax', 1)
        danger = f" You are at {hp}/{hpmax} HP: one or two more hits could kill you." if hp * 3 < hpmax else ''

        # attacking from Elbereth erases it and costs alignment (5.0: "You feel like a hypocrite"); only @ and minotaurs ignore it
        on_e = self.engraved_here() and hp < 0.9 * hpmax and not shot  # zapped on Elbereth by an adjacent orc, the only option left was 'retreat' (T4400); healthy: fight from it rather than wait out a speed-1 fog cloud
        for m in hostiles:
            if m['dist'] == 1 and m['pos'] not in self.avoid and not (on_e and m['ch'] != '@' and 'minotaur' not in m['name']):
                if m['name'] == "unknown '@'":
                    continue  # unidentified @ can be a shopkeeper or watchman: Jev hit Sarnen beside a mimic in her shop, wand of striking, dead (T5361)
                low = re.compile(r'shrieker|brown pudding|black pudding')
                if low.search(m['name']) and any(o['dist'] == 1 and not low.search(o['name']) for o in hostiles):
                    continue  # no attacks: Jev hit a shrieker 3 turns while a werejackal and iguana killed it (T1402); hit a brown pudding 4 times (iron splits it, uhitm.c) while an owlbear crushed it 53 -> 8, dead (T5320)
                d = DIR_OF[(m['pos'][0] - me[0], m['pos'][1] - me[1])]
                opts[f'attack_{d}'] = (f"Attack {m['name']} ({DIR_NAME[d]})", f"Melee the adjacent {m['name']} to the {DIR_NAME[d]}.{danger}", lambda d=d: self.act_fight(d))
        were_throw = None  # an animal-form were's bite gives lycanthropy 1 in 4 hits (uhitm.c mhitm_ad_were): 44 of 509 runs caught it; wiki: kill them before melee range
        nymph_throw = None  # nymphs stole a ration, spear, shield and slime molds in one game: hit them before they arrive
        missiles = [it for it in self.inventory if re.search(r'\b(daggers?|knife|knives|darts?|shuriken|spears?|javelins?)\b', it['text'])
                    and 'weapon in' not in it['text'] and 'wielded' not in it['text'].replace('not wielded', '')]
        # hand-thrown arrows do rnd(2) (uhitm.c): only for passives. Boxed by a floating eye with 7 arrows, meleed it, paralysed, starved (T2426)
        arrows = [it for it in self.inventory if re.search(r'\b(arrows?|bolts?)\b', it['text'])]
        if (missiles or arrows) and not on_e:
            for m in hostiles:
                dx, dy = m['pos'][0] - me[0], m['pos'][1] - me[1]
                if (missiles or m['passive']) and (1 if m['passive'] and 'gas spore' not in m['name'] else 2) <= m['dist'] <= 6 and (dx == 0 or dy == 0 or abs(dx) == abs(dy)) and self.clear_line(me, m['pos']):
                    d = DIR_OF[((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))]
                    it = (missiles or arrows)[0]
                    opts[f'throw_{d}'] = (f"Throw {it['text']} at {m['name']}", f"Throw item {it['letter']} {DIR_NAME[d]} at {m['name']} {m['where']}. Safe way to hit monsters you must not melee (floating eyes, molds); pick it up again afterwards.", lambda l=it['letter'], d=d: self.act_throw(l, d))
                    if 'nymph' in m['name'] and m['dist'] >= 2:
                        nymph_throw = f'throw_{d}'
                    if 'were' in m['name'] and m['ch'] != '@' and not self.run.get('lycanthropy'):
                        were_throw = f'throw_{d}'
        wand = next((it for it in self.inventory if re.search(r'\bwand\b', it['text'])
                     and not re.search(r'probing|light|nothing|opening|locking|enlightenment|secret door|create monster|wishing|undead turning|polymorph|make invisible|speed monster', it['text'])
                     and self.run.setdefault('zaps', {}).get((it['text'], s.get('dlvl')), 0) < 4), None)  # a silent unknown wand (polymorph) zapped 379 times at molds turned one into a gargoyle that pinned Jev until it starved (T5526)
        if wand:  # walled in by floating eyes once for 13000 turns with an unknown wand in the pack
            for m in hostiles:
                dx, dy = m['pos'][0] - me[0], m['pos'][1] - me[1]
                # also in a losing melee: two unknown wands stayed in the pack while an ogre took 69 -> 0 (T4539)
                if (m['passive'] or hp < 0.5 * hpmax and 'weaker' not in self.threat(m)) and (2 if 'gas spore' in m['name'] else 1) <= m['dist'] <= 6 and (dx == 0 or dy == 0 or abs(dx) == abs(dy)) and self.clear_line(me, m['pos']):
                    d = DIR_OF[((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))]
                    opts[f'zap_{d}'] = (f"Zap {wand['text']} at {m['name']}", f"Zap wand {wand['letter']} {DIR_NAME[d]} at the {m['name']} {m['where']}. Unknown effect; many wands kill or move monsters, and it identifies the wand.", lambda l=wand['letter'], d=d, t=(wand['text'], s.get('dlvl')): (self.run['zaps'].__setitem__(t, self.run['zaps'].get(t, 0) + 1), self.act_throw(l, d, 'z'))[1])
        # yellow light: its only attack is a 10d20-turn blinding explosion (monsters.h AT_EXPL), speed 15 so no outrunning it; Elbereth stops it (wiki). Blinded twice, both dead to unseen biters (T4631, T2307)
        # a jabberwock (difficulty 18) 3 squares off at XL6 got "Close in on" and no Elbereth: 67 -> 0 in two turns (T4199). @ and minotaurs ignore Elbereth
        dread = [m for m in hostiles if m['dist'] <= 5 and ('much stronger' in self.threat(m) or 'yellow light' in m['name']) and m['ch'] != '@' and 'minotaur' not in m['name']]
        pack = len(near) >= 5 or len(near) >= 3 and sum((MONSTERS.get(self.species(m)) or [1])[0] for m in near) > 2 * (s.get('xl') or 1)  # 9 level-1 killer bees summed under 2 XL, '<' a step away: poisoned at 25/72 (T8697)  # stepped off Elbereth into four wargs: 69 -> 0 HP in 4 turns
        hallu = bool(set(s.get('conditions', [])) & {'Hallu', 'Hal', 'Hl'})  # names are random: closed in on a 'nickelpede' that was a mumak at 39/73, dead (T7654)
        for m in near[:2] if not (danger or pack or hallu and hp < 0.8 * hpmax) else ():  # walking into a fight at a third of max HP killed three giant-bat runs
            if m['dist'] > 1 and m['pos'] in dist and not re.search(r'unicorn|yellow light|nymph', m['name']):  # nymph: stepping up to one cost a shield and a helm in one game, AC 10, dead (T6402); throw or let her come  # yellow light: its explosion blinds 10d20 turns, 5 of 6 blind deaths; throw instead (wiki). unicorn: speed 24, keeps its distance, butt+kick took 24 HP in one turn
                opts[f"approach_{m['pos'][0]}_{m['pos'][1]}"] = (f"Close in on {m['name']}", f"Step toward {m['name']} {m['where']}.", lambda m=m: self.act_go(m['pos'], dist_prev=None, steps=1, adjacent_ok=True))
        strong = False
        if near:
            if self.engraved_here() and not shot:  # Elbereth only stops melee (wiki); stepping off to 'retreat' threw away fresh Elbereths in two rothe deaths
                if (hp < 0.7 * hpmax or dread) and not any(m['ch'] == '@' or 'minotaur' in m['name'] for m in near):  # @ (elves, humans) and minotaurs ignore it (monmove.c onscary): sat 9 turns on it by a Woodland-elf, dead (T4259); 'stuck on Elbereth': up to 44% of a game's decisions were waits on it (0.9 before); at 77/80 HP Jev sat on Elbereth ~1400 turns watching a fog cloud
                    opts['wait'] = ('Stay on Elbereth one turn', 'You stand on Elbereth: most monsters will not melee you here, so waiting heals you safely. Stepping off or attacking loses the protection.', self.act_wait_elbereth)
            else:
                fast = [m['name'] for m in near if (MONSTERS.get(self.species(m)) or [0, 0])[1] >= 12]  # our speed is 12
                if not shot and not any(m['dist'] <= 1 for m in near):  # "let them come" while six jackals and a werejackal already bit: 42 -> 0 HP in 3 waits
                    opts['wait'] = ('Hold position one turn', 'Search in place for one turn and let monsters come to you (you get the first hit when they step adjacent).', lambda: self.act_keys('ms', 'waited'))
                # wiki (Fighting in corridors): a pack surrounds you on up to 8 sides; in a corridor only one or two can reach you
                open_n = lambda q: sum(snap.walkable(q[0] + dx, q[1] + dy) for dx, dy in DIRS.values())
                pack_near = [m for m in near if m['dist'] <= 5]
                gap = min((m['dist'] for m in pack_near), default=0)
                if len(pack_near) >= 2 and open_n(me) > 2 and gap >= 2:  # walked off with two apes adjacent at 14/42: free hits, dead (T2116)
                    choke = min((q for q, dq in dist.items() if 0 < dq <= 8 and open_n(q) <= 2 and q not in self.level().traps and not snap.is_monster(*q)
                                 and min(cheb(q, m['pos']) for m in pack_near) >= gap), key=dist.get, default=None)
                    if choke:
                        opts['choke'] = ('Fight from a corridor', f"Walk {dist[choke]} steps {compass(me, choke)} to a corridor or doorway square, so the {len(pack_near)} monsters can only reach you one or two at a time.", lambda q=choke: self.act_go(q, steps=8))
                weak_only = all('weaker' in self.threat(m) for m in near if m['dist'] <= 1) and any(m['dist'] <= 1 for m in near) and hp >= 0.25 * hpmax  # XL8 at 20/74 retreated twice from a rothe (speed 9: adjacent again each turn, 3 attacks), engraving garbled, dead (T13611)
                if not fast and not weak_only and not shot and hp < 0.7 * hpmax and self.retreat_dir(hostiles):  # one step back from a wand-zapping hill orc, 3 times at 5/45: zapped dead (T4400)  # at 50/53 Jev retreated 6 times from hill orcs, eating hits without swinging (T2966); retreating from a giant bat (speed 22) just gives it free hits
                    opts['retreat'] = ('Retreat one step', 'Step to the adjacent square farthest from visible hostiles.' + ' Everything nearby is slower than you, so you can open a gap.', lambda: self.act_retreat(hostiles))
            ups_near = [p for p in snap.find('<') if dist.get(p, 99) <= 8]
            # jabberwock (difficulty 18) at XL 8, '<' 2 steps away: stood and fought, 85 -> 0 (T8069). Non-stalkers never follow upstairs (mondata.c levl_follower)
            strong = any('much stronger' in self.threat(m) for m in near)
            if (danger or strong or pack) and ups_near and self.standing_on() != '<' and s.get('dlvl', 1) > 1:
                p = ups_near[0]
                opts['flee_up'] = ('Run for the upstairs', f"The up staircase is {dist[p]} steps {compass(me, p)}: walk there and climb. Only monsters right next to you follow.", lambda p=p: self.flee_up(lambda: self.act_descend(p, '<')))
            if snap.lines[me[1]] and self.standing_on() == '<' and s.get('dlvl', 1) > 1:
                opts['upstairs'] = ('Flee up the stairs', 'Climb the up staircase you are standing on; adjacent monsters may follow.', lambda: self.flee_up(lambda: self.act_keys('<', 'went up')))
        if (strong or pack) and ({'flee_up', 'upstairs'} & opts.keys()):  # a werewolf's summoned wolves (no M2_STALK: can't follow) took 34 -> 6 in a turn, '<' one step away (T5826)
            opts = {k: v for k, v in opts.items() if not k.startswith(('attack_', 'approach_', 'explore'))}
        walled = len(dist) <= 3 and any(m['passive'] and m['dist'] == 1 for m in hostiles)  # boxed in by floating eyes
        # at 56/64 Jev wrote Elbereth instead of closing on a large kobold, which stood off and zapped lightning until it died (T9749)
        # blind at 8/76, unseen apes' hits lost in 5-turn rests: rested to death with no Elbereth offered (T6987)
        if dread:
            opts = {k: v for k, v in opts.items() if not k.startswith(('approach_', 'explore'))}
        if (near and hp < 0.7 * hpmax or dread or walled or self.unseen_attacker() or 'Blind' in s.get('conditions', []) and hp < 0.7 * hpmax) and not self.engraved_here() and not (near and all(m['ch'] == '@' for m in near)) and not any(m['ch'] == '@' and m['dist'] == 1 for m in hostiles) \
                and not set(s.get('conditions', [])) & {'Hallu', 'Hal', 'Hl', 'Stun', 'Stn', 'Conf', 'Cnf', 'Lev'} \
                and not (any(m['dist'] == 1 for m in hostiles) and (s.get('turn') or 0) - self.run.get('engrave_interrupted', -99) <= 5):  # @ ignore it (monmove.c onscary: S_HUMAN); 2 Elbereths at 9/49 beside a Woodland-elf, a rock mole also near, dead (T2543); engrave.c scrambles writing
            opts['elbereth'] = ('Engrave Elbereth', 'Write Elbereth in the dust here with a finger (1 turn). Most monsters will not melee you while you stand on it; attacking from it erases it.' + (' The best move when badly hurt.' if danger else '') + (' Scared monsters flee, so this can drive off the ones boxing you in.' if walled else ''), self.act_elbereth)
        if 'choke' in opts and hp >= 0.4 * hpmax:  # wiki: Elbereth is breathing room; a corridor is how to actually fight a group
            opts.pop('elbereth', None)

        if danger:
            for it in self.inventory:  # unknown potion beside a Woodland-elf at 25/90: asleep, dead (T9392); an unknown potion on a working Elbereth: 11% heal, sleeping killed a Jev the warhorse was fleeing from
                if re.search(r'\bpotions?\b', it['text']) and (not self.engraved_here() or 'healing' in it['text']) and ('healing' in it['text'] or LOW_HP(s) or not any(m['dist'] <= 1 for m in hostiles)) \
                        and not re.search(r'sleeping|blindness|hallucination|confusion|booze|sickness|paralysis|water|oil|clear', it['text']):  # clear = water: 4 blind quaffs of it vs a housecat pack (T2801); drank a known potion of sleeping held by an ape (T9512)
                    opts[f"quaff_{it['letter']}"] = (f"Quaff {it['text']}", f"Drink this potion hoping it heals.{danger}", lambda l=it['letter']: (self.act_keys('q' + l, 'quaffed'), self.read_inventory())[0])  # stale inventory re-offered a drunk potion 3-4 times in a fight (T2801, T5616)
                    break

        fatal = [c for c in s.get('conditions', []) if c in ('FoodPois', 'Fpois', 'Poi', 'TermIll', 'Ill', 'Stone', 'Ston', 'Sto', 'Slime', 'Slim', 'Slm', 'Strngl', 'Stngl', 'Str', 'InLava', 'Lav')]  # kill in a few turns; prayer cures
        lyc = self.run.get('lycanthropy') and not any(m['dist'] <= 2 for m in hostiles)  # 'cure it mid-fight at 60%+ HP' spent the prayer at 24/32 beside a wererat, dead at 7/32 (T1231): reverted  # not mid-fight: curing it at 18/46 beside the wererat spent the prayer, dead 5 turns later (T3790); slow, and each were bite re-infects: it follows the normal timeout (two runs prayed every 4 turns into "Then die, mortal!")
        trouble = LOW_HP(s) or s.get('hunger') in ('Weak', 'Fainting') or fatal or lyc
        last = self.run.get('prayed_turn')
        if last is not None and last > (s.get('turn') or 0):
            last = self.run['prayed_turn'] = None
        turn = s.get('turn') or 0
        if s.get('hunger') == 'Fainting':
            self.run.setdefault('faint_start', turn)
        else:
            self.run.pop('faint_start', None)
        # eat.c: Fainting starts at nutrition 0, starvation below -(100 + 10 Con): pray ~40 turns before that, as late as is safe.
        # A fixed 150 since the last prayer prayed 171 turns after a good one: "Tyr is displeased", angry, fainted to death (T2527)
        # Weak in melee is major trouble (pray.c TROUBLE_STARVING) on top of the fight: 950 turns on, 25/51 in a gang, dead unprayed (T4496)
        # Weak at 400 prayed 851 turns after a good prayer: "Thou art arrogant", angry god, fainted to death (T8071). Weak can't kill; 'starving' covers the end
        starving = turn - self.run.get('faint_start', turn) >= 60 + 10 * (s.get('co') or 10)
        # prayer timeout is ~50-1000 turns; praying early angers the god (a couatl killed an earlier run)
        # timeout after a good prayer is ~350 on average and major trouble is fixed below 200: 600 is a fair bet for
        # low HP, hunger can wait longer (a couatl killed the run that prayed 6 times in 33 turns)
        # 5.0 source: timeout starts at 300, drops 1/turn, and major trouble (all of these) is fixed at <= 200
        # rnz(350) is heavy-tailed, so waiting buys little: P(rnz - elapsed < 200) is .66 at 300, .87 at 500, .94 at 1000 turns (simulated;
        # nethack-tools' prayer timer uses the same model). 1000 left low-HP Jevs dying unprayed; the gamble below covers dying with a monster adjacent;
        # starving is certain death, so hunger bets earlier (1000 let a Weak Jev faint to death 640 turns after praying; 600 did it again at 524, T5771)
        if trouble and not self.run.get('god_angry') and (fatal or starving or (turn - last >= {'Weak': 1000 if not any(m['dist'] <= 1 for m in hostiles) else 500}.get(s.get('hunger'), 500) if last is not None else turn >= 110)):
            opts['pray'] = ('Pray to Tyr', f"You are in trouble ({fatal[0] + ': fatal within a few turns unless cured' if fatal else 'low HP' if LOW_HP(s) else 'lycanthropy: you will turn into a jackal' if lyc and s.get('hunger') not in ('Weak', 'Fainting') else s.get('hunger')}). Last prayer: {'never' if last is None else 'turn ' + str(last)}. Current turn {s.get('turn')}. A successful prayer fully heals.", self.act_pray)
        elif LOW_HP(s) and (any(m['dist'] <= 7 for m in hostiles) or self.unseen_attacker()) and last is not None and turn - last >= 100:  # a quasit's wand took 29 -> 0 from range; 3/54 HP 243 turns after a prayer, no gamble offered, dead (T5218). rnz(350)<=200+t is ~50% at t=100; failing angers Tyr, but death was certain
            opts['pray'] = ('Pray to Tyr (gamble)', f"Last prayer was only {turn - last} turns ago: Tyr may well be angry (bad luck, maybe smiting). But at {s.get('hp')} HP with a monster attacking, this may be the last chance.", self.act_pray)

        if not self.run.get('god_angry') and (turn - last >= 800 if last is not None else turn >= 300):  # prayer ready: fight on, pray at low HP
            opts = {k: v for k, v in opts.items() if not (k.startswith('quaff_') and 'healing' not in v[0])}  # a swirly potion of sleeping at 15/50, prayer 1460 turns old: frozen, killed by a pony

        # shop floor gold belongs to the shopkeeper: picking it up billed Jev, who then could not leave and died to Mr. Kipawa; eating its food kept another Jev locked in a shop for 4000 turns
        shop = any(d == s.get('dlvl') and cheb(p, me) <= 7 and any(re.search(r'for sale|no charge', i) for i in v) for (d, p), v in self.run.get('here', {}).items()) or self.run.get('debt') == s.get('dlvl')
        if shop:  # an unknown wand zapped at a brown mold in Sipaliwini's store angered her: dead to her wand (T1314)
            opts = {k: v for k, v in opts.items() if not k.startswith(('zap_', 'throw_'))}
        if s.get('hunger') in ('Hungry', 'Weak', 'Fainting'):
            for it in self.inventory:
                if re.search(FOOD, it['text']) and not any(n in it['text'] for n in NEVER_EAT) and it['text'] not in self.run.get('inedible', ()) \
                        and not re.search(r'potion|gem|stone|glass|spellbook|wand|ring|scroll|amulet|opener', it['text']) \
                        and (s.get('hunger') != 'Hungry' or 'tripe' not in it['text'] and not any(m['dist'] <= 1 for m in hostiles)):
                    # tripe: rn2(2) vomiting for non-orc non-cavemen (eat.c); ate it Hungry beside a black unicorn, confused+stunned, dead (T4650)
                    opts[f"eat_{it['letter']}"] = (f"Eat {it['text']}", f"You are {s.get('hunger')}: eat item {it['letter']} from your pack now, before you weaken and faint (fainting next to a monster is how most of your games have ended).", lambda l=it['letter']: self.act_eat(l))
            here = [i for i in self.here_items() if 'corpse' in i and not any(n in i for n in NEVER_EAT)]
            age = s.get('turn', 0) - lv.corpses.get(me, s.get('turn', 0))
            fresh = [p for p, t0 in lv.corpses.items() if p != me and p in dist and s.get('turn', 0) - t0 < 35 and dist[p] < 15]
            if fresh and not here and not shop:
                p = min(fresh, key=dist.get)
                opts['goto_corpse'] = ('Go eat the fresh corpse', f"Walk {dist[p]} steps {compass(me, p)} to a corpse that appeared recently and eat it if it is safe.", lambda p=p: self.act_goto_corpse(p))
        if s.get('hunger') != 'Satiated' and not shop:
            here = [i for i in self.here_items() if 'corpse' in i and not any(n in i for n in NEVER_EAT)]
            age = s.get('turn', 0) - lv.corpses.get(me, -10**6)  # a corpse we did not see appear is of unknown age: treat as rotten
            why = ' Packed food is rare and most deaths so far were fainting from hunger: eating fresh kills now, even when not hungry, is what keeps you alive later.'
            # eat.c: rotted = age / (10 + rn2(20)), +2 if cursed; > 5 tainted (never before age 60 uncursed), > 3 only rnd(8) HP: so < 50 is safe, and arrival from 15 steps at < 35 stays under it (one Jev ate nothing for 1650 turns of kills, fainted, T4698)
            # lichens and lizards never rot; starving with no prayer left, a maybe-tainted corpse beats certain death (walked past a floating eye corpse, fainted to a bat)
            if here and (age < 50 or re.search(r'lichen|lizard', here[0]) or s.get('hunger') in ('Weak', 'Fainting') and 'pray' not in opts and lv.corpses.get(me, -10**6) > -10**9):  # a destroyed zombie's corpse is pre-aged: always tainted, Weak Jev ate one and died of food poisoning (T2797)
                opts['eat_corpse'] = (f"Eat the {here[0]} here", f"Eat {here[0]} on this square. It appeared about {age} turns ago (old corpses can be rotten or poisonous).{why}", self.act_eat_corpse)
            fresh = [p for p, t0 in lv.corpses.items() if p != me and p in dist and s.get('turn', 0) - t0 < 35 and dist[p] < 10]
            if fresh and not here and not near and 'goto_corpse' not in opts:
                p = min(fresh, key=dist.get)
                opts['goto_corpse'] = ('Go eat the fresh corpse', f"Walk {dist[p]} steps {compass(me, p)} to a corpse that appeared recently and eat it if it is safe.{why}", lambda p=p: self.act_goto_corpse(p))
        if 'eat_corpse' in opts and not near:  # taken 15 of 98 offers (explore won), and hunger is the top killer: eat it
            opts = {k: v for k, v in opts.items() if k in ('eat_corpse', 'pray')}
        elif 'goto_corpse' in opts and not near:  # passed up for explore/rest ~60% of the time; one Jev prayed 6 times for food in 7700 turns
            opts = {k: v for k, v in opts.items() if k in ('goto_corpse', 'pray')}
        if any(m['dist'] <= 1 for m in near):  # Weak, walked for a corpse through a bugbear + hobgoblin gang: free hits, dead (T4496)
            opts.pop('goto_corpse', None)
        # eat.c:1953: any corpse has a 1/7 rotten roll, ~1 in 37 meals knocks you out up to 10 turns; an elf takes ~15 turns to eat.
        # Elves out of sight in a dark room beat an unconscious Jev 46 -> 1 HP (T8218)
        if s.get('hunger') not in ('Weak', 'Fainting') and (any(m['dist'] <= 6 for m in hostiles) or (s.get('turn') or 0) - self.run.get('hit_turn', -99) <= 5):
            opts = {k: v for k, v in opts.items() if k not in ('eat_corpse', 'goto_corpse')}
        if s.get('hunger') not in ('Weak', 'Fainting') and any(m['dist'] <= 2 for m in near):  # eating twice mid-swarm took 25 HP to 1 (giant rat, T2344)
            opts = {k: v for k, v in opts.items() if not k.startswith(('eat_', 'goto_corpse'))}

        if shop and self.run.get('debt'):  # broke and billed, the shopkeeper blocks the door forever: sell things (general stores buy anything)
            if s.get('gold'):
                opts['sell_pay'] = ('Pay the shopkeeper', 'You owe the shopkeeper and now have gold; pay so they let you out.', self.act_pay)
            for it in [it for it in self.inventory if not re.search(r'weapon in|being worn|gold piece', it['text'])][:3]:
                opts[f"sell_{it['letter']}"] = (f"Sell {it['text']} to pay your debt", "You owe the shopkeeper and have no gold, so they will not let you leave. Drop this to sell it for credit, then pay.", lambda l=it['letter']: (self.act_keys('d' + l, 'sold'), self.act_keys('p', 'paid'))[1])
        for i, item in enumerate(self.here_items()[:4]):
            price = re.search(r'for sale, (\d+) zorkmid', item)
            if price and FOOD.search(item) and 'corpse' not in item and int(price[1]) <= s.get('gold', 0) and not self.run.get('debt'):
                opts[f'buy_{i}'] = (f"Buy {item}", f"Pick up {item} and pay {price[1]} of your {s.get('gold')} gold. Packed food prevents fainting from hunger.", lambda item=item: (self.act_pickup(item), self.act_pay())[1])
                continue
            if shop or 'for sale' in item or 'corpse' in item or HEAVY.search(item) or item in self.run.get('heavy', ()):
                continue
            opts[f'pickup_{i}'] = (f"Pick up {item}", f"Pick up {item} from this square.", lambda item=item: self.act_pickup(item))
        if 'Burdened' in s.get('conditions', []) or 'Stressed' in s.get('conditions', []):
            for it in self.inventory:
                if HEAVY.search(it['text']) and not re.search(r'weapon in|being worn', it['text']):
                    opts[f"drop_{it['letter']}"] = (f"Drop {it['text']}", f"You are {'Burdened' if 'Burdened' in s['conditions'] else 'Stressed'}: slower, and you can't fight or flee well. {it['text']} is heavy and of little use.", lambda l=it['letter']: self.act_keys('d' + l, 'dropped it'))
        lev = next((it for it in self.inventory if re.search(r'levitation|invisibility', it['text']) and re.search(r'being worn|on (left|right) hand', it['text'])), None)
        if lev and (not near or 'invisib' in lev['text']):  # -2 levitation boots floated Jev over the stairs for 2400 turns until it starved
            # invisible, the hero has no @ on screen: the bot took an elf for itself while a soldier ant ate it (T5244)
            opts = {f"remove_{lev['letter']}": (f"Take off {lev['text']}", 'It keeps you from playing normally (no stairs while levitating; while invisible you cannot see where you are). Remove it.', lambda it=lev: self.act_keys(('R' if 'hand' in it['text'] else 'T') + it['letter'] + '\x1b', 'took it off'))}
        # cursed plain cloak: only blocks body-armor swaps (wiki), and any cloak is MC1 against were bites; cursed mithril still beats AC 7+.
        # Unknown-look cloaks (tattered cape, opera cloak...) can be invisibility: still need a known BUC.
        worn_ac = max((suit_ac(it['text']) or 0 for it in self.inventory if 'being worn' in it['text']), default=0)
        better_body = any((suit_ac(it['text']) or 0) > worn_ac and 'being worn' not in it['text'] and it['text'] not in self.run.get('unwearable', {}) for it in self.inventory)
        if not near:
            for it in self.inventory:
                t = it['text']
                if re.search(r'\b(armor|mail|helmet|helm|cap|hat|cloak|mantelet|mithril-coat|boots|shoes|gloves|gauntlets|shield|robe|apron|shirt|coat|jacket|tunic)\b', t) and 'being worn' not in t and not re.search(r'levitation|invisibility', t) and not (re.search(r'cloak|mantelet|mithril', t) and not re.search(r'\b(uncursed|blessed)\b', t) and not (re.search(r'\b(dwarvish|hooded|orcish|leather|elven) cloak|mantelet|faded pall', t) and not better_body) and not ('mithril' in t and (s.get('ac') or 0) >= 7)) and (s.get('ac') or 0) > self.run.setdefault('unwearable', {}).get(t, -99):  # AC got worse since the failed try (nymph stole the worn armor): try again
                    opts[f"wear_{it['letter']}"] = (f"Wear {t}", "Put on this armor (takes a few turns; may be cursed if unidentified).", lambda it=it: self.act_wear(it))
            worn = next((it for it in self.inventory if 'being worn' in it['text'] and suit_ac(it['text']) is not None), None)
            better = max((it for it in self.inventory if 'being worn' not in it['text'] and (suit_ac(it['text']) or 0) > (suit_ac(worn['text']) if worn else 99)
                          and it['text'] not in self.run.setdefault('unwearable', {})), key=lambda it: suit_ac(it['text']), default=None)
            if better and not any('cloak' in it['text'] and 'being worn' in it['text'] for it in self.inventory):  # 'cannot wear armor over a cloak'
                opts[f"wear_{better['letter']}"] = (f"Swap {worn['text']} for {better['text']}", f"Body armor: {better['text']} gives {suit_ac(better['text'])} AC, {worn['text']} only {suit_ac(worn['text'])}. Take it off, put the better one on.", lambda w=worn, b=better: self.act_swap(w, b))
            if any(k.startswith('wear_') for k in opts):  # offered, rarely taken: died at AC 6 with an orcish helm in the pack and no helm on (T3559)
                opts = {k: v for k, v in opts.items() if k.startswith(('wear_', 'eat_')) or k == 'pray'}  # each try wears it or marks it unwearable, so no loop

        # altars (wiki "Altar", "Sacrifice"; 5.0 pray.c): dropping identifies BUC on any altar; a fresh (<50 turns) corpse offered on a lawful one
        # cuts prayer timeout, adds luck, and at timeout 0 gives a 1 in 6 first-gift chance (bestow_artifact)
        altars = self.run.get('altars', {})
        here_alt = altars.get((s.get('dlvl'), me)) if self.standing_on() == '_' else None
        if not near and not shop:
            unseen = [p for p in snap.find('_') if p in dist and (s.get('dlvl'), p) not in altars and p != me]
            if unseen or (self.standing_on() == '_' and here_alt is None):
                q = min(unseen, key=dist.get) if unseen else me
                opts['altar'] = (f"Go check the altar {compass(me, q)}", f"Walk {dist.get(q, 0)} steps to the altar '_' to learn its alignment. Altars reveal whether items are cursed, and a lawful one takes sacrifices.", lambda q=q: self.act_altar(q))
            unk = [it for it in self.inventory if UNKNOWN_BUC(it['text']) and it['text'] not in self.run.setdefault('buc_done', set())]
            if here_alt and unk:
                opts['buc'] = ('Drop your unknown items on the altar to learn if they are cursed', f"Drop {len(unk)} item(s) whose curse status is unknown and pick them back up: a black flash means cursed, amber blessed. Then you can safely wear the armor.", lambda unk=unk: self.act_buc(unk))
            lawful = [p for (dl, p), a in altars.items() if dl == s.get('dlvl') and a == 'lawful' and (p in dist or p == me)]
            carried = next((it for it in self.inventory if 'corpse' in it['text'] and not any(n in it['text'] for n in NEVER_OFFER)), None)
            if lawful and carried and s.get('turn', 0) - self.run.get('carry_turn', -99) < 45:
                opts['offer'] = (f"Offer {carried['text']} at the lawful altar", f"Walk {dist.get(lawful[0], 0)} steps to Tyr's altar and sacrifice it while fresh: lowers prayer timeout, raises luck, may bring a gift.", lambda l=carried['letter'], q=lawful[0]: self.act_offer(l, q))
            elif lawful and s.get('hunger') not in ('Hungry', 'Weak', 'Fainting'):
                cands = [(p, t0) for p, t0 in lv.corpses.items() if p in dist and (s.get('dlvl'), p) not in self.run.setdefault('sac_skip', set())
                         and dist[p] + 2 * cheb(p, lawful[0]) < 40 - (s.get('turn', 0) - t0)]
                if cands:
                    p, t0 = min(cands, key=lambda c: dist[c[0]])
                    opts['carry'] = ('Carry the fresh corpse to the altar', f"Walk {dist[p]} steps {compass(me, p)}, pick up the corpse and offer it at Tyr's altar before it gets too old.", lambda p=p, t0=t0: self.act_carry(p, t0))
        if not near and {'altar', 'buc', 'offer', 'carry'} & opts.keys():
            opts = {k: v for k, v in opts.items() if k in ('altar', 'buc', 'offer', 'carry', 'pray') or k.startswith('eat')}
        if any('stop damaging' in t for t in self.run['recent']):
            self.run.setdefault('door_warned', set()).add(s.get('dlvl'))
        # dokick.c: the watch only reacts if it can see you (first a warning); town closets locked Jev in for 10000 turns of searching (T16506)
        watched = lv.town and (any(m['peaceful'] and m['ch'] == '@' for m in mons) or s.get('dlvl') in self.run.get('door_warned', ()))
        for d, p in [(k, (me[0] + v[0], me[1] + v[1])) for k, v in DIRS.items() if not (v[0] and v[1])]:
            if p in lv.locked and not watched:
                opts[f'kick_{d}'] = (f"Kick the locked door {DIR_NAME[d]}", 'Kick the locked door to break it open (may take several tries).', lambda d=d: self.act_kick(d))

        # closed doors read off the screen each turn: level memory alone once left three doors unexplored for 10000 turns
        doors = []
        for door in snap.find('+'):
            orth = [(door[0] + dx, door[1] + dy) for dx, dy in DIRS.values() if not (dx and dy)]
            spots = [q for q in orth if q in dist]
            if snap.is_door(*door) and spots and any(snap.at(*q) is not None and snap.at(*q).ch == ' ' for q in orth):
                q = min(spots, key=dist.get)
                doors.append((dist[q], door, q))
        for _, door, q in sorted(doors)[:2]:
            if door in lv.locked and (cheb(door, me) <= 1 or watched):
                continue  # kick_<dir> covers it; in town a locked door stays shut
            what = 'locked door' if door in lv.locked else 'closed door'
            opts[f'door_{door[0]}_{door[1]}'] = (f"Go through the {what} {compass(me, door)}", f"Walk {dist[q]} steps to the {what} {compass(me, door)}, open it (kicking it if locked). What lies behind is unexplored.", lambda q=q, door=door: self.act_kick_door(q, door))
        if (not near or s.get('hunger') in ('Weak', 'Fainting')) and not shop:  # starving beats a hovering monster; only stepped-on items were ever picked up; Jev fainted twice with food lying in view
            objs = [q for c in ')[%?/=!("$' for q in snap.find(c)]
            if self.run.get('dropped') == (s.get('dlvl'), me) or not (s.get('title') or '').startswith('Were') and self.run.get('dropped', (0,))[0] != s.get('dlvl'):
                self.run.pop('dropped', None)
            loot = [q for q in objs if q in dist and 0 < dist[q] <= 15 and ((s.get('dlvl'), q) not in self.run['here'] or self.run.get('dropped') == (s.get('dlvl'), q)) and lv.corpses.get(q, -1) < 0
                    and sum(cheb(q, o) <= 3 for o in objs) < 6]  # a dense cluster is a shop
            if loot:
                starving = s.get('hunger') in ('Weak', 'Fainting')
                q = min(loot, key=lambda q: (not (starving and snap.at(*q).ch == '%'), dist[q]))  # starving: food first
                g = snap.at(*q).ch
                what = {'%': 'food', '$': 'gold', '[': 'armor', ')': 'a weapon', '!': 'a potion', '?': 'a scroll', '/': 'a wand', '=': 'a ring', '"': 'an amulet', '(': 'a tool'}[g]
                opts['fetch'] = (f"Go look at the item {compass(me, q)} ({what}?)", f"Walk {dist[q]} steps {compass(me, q)} to the '{g}' on the floor and see what it is; food keeps you from fainting, armor lowers AC.", lambda q=q: self.act_go(q))
        packed = sum(bool(FOOD.search(it['text'])) for it in self.inventory)
        if not near and s.get('gold', 0) >= 5 and packed < 3:  # a Jev with 236 gold starved to death: shops sell food
            food = [q for q in snap.find('%') if q in dist and 0 < dist[q] <= 15 and (s.get('dlvl'), q) not in self.run['here'] and lv.corpses.get(q, -1) < 0
                    and sum(cheb(q, o) <= 3 for c in ')[%?/=!("' for o in snap.find(c)) >= 6]
            if food:
                q = min(food, key=dist.get)
                opts['shop_food'] = (f"Go look at the food for sale {compass(me, q)}", f"Walk {dist[q]} steps into the shop to see the '%' item and its price. You have {s.get('gold')} gold and {packed} food items packed.", lambda q=q: self.act_go(q))
        fr = self.frontiers(dist)
        picked = []
        for d, p in fr:
            if all(cheb(p, q) >= 8 for q in picked):
                picked.append(p)
                k = len(picked)
                opts[f'explore_{k}'] = (f"Explore {compass(me, p)} ({d} steps)", f"Walk to the unexplored edge {d} steps away to the {compass(me, p)} and see what is there.", lambda p=p: self.act_explore(p))
            if len(picked) == 3:
                break
        if not fr and not snap.find('>') and s.get('turn', 0) - lv.terrain_turn >= 300:
            # Minetown hid its '>' under a rock pile: 260 turns of explore/search with "no unexplored edges left"
            lv.terrain_turn = s.get('turn', 0)
            lv.stairs |= set(self.terrain_find('>'))
        bad = {q for (dl, q), t0 in self.run.setdefault('bad_down', {}).items() if dl == s.get('dlvl') and s.get('turn', 0) - t0 < 3000}
        downs = [p for p in snap.find('>') + sorted(lv.stairs) if p in dist or p == me]
        # a bad '>' is skipped only when another way down exists: otherwise the level above dead-ends too and Jev cascades up to Dlvl 1 (starved, T7223)
        downs = [p for p in downs if p not in bad] or downs
        too_deep = s.get('dlvl', 1) >= (s.get('xl') or 1) + 2  # pace: Dlvl <= XL+1 (XL+2 still lost most runs on Dlvl 4-5 before T2000)
        ups = [p for p in snap.find('<') if p in dist]
        above = self.run['levels'].get(s.get('dlvl', 1) - 1)
        if too_deep and ups and self.standing_on() != '<' and not (above and sum(above.searched.values()) >= 800) and (dist[ups[0]] <= 2 or not any(m['dist'] <= 1 for m in hostiles)):  # walked for '<' 50 steps off with Mordor orcs and a snake adjacent: 7 tries, 44 -> 0, dead praying (T3746)  # the level above already waited out its pace cap: going back just ping-pongs (4 <-> 5 25 times in 100 turns, T4478)  # XL5 on Dlvl 7 died to a winter wolf; XL+3 was too late
            opts['ascend'] = ('Head back upstairs', f"This level is far too deep for experience level {s.get('xl')}. Walk to the up staircase ({dist[ups[0]]} steps {compass(me, ups[0])}) and climb to Dlvl {s.get('dlvl', 0) - 1}.", lambda p=ups[0]: self.act_descend(p, '<'))
        if len(snap.find('{')) >= 4:  # the Oracle's four fountains: Sokoban's entrance is the second '<' one level down
            self.run['oracle'] = s.get('dlvl')
        soko_hunt = s.get('dlvl') == (self.run.get('oracle') or -9) + 1 and len(snap.find('<')) < 2 and not self.run.get('soko_done') and self.frontiers(dist)
        if soko_hunt or s.get('dlvl', 1) >= (s.get('xl') or 1) + 1 or s.get('hp', 1) < 0.8 * s.get('hpmax', 1):  # rest first; fleeing downward from a fight at this depth is how the pony and giant ant runs ended
            pass
        elif self.standing_on() == '>':
            opts['descend'] = ('Go down the stairs', f"You are on the down staircase to Dlvl {s.get('dlvl', 0) + 1}.", lambda: self.act_keys('>', 'descended'))
        elif downs:
            opts['descend'] = ('Head for the downstairs', f"Walk to the known down staircase ({dist[downs[0]]} steps {compass(me, downs[0])}) and descend to Dlvl {s.get('dlvl', 0) + 1}.", lambda p=downs[0]: self.act_descend(p))
        pick = next((it for it in self.inventory if re.search(r'pick-axe|dwarvish mattock', it['text'])), None)
        if pick and not near and s.get('dlvl', 1) < (s.get('xl') or 1) + 1 and not soko_hunt and self.standing_on() not in ('<', '>', '_', '{'):
            # same pace as the stairs: 'not too_deep' let XL5 dig 6 -> 7 and XL6 7 -> 8, dead to a giant spider (T4825)
            opts['dig_down'] = ('Dig down with the pick-axe', f"Apply {pick['text']} downward to dig a hole to Dlvl {s.get('dlvl', 0) + 1} (takes several turns; skips the rest of this level).", lambda l=pick['letter']: self.act_dig(l))
        # resting at full HP was Jev's favourite way to do nothing (537 of 650 choices in one game); searching has its own option
        if not near and not self.unseen_attacker() and s.get('hp', 1) < 0.85 * s.get('hpmax', 1):  # blind, Jev rested beside an orc and died (T3212)
            opts['rest'] = ('Rest and search 15 turns', 'Stay put for up to 15 turns to regain HP. Interrupted if a monster appears.', lambda: self.act_search(15))
        if not fr and not downs and ups and sum(lv.searched.values()) >= 1000 and not self.soko():
            # a Mines level whose '>' was never found: 6000 turns of searching, living on prayer, fainted (T11246). Go up, try another way down
            opts['dead_end'] = ('Give up on this level and go back up', f"You have searched this level for {sum(lv.searched.values())} turns without finding a way down. Climb to Dlvl {s.get('dlvl', 0) - 1} and look for another down staircase.", lambda p=ups[0]: self.act_dead_end(p))
        hole = min(((h, q) for h in sorted(lv.holes) for q in dist if max(abs(q[0] - h[0]), abs(q[1] - h[1])) == 1), key=lambda t: t[0][0] != t[1][0] and t[0][1] != t[1][1], default=None)  # orthogonal first: no diagonal steps into doorways
        if hole and not fr and not downs and not ups and not self.soko():
            # a kobold dug a hole in the only doorway: refusing it boxed Jev in a stub for 5000 turns, starved (T9952). trap.c: holes drop 1+ levels in this dungeon
            opts['dead_end'] = ('Jump into the hole', f"The only way out is a hole/trap door at {hole[0]}. Step into it and fall to a lower level.", lambda h=hole: self.act_hole(*h))
        if 'dead_end' in opts and not near:
            opts = {k: v for k, v in opts.items() if k in ('dead_end', 'pray') or k.startswith('eat_')}
        if not fr and not downs:
            if not walled: self.run['walled'] = s.get('turn') or 0
            # boxed in by Minetown's peaceful gnomes, meleed the eye at once: frozen, killed by an imp (T7290). Wait them out first.
            long_walled = walled and (s.get('turn') or 0) - self.run.setdefault('walled', s.get('turn') or 0) > 200
            if walled and not long_walled:
                opts['wait_eye'] = ('Search 10 turns and let it drift off', 'A monster you must not melee boxes you in. Floating eyes drift and peacefuls wander off; waiting is safe, hitting it risks long paralysis.', lambda: self.act_search(10))
            molds = [m for m in hostiles if m['pos'] in self.avoid and (long_walled or ('floating eye' not in m['name'] and not (m['ch'] == 'e' and m['fg'] == 'blue')))
                     and ('gas spore' not in m['name'] or s.get('hp', 0) >= 30)]  # its 4d6 blast is survivable at 30+ HP
            if any(not m['passive'] for m in hostiles) or s.get('hp', 0) < 0.9 * s.get('hpmax', 1):  # frozen by an eye with a giant ant in view: dead at T8374
                molds = [m for m in molds if m['ch'] != 'e']
            if molds:
                self.avoid -= {m['pos'] for m in molds}
                d2, _ = self.dijkstra()
                self.avoid |= {m['pos'] for m in molds}
                if any(m['pos'] in d2 for m in molds) and (len(self.frontiers(d2)) > 0 or len(d2) > len(dist) + 5):  # or it walls us in
                    m = min((m for m in molds if m['pos'] in d2), key=lambda m: d2[m['pos']])
                    why = (f"Its explosion does at most 24 damage and you have {s.get('hp')} HP, so you survive it" if 'gas spore' in m['name']
                           else "Last resort: if it survives a hit it may paralyze you for a long time while other monsters attack; killing it in one blow is safe" if m['ch'] == 'e'
                           else "It hurts you passively when you hit it; the fight stops if HP gets low")
                    opts['kill_blocker'] = (f"Kill the {m['name']} blocking the way", f"The {m['name']} {m['where']} blocks the only way out: you are stuck here until it dies. Walk next to it and fight it. {why}.", lambda m=m: self.act_kill_blocker(m['pos']))
                    if m['ch'] == 'e' and any(k.startswith(('throw_', 'zap_')) for k in opts):
                        del opts['kill_blocker']  # throw at it instead: melee paralyses for up to 127 turns
        # stagnant: yellow + red molds plugged both corridors, rats behind them; explore/approach/wait looped 4000 turns at XL2, starved (T5244)
        if s.get('exp') != self.run.get('exp_seen'):
            self.run['exp_seen'], self.run['exp_turn'] = s.get('exp'), s.get('turn') or 0
        if (s.get('turn') or 0) - self.run.get('exp_turn', 0) > 500 and 'kill_blocker' not in opts and hp >= 0.6 * hpmax and not any(not m['passive'] and m['dist'] <= 3 for m in hostiles):
            fs = [m for m in hostiles if m['ch'] == 'F' and m['pos'] in self.avoid and 'lichen' not in m['name']]
            self.avoid -= {m['pos'] for m in fs}
            d2, _ = self.dijkstra()
            self.avoid |= {m['pos'] for m in fs}
            fs = [m for m in fs if m['pos'] in d2]
            if fs:
                m = min(fs, key=lambda m: d2[m['pos']])
                opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('eat')}
                opts['kill_blocker'] = (f"Kill the {m['name']}", f"No experience gained in {(s.get('turn') or 0) - self.run['exp_turn']} turns: the {m['name']} {m['where']} sits in the way. It cannot move or attack; hitting it hurts you a little. The fight stops if HP gets low.", lambda m=m: self.act_kill_blocker(m['pos']))
        if not fr and not downs and not near and sum(lv.searched.values()) >= 300 * (lv.resets + 1):
            # searched a long time for nothing: level memory may be hiding real exits (a starved run had an open doorway in view)
            lv.resets += 1
            lv.blocked.clear(); lv.dead.clear(); lv.near.clear()
            fr = self.frontiers(dist)
            if fr:
                opts['explore_again'] = ('Re-explore this level', f"Searching found nothing, but there are unexplored edges again ({len(fr)} of them, nearest {fr[0][0]} steps {compass(me, fr[0][1])}).", lambda p=fr[0][1]: self.act_explore(p))
        if not fr and not downs and not near and 'kill_blocker' not in opts:  # walled in: searching finds nothing
            spot = self.search_spot(dist)
            if spot:
                opts['search_hidden'] = ('Search for hidden passages', f"No unexplored edges or downstairs are known. Walk {dist[spot]} steps {compass(me, spot)} to a likely spot (dead end or wall) and search there.", lambda: self.act_search_at(spot))
        m = self.soko()
        if m and not self.run.get('soko_done'):
            i = self.run.setdefault('soko_step', {}).get(m[0], 0)
            plan = self.run.setdefault('soko_plan', {}).get(m[0])
            st = (plan[0] if plan else None) if plan is not None else sokoban.step(m, i)
            n = i + len(plan) if plan is not None else len(sokoban.solutions()[m[0]]['pushes'])
            if st:
                b, k = st
                behind = (b[0] - DIRS[k][0], b[1] - DIRS[k][1])
                if snap.at(*b).ch == '0' and (behind in dist or behind == me) and self.run.get('soko_stuck', {}).get((m[0], i)) != -99:
                    opts['soko_push'] = (f"Sokoban: push the boulder {compass(me, b)} one square {DIR_NAME[k]} (push {i + 1} of {n})",
                                         f"Next move of a known solution to this Sokoban level. Filling every pit or hole opens the way up; each level has food, a ring and a wand, and the top one a bag of holding or amulet of reflection.",
                                         lambda m=m, b=b, behind=behind, k=k: self.act_soko(m, b, behind, k))
                elif snap.at(*b).ch != '0' and not snap.is_monster(*b) or \
                        s.get('turn', 0) - self.run.setdefault('soko_stuck', {}).setdefault((m[0], i), s.get('turn', 0)) > 30:
                    # off-plan (a boulder rolled, or the plan walled us into a pocket: starved 30000 turns there): solve from the screen
                    tries = self.run.setdefault('soko_replans', {})
                    tries[m[0]] = tries.get(m[0], 0) + 1
                    new = sokoban.replan(m, me, set(snap.find('0')), set(snap.find('^'))) if tries[m[0]] <= 3 else None
                    self.log(f"sokoban {m[0]}: push {i + 1} off-plan; replan -> {len(new) if new else 'no solution, leaving'}", 'warn')
                    if new:
                        self.run['soko_plan'][m[0]] = new
                        self.run.setdefault('soko_stuck', {}).pop((m[0], i), None)
                    else:
                        self.run['soko_done'] = True
                if 'soko_push' in opts and not near and not (hostiles and hp < 0.6 * hpmax):  # forced push off Elbereth at 26/64 with fled orcs in view: 14 HP next turn, dead (T5149)
                    opts = {k2: v for k2, v in opts.items() if k2 == 'soko_push' or k2 == 'pray' or k2.startswith('eat_')}
                opts.pop('descend', None)  # a gnome king nearby lifted the filter and Jev walked out with 8 of 41 pushes left
            elif m[0].startswith('soko1'):
                self.run['soko_done'] = True  # top level solved: the zoo and prize are ordinary exploring from here
            elif ups and not near and not self.run.get('soko_done'):  # gave up on the level above: soko_up/descend ping-ponged 1400 times, 13000 turns (T20758)
                opts = {k2: v for k2, v in opts.items() if k2 == 'pray' or k2.startswith('eat_')}
                opts['soko_up'] = ('Sokoban: climb to the next puzzle level', 'This level is solved. The next Sokoban level is up these stairs.', lambda p=ups[0]: self.act_descend(p, '<'))
        elif not m and len(ups) >= 2 and not self.run.get('soko_done') and not near and hp >= 0.7 * hpmax:
            p = max(ups, key=lambda u: cheb(u, lv.arrival or me))
            opts = {k2: v for k2, v in opts.items() if k2 == 'pray' or k2.startswith('eat_')}
            opts['enter_sokoban'] = ('Go up into Sokoban', f"This level has a second up staircase ({dist[p]} steps {compass(me, p)}): it leads to Sokoban, four puzzle levels with a known solution, safe food, rings, wands and a bag of holding or amulet of reflection at the top.", lambda p=p: self.act_descend(p, '<'))
        if self.run.get('nymph_lvl') == s.get('dlvl') and downs and s.get('dlvl', 1) <= (s.get('xl') or 1) and not near and not m:
            # a nymph teleports back for more: one wood nymph took shield, spear, bag, ration and egg over 500 turns
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('eat_')}
            opts['leave_nymph'] = ('Leave this level (a nymph lives here)', f"A nymph on this level keeps coming back to steal your things. Walk to the down staircase ({dist.get(downs[0], 0)} steps) and descend.", lambda p=downs[0]: self.act_descend(p))
        if were_throw in opts and not any(m['dist'] <= 1 for m in hostiles):
            opts = {k: v for k, v in opts.items() if k.startswith(('throw_', 'zap_')) or k in ('elbereth', 'pray') or k.startswith('quaff_')}
        if nymph_throw in opts and not any(m['dist'] <= 1 for m in hostiles):  # forced to throw at a nymph, a fire ant ate Jev at 10 HP
            opts = {k: v for k, v in opts.items() if k in (nymph_throw, 'pray') or k.startswith('eat_')}
        if 'ascend' in opts and not any(m['dist'] <= 1 for m in hostiles) and s.get('hunger') not in ('Hungry', 'Weak', 'Fainting'):  # hungry descents were forced back up: 33 ascends/14 descends while starving (T3603)  # offered only, Jev rarely took it: 25 of 60 deaths were 2+ levels past XL
            opts = {k: v for k, v in opts.items() if k in ('ascend', 'pray') or k.startswith(('eat_', 'quaff_'))}
        # stall guard: an option picked 3 times in a row without the game clock moving is not working
        streak = []
        for h in reversed(self.history):
            if h['turn'] != s.get('turn'):
                break
            streak.append(h['choice'])
        if len(streak) >= 3 and len(set(streak[:3])) == 1:
            opts.pop(streak[0], None)
        if s.get('hunger') in ('Weak', 'Fainting') and not any(m['dist'] <= 3 and not m['passive'] for m in hostiles):  # dist<=1 forced 'fetch' food off Elbereth past a rothe and elf zombie 2 steps away: 35 -> 0 (T4576)
            # sat 69 turns on Elbereth Weak -> Fainting with food in view, dead (T2958); wiki: Weak is major trouble, eat or pray
            food = {k: v for k, v in opts.items() if k == 'pray' or k.startswith(('eat_', 'goto_corpse')) or k == 'fetch' and '(food?)' in v[0]}
            opts = food or opts
        if (s.get('turn') or 0) - self.run.get('held', -99) <= 1:  # held: moving escapes 1 in 40 (hack.c); a rope golem choked Jev through 3 retreats (T5125). Wiki: Elbereth works while grabbed
            opts = {k: v for k, v in opts.items() if k in ('elbereth', 'pray') or k.startswith(('attack_', 'quaff_'))} or opts
        if any(m['dist'] <= 1 and not m['passive'] for m in hostiles) and any(k.startswith('attack_') for k in opts):  # explored away from 5 adjacent rats at 21/29: dead (T1354)
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore_', 'search', 'throw_', 'pickup_', 'fetch', 'door_'))}  # picked up loot 3 times with Woodland-elves hitting (T6490); threw daggers at a far orc-captain with a giant spider adjacent: 19 -> 8 HP, dead (T4825); walked for a locked door 3 times inside a wererat's rat swarm: 17 -> 0 (T5245)
        if self.history and 'blocked' in self.history[-1]['outcome'] and any(m['dist'] <= 1 for m in hostiles) and len(opts) > 1:
            opts.pop(self.history[-1]['choice'], None)  # hill orcs blocked the stairs path: 5 'ascend' bumps at 80/80 HP without a swing, dead (T6782)
        last = self.history[-5:]  # blocked walks cost a turn each, so the clock-frozen check misses them: 3500 turns bumping a shopkeeper past a floating eye
        if len(last) == 5 and len({h['choice'] for h in last}) == 1 and all('blocked' in h['outcome'] for h in last) and len(opts) > 1:
            opts.pop(last[0]['choice'], None)
        if len(streak) >= 4:  # several tries, clock frozen: everything tried this turn is failing
            for c in set(streak):
                if len(opts) > 1:
                    opts.pop(c, None)
        if downs:  # a locked door can be a shop closed for inventory whose sign got scuffed: kicked one in, Mr. Kipawa killed Jev (runs before the empty guards: filtering after them left no options, 1100 turns searched)
            opts = {k: v for k, v in opts.items() if not (k.startswith('kick_') or 'locked door' in v[0])}
        if not opts and downs and s.get('dlvl', 1) >= (s.get('xl') or 1) + 1 and s.get('hunger') not in ('Hungry', 'Weak', 'Fainting') \
                and (sum(lv.searched.values()) < 400 or s.get('dlvl', 1) + 1 >= (s.get('xl') or 1) + 2 and sum(lv.searched.values()) < 800):  # 1500: ~95 pace rests = 1900 of 3200 turns waiting for XP, fainted to a dog (T3853); hunger was 5 of 12 deaths  # uncapped, an XL2 rested 91% of 8000 turns on Dlvl 3, living on prayers until one angered Tyr (T8071)  # 'anyway' to XL+2 just ping-pongs with the forced ascend (Green-elves, T5351)
            # Hungry is ~100 turns from Weak, where prayer takes over: Hungry 'anyway' took XL6 to Dlvl 8, ogre + giant spider (T5817)
            # 'anyway' took Jev past the pace limit 165 times in 60 games (median death XL5 on Dlvl 7): wait here for monsters and HP first
            opts['rest'] = ('Rest and search 20 turns', f"This level is cleared, but Dlvl {s.get('dlvl', 0) + 1} is too deep for experience level {s.get('xl')}. Wait here: wandering monsters bring experience, and HP recovers.", lambda: self.act_search(20))
        if (s.get('turn') or 0) - self.run.get('fled_up', -99) < 50:  # fled a warg pack upstairs, walked straight back down into it (T5161)
            opts = {k: v for k, v in opts.items() if k not in ('descend', 'dig_down')}
            downs = []
        if self.soko() and not self.run.get('soko_done'):  # a fresh replan offers no push that decision: 'anyway' walked out 3 times and burned every replan (T6359)
            downs = []
        if not opts and downs:  # the pace gate is advice; idle-searching a cleared level only burns food (one run searched 400+ turns in a corridor)
            opts['descend'] = ('Take the downstairs anyway', f"Nothing else is reachable on this level. Walk to the down staircase ({dist.get(downs[0], 0)} steps) and descend to Dlvl {s.get('dlvl', 0) + 1}.", lambda p=downs[0]: self.act_descend(p))
        if not opts:
            # nothing to do usually means level memory has walled us in (once for 7800 turns): forget it and look again
            lv.blocked.clear(); lv.dead.clear(); lv.near.clear()
            lv.resets += 1
            opts['wait'] = ('Wait one turn', 'Nothing else is possible right now; search in place for one turn.', lambda: self.act_keys('ms', 'waited'))
        # Jev never picked "Wear" over exploring (194 offers after a monkey stole the shield) and has no wield option at all
        # never a known-cursed one (welded: a cursed orcish dagger over an uncursed dagger, killed by an ogre T4539); known-safe first at equal rank
        weapon = min((it for it in self.inventory if WEAPON.search(it['text']) and not re.search(r'(?<!un)cursed', it['text']) and it['text'] not in self.run.setdefault('unwieldable', set())),
                     key=lambda it: (WEAPON_RANK.index(WEAPON.search(it['text'])[1]), not re.search(r'uncursed|blessed', it['text'])), default=None)
        if weapon and self.inventory and not any('weapon in' in it['text'] for it in self.inventory):
            opts = {f"wield_{weapon['letter']}": (f"Wield {weapon['text']}", 'You are fighting bare-handed.', lambda l=weapon['letter']: self.act_wield(l))}
        elif not near and (art := next((it for it in self.inventory if 'named' in it['text'] and WEAPON.search(it['text']) and 'weapon in' not in it['text'] and it['text'] not in self.run['unwieldable']), None)):
            opts = {f"wield_{art['letter']}": (f"Wield {art['text']}", 'An artifact weapon beats anything else you carry.', lambda l=art['letter']: self.act_wield(l))}
        elif not near and any(k.startswith('wear_') for k in opts):
            opts = {k: v for k, v in opts.items() if k.startswith('wear_')}
        if not near and 'rest' in opts and s.get('hp', 1) < 0.5 * s.get('hpmax', 1):  # explored on at 11/65 HP into a giant beetle
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'door', 'descend', 'approach', 'kick', 'goto', 'search'))}
        if (s.get('title') or '').startswith('Were'):  # animal form: armor falls off, paws can't wear or carry much
            opts = {k: v for k, v in opts.items() if not k.startswith(('pickup_', 'wear_', 'fetch'))}
        if 'Overloaded' in s.get('conditions', []):  # a wererat Jev tried to walk 291 times under a Valkyrie's pack
            opts = {k: v for k, v in opts.items() if k == 'pray'}
            for it in self.inventory:
                if not re.search(r'weapon in|being worn|gold piece', it['text']):
                    opts[f"drop_{it['letter']}"] = (f"Drop {it['text']}", 'You are Overloaded and cannot move at all. Drop heavy things (armor, weapons, rations, tools) first.', lambda l=it['letter']: self.act_keys('d' + l, 'dropped it'))
        if not near and any(k.startswith('sell_') for k in opts):  # Jev chose "explore" into Chicoutimi 3000 times instead
            opts = {k: v for k, v in opts.items() if k.startswith('sell_')}
        if set(s.get('conditions', [])) & {'Conf', 'Cnf', 'Stun', 'Stn'} and (not near or any(m['peaceful'] and m['dist'] <= 1 for m in mons)):  # hack.c: Stunned always, Confusion 1 in 5 confdir()s the move or attack: a stunned swing at a mimic hit Izchak, dead (T2680)  # a confused bump into a shopkeeper attacks him
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_')} | {'rest': ('Wait until you are steady', 'You are confused or stunned: moves go in random directions and can attack peacefuls. Nothing hostile is near, so wait it out.', lambda: self.act_keys('5s', 'waited'))}
        if self.run.get('engulfed'):  # a flag: 'laden with moisture' spam pushed 'engulfs you' out of a 3-message window, Jev searched inside a fog cloud for 20 turns (T5756)
            # inside a vortex (shown as Blind) Jev chose 'wait until you can see' twice: 51 -> 13 HP, dead (T8226). Any hit lands on the engulfer.
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_')} | {'attack_k': ('Attack the monster engulfing you', 'You are engulfed: every attack hits the engulfer, and killing it or hurting it enough frees you. Waiting only lets it digest or burn you.', lambda: self.act_fight('k'))}
        elif 'Blind' in s.get('conditions', []):  # a blind step into an unseen watchman angered the whole Minetown watch
            fight = {k: v for k, v in opts.items() if k in ('pray', 'elbereth') or k.startswith(('quaff_', 'attack_', 'eat', 'wield_'))}  # weaponless, opts was just 'wield': this dropped it and a blind Jev waited while a dog bit 37 -> 0 (T4631)  # blind engraving still scares: invisible quasits drained a blind Jev who could only swing
            # 'You feel an unseen monster' is just sensing: swung at it blind in Aklavik's store, and she zapped Jev dead (T3012)
            if shop and not any(re.search(r"\bIt (hits|bites|touches|stings|butts|kicks)", m) for m in self.run['recent'][-2:]):  # blind swings at the unseen shopkeeper angered Ms. Tipor, twice-dead to her wand
                fight = {k: v for k, v in fight.items() if not k.startswith('attack_')}
            # resting while unseen things bit a blind Jev from 54 to 4 HP (twice) is worse than swinging back
            opts = fight if any(k.startswith(('attack_', 'wield_')) for k in fight) else fight | {'rest': ('Wait until you can see', 'You are blind: walking bumps into unseen monsters and attacks them, peaceful or not. Wait for your sight to return.', lambda: self.act_keys('5s', 'waited'))}
        # a pack at any HP: left a working Elbereth at 40/44 to throw at bugbears and a goblin gang, dead 4 turns later
        # Weak is only nutrition 1-50 (eat.c): 23 turns camping on Elbereth there fainted Jev into a kitten's jaws (T4709)
        if self.engraved_here() and s.get('hunger') not in ('Weak', 'Fainting') and (pack or s.get('hp', 1) < 0.75 * s.get('hpmax', 1)) and any(m['ch'] != '@' and m['dist'] <= 7 for m in hostiles) \
                and not shot \
                and not any((m['ch'] == '@' or 'minotaur' in m['name']) and m['dist'] <= 7 for m in hostiles):  # a bugbear threw daggers at a waiting Jev (Elbereth only stops melee): 13 -> 0 (T2350)  # a Woodland-elf (ignores Elbereth) walked up to a waiting Jev: 36 -> 0 (T7182)
            # stepping off a working Elbereth at a third HP with rothes/apes in view ended two runs in one hour
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith(('quaff_', 'eat'))} | {'wait': ('Stay on Elbereth one turn', 'You are hurt and monsters are in view; Elbereth keeps most of them off while you heal.', self.act_wait_elbereth)}
        # a safe prayer fully heals; Jev chose Elbereth over it at 1 HP and died. 500+ turns on, rnz(350) - elapsed < 200 most of the time:
        # Jev threw darts at 8 HP instead of a 700-turn gamble and died (T5087)
        if LOW_HP(s) and 'pray' in opts:  # the gamble (100+ turns) is ~.5-.87: Jev engraved at 1 HP 478 turns after praying and died (T4535)
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_') and 'healing' in v[0]}  # chose an unknown black potion over a ~.7 prayer at 8/43: dead (T3559)
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
        if 'Blind' in self.snap.status.get('conditions', []):
            return False  # cannot read it back, and a rothe pack chewed a blind Jev from 48 to 0 HP 'on Elbereth'
        return (self.snap.status.get('dlvl'), self.snap.me) in self.run.setdefault('elbereth', set())

    # ---------- motors ----------
    def after_move(self, before):
        """Remember the glyph we stepped onto and what lies here."""
        snap = self.observe()
        key = (snap.status.get('dlvl'), snap.me)
        if snap.me and snap.me != before.me and before.at(*snap.me):
            g = before.at(*snap.me).ch
            if g in '<>_{':
                self.run['under'][key] = g
            elif before.is_door(*snap.me):
                self.run['under'][key] = 'door'
            if g in OBJECT_CHARS or g in '0_':
                self.run['here'][key] = self.look_here()
            else:
                self.run['here'].pop(key, None)
        return snap

    def act_swap(self, worn, it):  # 5 turns each way for metal suits (objects.h delay)
        self.act_keys('T' + worn['letter'], '')
        self.read_inventory()
        if any(i['letter'] == worn['letter'] and 'being worn' in i['text'] for i in self.inventory):
            self.run['unwearable'][it['text']] = -99  # cursed suit stays on: never offer this swap again
            return 'could not take it off: ' + (self.run['recent'][-1] if self.run['recent'] else '')
        r = self.act_wear(it)
        if r == 'wore armor':
            self.act_keys('d' + worn['letter'], '')
            self.read_inventory()
        return r

    def act_wear(self, it):
        self.act_keys('W' + it['letter'], '')
        self.read_inventory()
        now = next((i['text'] for i in self.inventory if i['letter'] == it['letter']), '')
        if 'being worn' in now:
            return 'wore armor'
        self.run['unwearable'][it['text']] = self.snap.status.get('ac') or 0  # wrong slot taken, two-handed weapon, too big...: stop offering it
        return 'could not wear it: ' + (self.run['recent'][-1] if self.run['recent'] else '')

    def act_pay(self):
        self.t.send('p')
        time.sleep(0.5)
        if any('Pay for which' in l for l in self.t.lines()):  # used-up items (eaten shop food) come as a menu; settle() would Esc it
            self.t.send('.\r')
            time.sleep(0.5)
        raw = ' | '.join(l.strip() for l in self.t.lines()[:3] if l.strip())
        self.observe()
        return 'paid: ' + raw

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
        n_seen = len(self.hostile_glyphs())
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
            self.refused_trap = False
            nx, ny = me[0] + DIRS[d][0], me[1] + DIRS[d][1]
            # a plain step into a monster attacks it (a floating eye drifted onto the stair path and froze Jev); pets still get swapped
            self.t.send(('m' if self.snap.is_monster(nx, ny) and not self.snap.at(nx, ny).reverse else '') + d)
            snap = self.after_move(before)
            if self.refused_trap:
                self.level().traps.add((me[0] + DIRS[d][0], me[1] + DIRS[d][1]))
                if self.refused_trap in ('trap door', 'hole'):
                    self.level().holes.add((me[0] + DIRS[d][0], me[1] + DIRS[d][1]))
                return f'stopped after {taken} steps: a known trap door or teleporter lies on the path'
            taken += 1
            news = [m['text'] for m in self.messages[nmsg:]]
            if any('locked' in m for m in news):
                door = (me[0] + DIRS[d][0], me[1] + DIRS[d][1])
                self.level().locked.add(door)
                self.level().blocked.add(door)
                return 'found a locked door'
            if any('diagonally' in m for m in news):  # we are (or it is) in a doorway we did not see
                self.run['under'][(snap.status.get('dlvl'), me)] = 'door'
                continue
            if snap.me == me and not any('door opens' in m or 'open' in m for m in news):
                step = (me[0] + DIRS[d][0], me[1] + DIRS[d][1])
                if before.is_door(*step) and before.at(*step).ch == '+':
                    self.level().locked.add(step)  # locked, stuck or resisting: kicking is the way through
                if not snap.is_monster(*step) and not before.is_monster(*step) and not any('Pardon me' in m for m in news) and (before.at(*step).ch not in '.#' or any(m.startswith("It's ") for m in news)):  # hack.c test_move: "It's a wall." only for real rock, even if memory shows '.' (bumped one 30+ times, T7444)  # a shopkeeper on the doorway walled Jev into a shop for 2700 turns  # floor was only ever blocked by a peaceful in the way
                    self.level().blocked.add(step)
                return f'blocked after {taken} steps' + (f": {news[-1]}" if news else '')
            if snap.status.get('hp', 0) < hp0:
                return f'took damage after {taken} steps'
            # monsters move, so compare counts rather than positions
            if len(self.hostile_glyphs()) > n_seen and any(cheb(p, snap.me) <= 7 for p in self.hostile_glyphs()):
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

    def terrain_find(self, ch):
        """#terrain redraws the remembered map without objects or monsters: stairs under a boulder or item pile show up."""
        self.t.send('#terrain\r'); self.t.pump(1.0)
        if 'View which' in '\n'.join(self.t.lines()):
            self.t.send('\r'); self.t.pump(1.0)  # a: known map without monsters, objects and traps
        lines = self.t.lines()
        found = [(x, y) for y in range(MAP_TOP, MAP_BOT + 1) for x, c in enumerate(lines[y]) if c == ch]
        self.t.send('\x1b\x1b\x1b')
        self.settle()
        self.observe()
        self.log(f'#terrain {ch}: {found}')
        return found

    def act_dead_end(self, p):
        dl = self.snap.status.get('dlvl')
        r = self.act_descend(p, '<')
        if self.snap.status.get('dlvl') != dl:
            self.run['levels'].pop(dl, None)  # forget it: another branch at this depth must start fresh
            self.run['bad_down'][(self.snap.status.get('dlvl'), self.snap.me)] = self.snap.status.get('turn') or 0
        return r

    def act_hole(self, h, q):
        r = self.act_go(q)
        if self.snap.me != q:
            return 'heading for the hole: ' + r
        dl = self.snap.status.get('dlvl')
        k = next(k for k, v in DIRS.items() if (q[0] + v[0], q[1] + v[1]) == h)
        self.jump_hole = True
        try:
            self.act_keys(k, '')
        finally:
            self.jump_hole = False
        return f'jumped into the hole (Dlvl {dl} -> {self.snap.status.get("dlvl")})'

    def act_descend(self, p, key='>'):
        r = self.act_go(p)
        if self.snap.me == p:
            dl = self.snap.status.get('dlvl')
            self.act_keys(key, '')
            return f'walked to the stairs and took them (Dlvl {dl} -> {self.snap.status.get("dlvl")})'
        return 'heading for the stairs: ' + r

    def act_soko(self, m, b, behind, k):
        r = self.act_go(behind)
        if self.snap.me != behind:
            return 'sokoban: ' + r
        nmsg = len(self.messages)
        self.act_keys(k, '')
        # rolling-boulder trap: the roll animates past the pump's idle gap, and its message can land after we look, so always settle first
        time.sleep(0.5); self.t.pump(1.0); self.observe()
        news = ' | '.join(x['text'] for x in self.messages[nmsg:])
        if self.snap.me == b or 'roll' in news or self.snap.at(*b).ch != '0':  # we stepped into its square, or it left it (fell in / rolled away)
            self.run['soko_step'][m[0]] = self.run['soko_step'].get(m[0], 0) + 1
            if self.run.get('soko_plan', {}).get(m[0]):
                self.run['soko_plan'][m[0]].pop(0)
            return f"pushed the boulder {DIR_NAME[k]}" + (f": {news[:100]}" if news else '')
        if 'monster behind' in news or 'perhaps that' in news:
            self.act_keys('s', '')  # let it move off: retrying in the same turn just tripped the stall guard
        elif 'in vain' in news:  # something unseen behind it: pushed 'in vain' 200+ turns (soko3-1 T3610); force a replan now
            self.run.setdefault('soko_stuck', {})[(m[0], self.run['soko_step'].get(m[0], 0))] = -99
        return 'push failed' + (f": {news[:120]}" if news else '')

    def retreat_dir(self, hostiles):
        me, snap = self.snap.me, self.snap
        best = None
        for d, (dx, dy) in DIRS.items():
            q = (me[0] + dx, me[1] + dy)
            if not snap.walkable(*q) or snap.is_monster(*q) or snap.at(*q).ch in '^0' or (dx and dy and not (snap.diag_ok(me, q) and (snap.walkable(me[0] + dx, me[1]) or snap.walkable(me[0], me[1] + dy)))):
                continue  # hack.c test_move: a squeeze between two walls fails over 600 weight; a retreat that didn't move at 21/71 HP cost the last 17 HP (T4507)
            score = min(cheb(q, m['pos']) for m in hostiles)
            if best is None or score > best[0]:
                best = (score, d)
        # a step that gains no distance just trades squares: ping-ponged west/east under a Woodland-elf's arrows, dead (T4388)
        return best and best[0] > min(cheb(me, m['pos']) for m in hostiles) and best[1]

    def act_retreat(self, hostiles):
        me, d = self.snap.me, self.retreat_dir(hostiles)
        if not d:
            return 'nowhere to retreat'
        self.act_keys(d, '')
        return f'retreated {DIR_NAME[d]}' if self.snap.me != me else 'tried to retreat but did not move'

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
        if not self.elbereth_ok():
            if 'written' not in self.last_read:  # 5.0 engraving is an occupation: a fast attacker interrupts it before any letter lands
                self.run['engrave_interrupted'] = self.snap.status.get('turn') or 0
                return 'nothing got written: the attack interrupted the engraving'
            self.run['engrave_interrupted'] = self.snap.status.get('turn') or 0  # hits scuff dust too: 3 garbled tries in a row fed a tengu 30 HP
            return 'engraving came out garbled; not protected'
        return 'engraved Elbereth'

    def flee_up(self, act):
        self.run['fled_up'] = self.snap.status.get('turn') or 0
        return act()

    def act_wait_elbereth(self):
        if not self.elbereth_ok():
            return 'Elbereth is gone'
        hp = self.snap.status.get('hp', 0)
        self.act_keys('ms', '')
        if self.snap.status.get('hp', 0) < hp:
            self.run['elbereth'].discard((self.snap.status.get('dlvl'), self.snap.me))
            self.run['engrave_interrupted'] = self.snap.status.get('turn') or 0  # cornered monsters can't flee and hit anyway: re-engraving 3 times fed a swarm (T5315)
            return 'got hit while standing on Elbereth: it is not protecting you here'
        return 'waited on Elbereth'

    def elbereth_ok(self):
        """Read the square (free action): dust Elbereths garble ~27% of the time and scuff as we fight."""
        nmsg = len(self.messages)
        self.t.send(':')
        raw = []
        for _ in range(6):  # "There is a doorway here.  Something is written...--More--" hides the read line on the next screen
            lines = self.t.lines()
            raw += [l.rstrip() for l in lines[:3]]
            if not re.search(r'--More--|\(end\)|Things that are here', '\n'.join(lines)):
                break
            self.t.send('\r')
        self.observe()
        read = self.last_read = ' '.join(raw + [m['text'] for m in self.messages[nmsg:]])  # messages dedupe a repeat of the last read
        key = (self.snap.status.get('dlvl'), self.snap.me)
        if not re.search(r'You read: "Elbereth"', read, re.I):  # engraving is an interruptible occupation in 5.0: silence means nothing got written
            self.run['elbereth'].discard(key)
            self.log(f'elbereth read-back: {read[:120]!r} raw={raw!r}', 'warn')
            return False
        self.run['elbereth'].add(key)
        return True

    def act_pray(self):
        nmsg = len(self.messages)
        self.t.send('#pray\r')
        self.observe()
        self.run['prayed_turn'] = self.snap.status.get('turn')
        with open(os.path.join(ROOT, 'runs', 'prayer.json'), 'w') as f:
            json.dump({'prayed_turn': self.run['prayed_turn']}, f)
        return 'prayed: ' + ' '.join(m['text'] for m in self.messages[nmsg:])[:200]  # log success vs "You feel that Tyr is displeased"

    def act_eat(self, letter):
        nmsg = len(self.messages)
        text = next((it['text'] for it in self.inventory if it['letter'] == letter), letter)
        self.t.send('e')
        if 'eat it?' in self.t.lines()[0] or 'eat one?' in self.t.lines()[0]:
            self.t.send('n')
        if 'What do you want to eat' in self.t.lines()[0]:
            self.t.send(letter)
        for _ in range(4):  # "It is not so easy to open this tin.--More--" can come first
            top = self.t.lines()[0]
            if '--More--' not in top:
                break
            self.t.send('\r')
        if 'Eat it?' in top:  # an opened tin names its contents: "It smells like cockatrice. Eat it?"
            self.t.send('n' if any(n in top for n in NEVER_EAT) else 'y')
        self.observe()
        self.read_inventory()
        if any("don't have anything to eat" in m['text'] or 'cannot eat' in m['text'] for m in self.messages[nmsg:]):
            self.run.setdefault('inedible', set()).add(text)
            return f'could not eat {text}'
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

    def act_kill_blocker(self, pos):
        self.avoid.discard(pos)
        r = self.act_go(pos, adjacent_ok=True)
        me = self.snap.me
        if not me or cheb(me, pos) != 1:
            return 'going to the blocker: ' + r
        d = DIR_OF[(pos[0] - me[0], pos[1] - me[1])]
        ch = self.snap.at(*pos).ch
        for i in range(10):
            g = self.snap.at(*pos)
            if not g or g.ch != ch or self.snap.status.get('hp', 0) < 0.5 * self.snap.status.get('hpmax', 1):
                break
            self.act_fight(d)
        return 'killed the blocker' if (g := self.snap.at(*pos)) is None or g.ch != ch else f'fought the blocker {i + 1} times; it still stands'

    def clear_line(self, a, b):
        """Nothing solid or alive between a and b (exclusive) on a straight line."""
        sx, sy = (b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1])
        p = (a[0] + sx, a[1] + sy)
        while p != b:
            g = self.snap.at(*p)
            if g is None or g.ch in '|-+ 0#' and not (g.ch == '#' and g.fg not in ('green', 'cyan')) or self.snap.is_monster(*p):
                return False
            p = (p[0] + sx, p[1] + sy)
        for k in range(1, 10):  # a miss flies on: a dagger thrown at an 'i' hit a watchman behind it, and the watch killed Jev (T3629)
            g = self.snap.at(b[0] + sx * k, b[1] + sy * k)
            if g is None or g.ch in '|-+ 0':
                break
            if g.ch == '@':
                return False
        return True

    def act_throw(self, letter, d, key='t'):
        self.run['elbereth'].discard((self.snap.status.get('dlvl'), self.snap.me))  # firing from Elbereth erases it
        self.t.send(key)
        if re.search(r'throw|zap', self.t.lines()[0].lower()):
            self.t.send(letter)
        if 'direction' in self.t.lines()[0].lower():
            self.t.send(d)
        else:
            self.t.send('\x1b')
        self.observe()
        self.read_inventory()
        return f"{'zapped' if key == 'z' else 'threw'} item {letter} {DIR_NAME[d]}"

    def act_goto_corpse(self, p):
        r = self.act_go(p)
        if self.snap.me != p:
            return 'going to the corpse: ' + r
        if not any('corpse' in i and not any(n in i for n in NEVER_EAT) for i in self.here_items()):
            self.level().corpses.pop(p, None)  # a bat corpse was re-offered 3 times
            return 'no edible corpse there'
        return self.act_eat_corpse()

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
        if any('trouble lifting' in l or 'can barely lift' in l for l in self.t.lines()[:2]):  # 'Continue?' got escaped: re-picked 2 gems every turn for 100+ turns (T6834)
            self.t.send('n')
            self.run.setdefault('heavy', set()).add(item)
        self.observe()
        key = (self.snap.status.get('dlvl'), self.snap.me)
        self.run['here'][key] = self.look_here()
        self.read_inventory()
        return f'picked up {item}'

    def act_altar(self, q):
        r = self.act_go(q)
        if self.snap.me != q:
            return 'heading for the altar: ' + r
        key = (self.snap.status.get('dlvl'), q)
        self.run['here'][key] = self.look_here()
        return f"the altar is {self.run['altars'].setdefault(key, 'unknown')}"  # blind or garbled: don't revisit forever

    def act_buc(self, unk):
        nmsg = len(self.messages)
        for it in unk:
            self.t.send('d' + it['letter'])
            self.settle()
        self.t.send(',')
        if top_prompt(self.t.lines())[0] == 'menu':
            self.t.send(',\r')  # select everything on the altar
        for _ in range(4):
            top = self.t.lines()[0]
            if re.search(r'Continue\?|lifting', top):
                self.t.send('y')
            elif '--More--' in top:
                self.t.send('\r')
            else:
                break
        self.observe()
        self.read_inventory()
        self.run['buc_done'] |= {it['text'] for it in unk} | {it['text'] for it in self.inventory}
        self.run['here'][(self.snap.status.get('dlvl'), self.snap.me)] = self.look_here()
        return 'BUC-tested: ' + ' '.join(m['text'] for m in self.messages[nmsg:])[:200]

    def act_carry(self, p, t0):
        r = self.act_go(p)
        if self.snap.me != p:
            return 'going to the corpse: ' + r
        self.run['sac_skip'].add((self.snap.status.get('dlvl'), p))
        item = next((i for i in self.here_items() if 'corpse' in i and not any(n in i for n in NEVER_OFFER)), None)
        if not item:
            return 'no corpse worth offering here'
        self.act_pickup(item)
        self.run['carry_turn'] = t0
        return f'picked up {item} for the altar'

    def act_offer(self, letter, q):
        r = self.act_go(q)
        if self.snap.me != q:
            return 'heading for the altar: ' + r
        nmsg = len(self.messages)
        self.t.send('#offer\r')
        for _ in range(6):
            top = self.t.lines()[0]
            if 'sacrifice it?' in top:
                self.t.send('n')  # a floor corpse of unknown age; offer the one we carried
            elif 'want to sacrifice' in top:
                self.t.send(letter)
            elif '--More--' in top:
                self.t.send('\r')
            else:
                break
        self.observe()
        self.read_inventory()
        said = ' '.join(m['text'] for m in self.messages[nmsg:])
        if 'reconciliation' in said:  # pray.c: ublesscnt reached 0, prayer is safe
            self.run['prayed_turn'] = (self.snap.status.get('turn') or 0) - 2000
        if 'gift' in said:  # bestow_artifact: ublesscnt = rnz(300 + 50n); the artifact lands at our feet
            self.run['prayed_turn'] = self.snap.status.get('turn')
            art = next((i for i in self.look_here() if 'named' in i), None)
            if art:
                self.act_pickup(art)
        if not any(it['letter'] == letter and 'corpse' in it['text'] for it in self.inventory):
            self.run.pop('carry_turn', None)
        else:
            self.t.send('d' + letter); self.observe(); self.read_inventory(); self.run.pop('carry_turn', None)
        return 'offered: ' + said[:200]

    def act_wield(self, letter):
        self.t.send('w' + letter)
        self.observe()
        self.read_inventory()
        if any('weapon in' in it['text'] for it in self.inventory):
            return 'wielded it'
        self.run.setdefault('unwieldable', set()).add(next((it['text'] for it in self.inventory if it['letter'] == letter), ''))
        return 'could not wield it'

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
        if door not in self.level().locked:
            self.level().blocked.discard(door)
            self.level().dead.discard(door)
            r = self.act_go(door, steps=1)
            if self.snap.at(*door).ch != '+':
                return 'opened the door'
            if door not in self.level().locked:
                return 'door did not open: ' + r
        if self.level().town:
            self.level().dead.add(door)
            return 'did not kick: shopkeepers and the watch punish broken doors'
        for i in range(6):
            if self.act_kick(d).startswith('did not'):
                return 'did not kick: something is written outside this door (shop sign?)'
            if door not in self.level().locked or self.hostile_glyphs():
                break
        return 'kicked the door open' if door not in self.level().locked else 'kicked the door; still shut'

    def act_kick(self, d):
        # a locked shop has "Closed for inventory" in the dust outside; kicking it in got Jev zapped by the shopkeeper
        nmsg = len(self.messages)
        self.t.send(':')
        raw = ' '.join(l.rstrip() for l in self.t.lines()[:3])
        self.observe()
        # the sign is dust and gets scuffed, so any writing outside a locked door counts
        if self.level().town or re.search(r'written here|for inv', raw + ' '.join(m['text'] for m in self.messages[nmsg:])):
            self.level().town = True
            self.level().dead.add((self.snap.me[0] + DIRS[d][0], self.snap.me[1] + DIRS[d][1]))
            return 'did not kick: a shop is closed behind this door'
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

    def unseen_attacker(self):
        return any(re.search(r"\b(It|ghost) (hits|bites|touches|stings|butts|kicks|misses)|feel an unseen monster", m) for m in self.run['recent'][-2:])

    # ---------- Jev ----------
    def state_text(self, mons):
        s, snap = self.snap.status, self.snap
        lv = self.level()
        inv = '; '.join(f"{i['letter']} - {i['text']}" for i in self.inventory) or 'unknown'
        seen = '; '.join(f"{m['name']}{self.threat(m)} {m['where']}" + (' (pet)' if m['pet'] else ' (peaceful)' if m['peaceful'] else '') for m in mons[:8]) or 'none'
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
            f"Monsters in view: {seen}.{' Something unseen is attacking you (ghost or invisible monster)!' if self.unseen_attacker() else ''}\n"
            f"Items on this square: {', '.join(self.here_items()) or 'none'}. Standing on: {self.standing_on() or 'floor'}.\n"
            f"Inventory: {inv}\n"
            f"Level: downstairs {'known' if snap.find('>') or self.standing_on() == '>' else 'not found yet'}; "
            f"deepest level reached this game {self.run['max_dlvl']}.\n"
            f"Recent game messages: {recent}\n"
            f"Recent decisions:\n{hist}\n\n"
            f"Map around you (@ is you; # corridor, + or orange | - doors, < > stairs, letters are monsters):\n{snap.crop()}\n"
        )

    def follow_guard(self):
        """Vault guard escort, scripted and Jev-free: drop the gold, then stay next to the guard until he has led us out."""
        turn = self.snap.status.get('turn') or 0
        if not any('follow me' in m['text'] and turn - m['turn'] <= 60 for m in self.messages[-20:]):
            return False
        me, lines = self.snap.me, self.snap.lines
        guards = [(x, y) for y in range(MAP_TOP, MAP_BOT + 1) for x, c in enumerate(lines[y])
                  if c == '@' and (x, y) != me and cheb(me, (x, y)) <= 8]
        if not guards:
            return False
        g = min(guards, key=lambda p: cheb(me, p))
        if self.snap.status.get('gold'):
            r = self.act_keys('d$', 'dropped the gold for the guard')
        elif cheb(me, g) <= 1:
            r = self.act_keys('ms', 'waited for the guard')
        else:
            r = 'following the guard: ' + self.act_go(g, steps=1, adjacent_ok=True)
        self.log(f'T{turn} vault guard -> {r}')
        return True

    def decide(self):
        # loop guard: decisions while the game clock stands still burn money (or just spin), whatever the cause
        turn = self.snap.status.get('turn') or 0
        self.frozen = self.frozen + 1 if turn == self.frozen_turn else 0
        self.frozen_turn = turn
        if self.frozen >= 50:
            self.frozen = 0
            raise RuntimeError(f'loop guard: 50 decisions stuck on T{turn}; paused')
        if self.frozen and self.frozen % 15 == 0:
            self.log(f'loop guard: {self.frozen} decisions on T{turn}; Esc, forget walls, step randomly, search', 'warn')
            lv = self.level()
            lv.blocked.clear(); lv.dead.clear(); lv.near.clear()
            self.t.send('\x1b\x1b\x1b\x12' + random.choice('hjklyubn') + '3s')
            self.settle()
            return
        if self.follow_guard():
            return
        t0 = time.time()
        opts, mons = self.build_options()
        if not opts:  # every option filtered away (e.g. only a locked door left): search, don't crash the Jev call
            dist, _ = self.dijkstra()
            downs = [p for p in self.snap.find('>') if p in dist]
            self.log(f"no options on T{turn}; {'descending' if downs else 'searching'}", 'warn')
            # one run searched 1100 turns on Dlvl 6 with the downstairs in view, then starved
            opts = {'descend': ('Take the downstairs', 'Nothing else to do on this level.', lambda p=downs[0]: self.act_descend(p))} if downs else \
                {'search': ('Search 10 turns', 'Nothing else to do here right now.', lambda: self.act_search(10))}
        state = self.state_text(mons)
        t1 = time.time()
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
                  'danger': dict(type='noul', instructions='Is the Valkyrie in serious danger of dying within the next few turns?'),
                  # jev-doom's "exposure" rubric: a second pick judged on survival alone; danger ran 0.6-0.87 in the turns before recent deaths
                  'safest': dict(type='choice', instructions='Ignoring progress entirely, which action gives the Valkyrie the best chance of still being alive 20 turns from now? You cannot see your other answers.', criteria=criteria)}
            answers, meta = self.jev.ask(state, qs)
            key = answers['action']['choice']
            if (answers['danger'].get('noul') or 0) >= 0.6 and answers['safest']['choice'] != key:
                key = answers['safest']['choice']
                self.log(f"danger {answers['danger']['noul']:.2f}: safest pick {key} over {answers['action']['choice']}", 'info')
            probs, conf = answers['action'].get('probabilities', {}), answers['action'].get('confidence')
        for o in self.decision['options']:
            o['p'] = probs.get(o['id'])
        self.decision.update(pending=False, choice=key, confidence=conf, latency_ms=meta['latency_ms'],
                             danger=(answers.get('danger') or {}).get('noul'))
        self.run['decisions'] += 1
        self.phase = 'acting'
        self.touch()
        label = opts[key][0]
        t2 = time.time()
        try:
            outcome = opts[key][2]() or ''
        except Exception as e:  # a motor tripping over an unexpected screen should not kill the run
            self.log(f'motor {key} failed: {e!r} at {traceback.extract_tb(e.__traceback__)[-1][:3]}', 'error')
            self.t.send('\x1b')
            outcome = f'error: {e}'
        h = dict(id=self.decision['id'], at=now(), turn=s.get('turn') or 0, dlvl=s.get('dlvl') or 0, choice=key, label=label,
                 p=probs.get(key, 1.0), confidence=conf, n_options=len(opts), latency_ms=meta['latency_ms'], outcome=outcome,
                 ms=dict(build=round((t1 - t0) * 1000), act=round((time.time() - t2) * 1000)))
        with self.lock:
            self.history.append(h)
            del self.history[:-200]
        with open(os.path.join(self.run_dir, 'decisions.jsonl'), 'a') as f:
            f.write(json.dumps(dict(h, state=state, criteria=criteria, answers=answers, model=meta.get('model'), screen=self.snap.lines)) + '\n')
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
        m = re.search(r'((?<!is )(?<!are )(?<!was )killed by (?:M[rs]s?\. )?[^.!\n]+?|died of [^.\n]+|[Pp]oisoned by [^.\n]+|[Tt]urned to slime[^.\n]*|starved to death|drowned [^.\n]+|choked [^.\n]+|quit|escaped)\s*(?:$|\s{2}|\n|\.)', blob)
        self.run['death'] = m[1].strip() if m else ('died' if 'You die' in blob else 'game ended')
        try:  # the screen scrape misreads tombstones and other games' high-score lines; the local xlogfile is exact
            x = dict(f.split('=', 1) for f in open(os.path.join(ROOT, 'nethack', 'lib', 'xlogfile')).read().splitlines()[-1].split('\t') if '=' in f)
            if self.mode == 'local' and abs(int(x.get('turns', -1)) - (self.run.get('turns') or 0)) <= 200:  # the last screen we read can lag the death by ~50 turns
                self.run['death'] = x['death'] + (f", {x['while']}" if x.get('while') else '')
        except (OSError, IndexError, KeyError, ValueError):
            pass
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
            if any('welcome back' in l for l in self.snap.lines + [m['text'] for m in self.messages[-5:]]):  # restored save: keep the prayer clock
                try:
                    t = json.load(open(os.path.join(ROOT, 'runs', 'prayer.json')))['prayed_turn']
                    # messages outlive games, so an old 'welcome back' can match: a prayer from the future is another game's
                    self.run['prayed_turn'] = t if t is not None and t <= (self.snap.status.get('turn') or 0) else None
                except (OSError, ValueError, KeyError):
                    pass
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
            if self.fresh and self.mode == 'local':  # else SELF_RECOVER resumes the old game from its level/save files
                for f in glob.glob(os.path.join(ROOT, 'nethack', 'lib', '*Jev.*')) + glob.glob(os.path.join(ROOT, 'nethack', 'lib', 'save', '*')):
                    os.remove(f)
            self.fresh = False
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
