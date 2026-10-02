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
SUIT = {'dragon scale mail': 9, 'crystal plate mail': 7, 'bronze plate mail': 6, 'plate mail': 7, 'splint mail': 6, 'banded mail': 6, 'dwarvish mithril-coat': 6, 'elven mithril-coat': 5,
        'orcish chain mail': 4, 'crude chain mail': 4, 'chain mail': 5, 'scale mail': 4, 'studded leather armor': 3, 'orcish ring mail': 2, 'crude ring mail': 2, 'ring mail': 3,
        'leather armor': 2, 'leather jacket': 1}
# wiki "Wish": AC and reflection first, then life saving, speed and to-hit/damage for a melee Valkyrie
WISHES = ('blessed greased +2 gray dragon scale mail', 'blessed amulet of life saving', 'blessed fixed +2 speed boots', 'blessed fixed +2 gauntlets of power', 'blessed +2 silver dragon scale mail')
suit_ac = lambda t: next((v for k, v in SUIT.items() if k in t), None)
# price identification (wiki "Price identification"; 5.0 shk.c get_cost, objects.h): base prices per class
BASES = {'scroll': (20, 50, 60, 80, 100, 200, 300), 'potion': (20, 50, 100, 150, 200, 250, 300), 'ring': (100, 150, 200, 300)}
APPEAR = re.compile(r'scrolls? labeled ([A-Z][A-Z ]*[A-Z])|\b(dark green|sky blue|brilliant blue|[\w-]+) potions?\b(?! of| called)|\b(tiger eye|black onyx|[\w-]+) rings?\b(?! of| called)')


def appearance(t):
    m = APPEAR.search(t)
    return m and (('scroll', m[1]) if m[1] else ('potion', m[2]) if m[2] else ('ring', m[3]))


def sell_price(base, ch, sur):
    """shk.c get_cost: unidentified items get 4/3 when o_id % 4 == 0, then a charisma factor, rounded."""
    m, d = (4, 3) if sur else (1, 1)
    m, d = (m, d * 2) if ch > 18 else (m * 2, d * 3) if ch == 18 else (m * 3, d * 4) if ch >= 16 else (m * 2, d) if ch <= 5 else (m * 3, d * 2) if ch <= 7 else (m * 4, d * 3) if ch <= 10 else (m, d)
    return (base * m * 10 // d + 5) // 10 if d > 1 else base * m


def price_bases(cls, price, ch):
    return {b for b in BASES[cls] for sur in (0, 1) if sell_price(b, ch, sur) == price}
JUNK = re.compile(r'\b(mail|plate|armor|shield|shoes|boots|cloak|wrapping|helm|helmet|gauntlets|gloves|short sword|long sword|broadsword|scimitar|axe|mace|club|bow|crossbow|pick-axe|morning star|flail|hammer|trident)\b')  # unworn copies: what to drop when Burdened
SLOTS = {'boots': r'boots|shoes', 'helm': r'helm|hat|cap\b', 'cloak': r'cloak|robe|wrapping|apron', 'shield': r'shield', 'gloves': r'gloves|gauntlets', 'body': r'\bmail|plate|armor|coat'}
HUGGERS = re.compile(r'\b(owlbear|python|rope golem|couatl|salamander|kraken|pit fiend|carnivorous ape|guardian naga)\b')  # AT_HUGS in monsters.h
HEAVY = re.compile(r'\b(chest|large box|ice box|boulder|statue|rocks?|iron ball|iron chain|lance|pole sickle|halberd|glaive|partisan|spetum|ranseur|bardiche|voulge|fauchard|guisarme|bill-guisarme|lucern hammer|bec de corbin|two-handed sword|dwarvish mattock)\b')  # carrying these left Jev Burdened
DOMESTIC = {'kitten', 'housecat', 'large cat', 'little dog', 'dog', 'large dog', 'pony', 'horse', 'warhorse'}  # M2_DOMESTIC (monsters.h)
WEAPON_RANK = ['long sword', 'axe', 'broadsword', 'katana', 'scimitar', 'saber', 'short sword', 'spear', 'mace', 'morning star', 'war hammer', 'flail', 'trident', 'dagger', 'knife', 'club']
WEAPON = re.compile(r'\b(' + '|'.join(WEAPON_RANK) + r')s?\b(?! corpse)')
# pray.c: never offer own race (dwarf), a former pet, a co-aligned (white) unicorn; touching a cockatrice bare-handed stones you
NEVER_OFFER = ('cockatrice', 'chickatrice', 'dwarf', 'kitten', 'housecat', 'large cat', 'little dog', 'large dog', 'dog corpse', 'pony', 'horse', 'white unicorn', 'Medusa', 'Death', 'Pestilence', 'Famine', 'were')
UNLOCKER = re.compile(r'\b(skeleton key|key|lock pick|credit card)\b')  # lock.c: opens boxes (and doors, but the watch treats any of them as lock picking)
UNKNOWN_BUC = lambda t: not re.search(r'\b(cursed|uncursed|blessed)\b|being worn|weapon in|gold piece|corpse', t)
MINES_XL = 10  # 33 of 78 deaths were in the Mines, mostly Dlvl 6-8 at avg XL 5.5: below this, Mines only after Sokoban and never past Minetown
POISONOUS = ('killer bee', 'soldier ant', 'giant beetle', 'queen bee', 'homunculus', 'rabid rat', 'giant spider', 'scorpion', 'snake', 'water moccasin', 'pit viper', 'cobra', 'gremlin', 'xan', 'jellyfish', 'salamander', 'guardian naga', 'green dragon')  # monsters.h M1_POIS, eat.c 5.0: 4 in 5 cost rnd(4) Str + rnd(15) HP without poison res (dwarven Valks have none); a homunculus and a giant beetle took Str 17 -> 5 (T6625)
# eat.c 5.0 cpostfx: polymorph (chameleon, doppelganger, genetic engineer), helpless 20-50 turns as gold (mimics), stun 60+ (stalker), speed toggle (quantum mechanic),
# random intrinsic loss (disenchanter), 200 turns hallucination (violet fungus, yellow mold, which is poisonous too)
BAD_EFFECT = ('doppelganger', 'genetic engineer', 'mimic', 'stalker', 'quantum mechanic', 'disenchanter', 'violet fungus', 'yellow mold')
NEVER_EAT = ('cockatrice', 'chickatrice', 'Medusa', 'green slime', 'Rider', 'Death', 'Pestilence', 'Famine', 'zombie', 'mummy', 'dwarf', 'were', 'kobold', 'bat', 'ghoul', 'vampire', 'chameleon', 'dog', 'cat', 'kitten', 'acid blob', 'spotted jelly') + POISONOUS + BAD_EFFECT  # undead corpses are pre-aged: always tainted
# pray.c critically_low_hp: the major-trouble line prayer fixes
LOW_HP = lambda s: s.get('hp', 1) <= 5 or s.get('hp', 1) * (5 if s.get('xl', 1) <= 5 else 6 if s.get('xl', 1) <= 13 else 7 if s.get('xl', 1) <= 21 else 8 if s.get('xl', 1) <= 29 else 9) <= min(s.get('hpmax', 1), 15 * s.get('xl', 1))
STRATEGY = ("You are a dwarven Valkyrie (NetHack 5.0): strong melee, cold resistant, infravision; stealthy from XL 3, fast from XL 7. Gnomes and dwarves (the Mines) are peaceful to you. Survive first. Monsters listed as weaker than you are easy experience: kill them rather than waiting or retreating. Each monster in view shows its AC, attacks and, for the dangerous ones, a 'Fight if ...; avoid if ...' rule: follow it. "
            "Fight weak monsters in melee; do not melee floating eyes (blue 'e') or cockatrices ('c' yellow) bare-handed. Against a group, fight from a corridor or doorway so only one or two reach you. Back off to heal at half HP, not at 1 HP. "
            "Prayer fixes low HP (at or below 1/5 of max at XL 1-5, 1/6 at XL 6-13, or 5 HP) and Weak hunger, but only about once per 1000 turns; "
            "the first prayer is safe after roughly turn 300. Your default against anything you cannot kill at once is to back into a corridor or doorway and fight one at a time; Elbereth is for emergencies only. Elbereth in the dust (fails about 1 time in 4: check it) stops melee from most monsters, "
            "not @ humans or elves (including were-creatures in @ form), minotaurs, shopkeepers or peacefuls, and never wands, arrows or breath: kill a weak monster that zaps or shoots at you instead of waiting it out. If it keeps backing off as you close in (an aklys returns to its thrower), stop chasing it: break line of sight, heal or leave by the stairs. A scared monster with nowhere to flee can still hit you, and attacking, throwing or zapping from it erases it. Elbereth is for healing, not for living on: new monsters keep arriving (about one every 70 turns), so once healed, fight the weakest one and re-engrave when hurt. An invisible attacker: search one turn to mark it (I), then attack that square. "
            "Mumakil (speed 9) hit hardest of anything early: never trade blows, throw things or walk away. Never melee a were in animal form if you can avoid it: its bite gives lycanthropy ('You feel feverish'); pray as soon as it is safe to cure it, and while you are in animal form stay on the current level instead of going down. Kill wererats quickly, before they summon rats; a were-creature (either form) can call more of its kind whenever it attacks, so when mobbed kill it before anything it summoned. A yellow light blinds you for up to 200 turns when it explodes at you, even on Elbereth if it is cornered: put on a towel or blindfold first (the explosion then does nothing), else kill it (killing it is safe) rather than wait beside it. Blind and bitten by something unseen while engraving fails: fight back. Soldier ants (speed 18, poison) kill more players than anything: Elbereth works on them, never let them surround you, and zap or read teleportation to escape when hurt. A monster that is scared but cornered still attacks you on Elbereth: if you are hit there, Elbereth is not protecting you, so pray, quaff or leave. Never rest for long with a fast monster that keeps coming back; find the up stairs. A crowd too big to fight (a magic trap's flash and roar summon monsters right beside you) interrupts engraving: if the up stairs are a few steps away, take them. Elbereth does not make a crowd go away: if more and more monsters gather while you wait, and the up stairs are close, leave by them. In speed boots you are faster than almost everything early: walk away from slow heavy hitters (zombies, mumakil, ogres) to the up stairs instead of standing on Elbereth. Hungry with no food and a food shop near (Minetown often has a delicatessen): sell spare weapons and gems in a general store and buy food before you faint; prayer for hunger can fail if prayed too soon. "
            "Collect gold: a temple priest sells permanent AC for about 400-500 gold per experience level; keep 2000-4000 after that for shops. "
            "Food is scarce (killed monsters no longer drop food): eat fresh corpses of what you kill (not cockatrices, kobolds or old ones), keep packed food for emergencies, never start eating while Satiated, eat when Hungry. "
            "Open chests and large boxes: early ones often hold potions of healing. Explore each level for useful items, "
            "then take the downstairs. A good pace is dungeon level no deeper than experience level + 1 early on. "
            "Wear armor you find if it covers an empty slot. The ultimate goal is to retrieve the Amulet and ascend.")


QUESTIONS = {'action': dict(type='choice', instructions='Choose the single best action for the Valkyrie right now. Staying alive comes first; after that, '
                            'make steady progress (explore, gear up, descend). Use the status, monsters, recent outcomes and the standing order.'),
             'danger': dict(type='noul', instructions='Is the Valkyrie in serious danger of dying within the next few turns?'),
             # jev-doom's "exposure" rubric: a second pick judged on survival alone; danger ran 0.6-0.87 in the turns before recent deaths
             'safest': dict(type='choice', instructions='Ignoring progress entirely, which action gives the Valkyrie the best chance of still being alive 20 turns from now? You cannot see your other answers.')}
questions = lambda criteria: {k: dict(q, criteria=criteria) if q['type'] == 'choice' else q for k, q in QUESTIONS.items()}

def runs_home(name):  # each player name (one per engine running side by side) keeps its own runs.json, prayer clock and ledger
    return os.path.join(ROOT, 'runs') if name == 'Jev' else os.path.join(ROOT, 'runs', name)

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
        self.town = False      # a peaceful @ lives here (Izchak killed a run over a kicked shop door; the cash-register chime means a shopkeeper: a wiped "Closed for inventory" sign let Jev kick in Kinojevis' door, zapped dead T972)
        self.notes = set()     # user: annotate levels (vault, altar, stash): #annotate shows them in the ^O overview
        self.noted = ''
        self.arrival = None    # where we first stood here: the other '<' on the Oracle+1 level leads to Sokoban
        self.stairs = set()    # '>' found under objects by #terrain
        self.terrain_turn = -999


class Bot:
    def __init__(self, launcher, jev, mode='local', name='Jev'):
        self.name, self.home = name, runs_home(name)
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
            if re.search(r'Closed for inventory|stop damaging that door|chime of a cash register', text) and self.snap and self.snap.status.get('dlvl'):
                self.level().town = True
            if re.search(r'You feel feverish|You turn into a were', text):
                self.run['lycanthropy'] = True
            if 'strange mental acuity' in text:  # telepathy (uhitm.c passive uses canseemon, which needs sight, so a blindfold still stops the floating eye)
                self.run['telepathic'] = True
            if re.search(r'Your armor falls|You find you must drop|can no longer hold your', text) and self.snap and self.snap.me:  # armor and weapon fall to the floor here (polyself.c break_armor/drop_weapon); a bare 'You turn into' re-shift moved the spot off the real pile, gear lost, starved (T5749)
                self.run['dropped'] = (self.snap.status.get('dlvl'), self.snap.me)
            if re.search(r'is displeased|Thou durst call upon me|Then die, mortal|voice of \w+ (booms|rings out|thunders)|relearn thy lessons|Thou hast angered me', text) and 'desecrate my altar' not in text:  # pray.c altar_wrath: engraving on your own altar costs 1 Wis and 1 alignment, not anger; flagged angry, no prayer offered at 7/56 888 turns on, dead (T5954)  # prayed too soon: god angry, Luck -3 (the quote after 'booms:' can be lost: wrath of Tyr killed T5998), praying again only makes it worse
                self.run['god_angry'] = True
            if re.search(r'counting gold coins|footsteps of a guard on patrol|Ebenezer Scrooge', text) and self.snap:  # sounds.c: a vault with gold on this level; raid it with a pick-axe later
                self.level().notes.add('vault')
            if re.search(r'grabs you|You are being (choked|held|crushed)|cannot escape from|swings itself around you|(large|giant) mimic hits', text) and self.snap:
                self.run['held'] = self.snap.status.get('turn') or 0
            if re.search(r'nymph stole|nymph steals|She stole|He stole|stole .* from you|gladly hand over|gladly start removing', text) and self.snap:
                self.run['nymph_lvl'] = self.snap.status.get('dlvl')
                self.run['inv_stale'] = True  # a nymph took the worn shield while resting; the 25-decision refresh showed it worn for 250 turns at AC 10 (T3453)
            if re.search(r'Your armor falls|You can no longer hold your shield|falls to the ground|You find you must drop|You drop your (gloves|weapon)', text) and self.snap and self.snap.me:  # were form shed chain mail, shield, helm, spear; Jev never went back, AC 10, dead (T4960)
                self.run['gear_at'] = (self.snap.status.get('dlvl'), self.snap.me)
            if re.search(r'more confident in your|could be more dangerous', text):  # weapon.c: a skill can be advanced (#enhance); never done, the spear stayed Basic all game
                self.run['enhance'] = True
            if re.search(r'You feel purified|You feel full of awe|affinity to \w+ disappears', text):  # prayer or holy water (potion.c peffect_water)
                self.run['lycanthropy'] = False
            if re.search(r'no gold or credit|you pay for it|Usage fee|You owe|pay before leaving|leave without paying', text):  # not 'Pardon me': bumping a shopkeeper in a doorway set debt, pay said 'You do not owe', 348 pay/bump loops while a mob gathered (T7249)
                self.run['debt'] = self.snap.status.get('dlvl') if self.snap else True
            if re.search(r'You do not owe|You have paid|You paid|Thank you for shopping|pay .* in full', text, re.I):
                self.run['debt'] = False
            if re.search(r"ghost (touches|misses)", text) and self.snap and self.snap.me:
                self.level().ghost = (self.snap.me, self.snap.status.get('turn') or 0)  # it is next to us: search somewhere else
            if re.search(r'You (kill|destroy) the lichen', text) and self.snap:
                self.run['lichen_kill'] = self.snap.status.get('turn') or 0
            if 'little dart' in text and self.snap and self.snap.me:  # trap.c: we stand on a dart trap
                self.level().__dict__.setdefault('dart_traps', set()).add(self.snap.me)
            elif re.search(r'\b(throws|shoots|zaps|breathes|spits)\b|gaze!', text) or re.search(r'\b(arrow|dart|dagger|knife|bolt|spear|shuriken|missile|ray)s? (hits|misses|bounces)', text) and (self.snap.status.get('turn') or 0 if self.snap else 0) - self.run.get('fired_turn', -99) > 2:  # our own bounced magic missile read as being shot: Jev left a fresh Elbereth at 7/54 among hill orcs, dead (T4858)
                self.run['shot_turn'] = self.snap.status.get('turn') or 0 if self.snap else 0
                if m := re.search(r'The ([\w -]+?) (?:throws|shoots|zaps|breathes|spits)\b', text):
                    self.run['shooter'] = m[1]
            for k in re.findall(r'You (?:kill|destroy) (?:the |an? )?(?:invisible )?([a-z -]+?)!', text):  # which corpse is fresh: the eat prompt names each one on the square
                self.run.setdefault('kills', []).append(((self.snap.status.get('turn') or 0) if self.snap else 0, k))
                del self.run['kills'][:-20]
            if re.search(r'\b(hits|bites|stings|kicks|butts|claws|touches)!', text):
                self.run['hit_turn'] = self.snap.status.get('turn') or 0 if self.snap else 0
            ev = re.findall(r'(engulfs you|swallows you|The exit\?|laden with moisture|enveloped in a cloud of steam)|get expelled|regurgitates you|expels you|You (?:destroy|kill) (?:it|the)|dissipates|thin air|You get released', text)
            if ev:  # last event wins: "You kill the newt!  The fog cloud engulfs you!" is one message
                self.run['engulfed'] = bool(ev[-1])
                self.run['engulfer'] = (re.findall(r'The ([a-z ]+?) (?:engulfs|swallows) you', text) or [self.run.get('engulfer')])[-1]
            if re.search(r"[Ww]elcome (again )?to \w", text) and self.snap:
                self.run['welcome'] = (self.snap.status.get('dlvl'), self.snap.status.get('turn') or 0)
            self.run['recent'].append(text)
            self.run['msg_turn'] = self.snap.status.get('turn') or 0 if self.snap else 0
            del self.run['recent'][:-12]

    def _load_runs(self):
        try:
            rs = json.load(open(os.path.join(self.home, 'runs.json')))  # drop records of server restarts, but keep a game in progress
            return [r for i, r in enumerate(rs) if r.get('turns') or (i == len(rs) - 1 and not r.get('ended'))]
        except (OSError, ValueError):
            return []

    def _save_runs(self):
        os.makedirs(self.home, exist_ok=True)
        json.dump(self.runs, open(os.path.join(self.home, 'runs.json'), 'w'), indent=1)

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
        if 'Unlock it' in q:  # was ESC: a key never opened a door; starved beside two locked doors on a level whose '>' was behind one (T5360). Minetown's watch punishes lockpicking
            return 'n' if self.snap and self.run and self.level().town else 'y'
        for pat, ans in rules:
            if pat.lower() in q.lower():
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
        if self.run is not None and s.get('dlvl') and self.run.get('ov_dl') != s['dlvl'] and top_prompt(self.snap.lines)[0] is None:
            return self.overview()
        if self.run is not None and s.get('dlvl') and top_prompt(self.snap.lines)[0] is None and (lv := self.level()).notes and lv.noted != (note := ', '.join(sorted(lv.notes))):
            lv.noted = note
            self.t.send('#annotate\r'); self.t.pump(0.5)
            self.t.send('\x15' + note + '\r')  # ^U clears an EDIT_GETLIN prefill ('Replace annotation ... with?')
            self.settle()
            return self.observe()
        if self.snap.me and s.get('dlvl'):
            lv = self.level()
            x, y = self.snap.me
            lv.near.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            recent = ' '.join(self.run['recent'][-3:]) if self.run else ''
            fresh = 'You kill' in recent and 'You destroy' not in recent and not any(re.search(rf'You kill the [\w -]*{n}', recent) for n in self.never_eat() if n != 'bat')  # bats are dated: edible once calm  # walked to giant bat and acid blob corpses only to skip them
            turn = s.get('turn') or 0
            mon_seen, pct_seen = lv.__dict__.setdefault('mon_seen', {}), lv.__dict__.setdefault('pct_seen', {})
            for p in self.snap.find('%'):  # 7 for this turn's kill: thrown-dagger kills left uncounted corpses; ~40 kills, 4 eaten, fainted (T3625)
                first = pct_seen.setdefault(p, turn)
                if p in lv.corpses and (lv.corpses[p] >= 0 or turn - first > 2):
                    continue  # re-judged for 2 turns: the '%' often shows before 'You kill' is parsed, which filed fresh kills as stale (158 kills, 4 eaten, fainted T3223)
                lv.corpses[p] = turn if fresh and cheb(p, self.snap.me) <= (7 if self.run and any('You kill' in r for r in self.run['recent'][-1:]) else 2) and turn - mon_seen.get(p, -99) <= 2 \
                    else -10**9 if 'You destroy' in recent and cheb(p, self.snap.me) <= 2 else -10**6  # only where the kill stood: an old ape corpse next to a new kill was eaten tainted (T4763)
            for y in range(MAP_TOP, MAP_BOT + 1):
                for x in range(80):
                    if self.snap.is_monster(x, y):
                        mon_seen[(x, y)] = turn  # no pct_seen reset here: a hobbit crossing a 180-turn-old rothe corpse made it 'new', eaten, poisoned (T2090)
            if self.run is not None:
                self.run['prev'] = (s['dlvl'], self.snap.me)  # on a level change: the stair we left by
                self.run['max_dlvl'] = max(self.run['max_dlvl'], s['dlvl'])
                self.run['turns'] = s.get('turn') or self.run['turns']
        self.touch()
        return self.snap

    def overview(self):
        """^O on each new Dlvl: the heading above '<- You are here' says which branch we are in (dungeon.c print_dungeon)."""
        dl = self.run['ov_dl'] = self.snap.status['dlvl']
        self.t.send('\x0f'); self.t.pump(1.0)
        head, mines = None, False
        for _ in range(6):
            for l in self.t.lines():
                h = re.search(r"(The [A-Z][\w' ]+|Sokoban|Fort Ludios|Vlad's Tower)(:| levels? \d)", l)
                head = h[1] if h else head
                mines = mines or 'You are here' in l and head == 'The Gnomish Mines'
            if not re.search(r'--More--|\(\d+ of \d+\)', '\n'.join(self.t.lines())):
                break
            self.t.send(' '); self.t.pump(1.0)
        self.t.send('\x1b'); self.settle()
        if mines:
            md = self.run.setdefault('mines_dls', set())
            if not md and self.run.get('prev', (0,))[0] == dl - 1:
                self.run['mines_stair'] = self.run['prev']  # the main-dungeon '>' that leads here
            md.add(dl)
        else:  # main Dlvl 4 after a visit to Mines Dlvl 4 stayed 'mines': the XL cap sent Jev 3 <-> 4 ~50 times, starved, prayed too soon, dead (T4486)
            self.run.get('mines_dls', set()).discard(dl)
        self.log(f'overview Dlvl {dl}: mines={mines}')
        return self.observe()

    def in_mines(self):
        return self.snap.status.get('dlvl') in self.run.get('mines_dls', ())

    def level(self):
        dl = self.snap.status.get('dlvl', 0)
        lv = self.run['levels'].setdefault(('soko', dl) if self.soko() else ('mines', dl) if self.in_mines() else dl, Level())  # Sokoban and the Mines share Dlvl numbers with the main dungeon  # Sokoban shares Dlvl numbers with the main dungeon
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
                if m['peaceful'] and (m['ch'] == '@' or m['ch'] in 'Gh' and snap.find('{')):  # shopkeeper, watchman or priest: breaking doors here gets us killed
                    self.level().town = True  # peaceful gnomes + a fountain is Minetown: no sign, no @ seen, kicked Izchak's door, struck dead (T6005)
        out = [m for m in out if not (m['name'] or '').startswith(('statue', 'a statue'))]
        for m in out:
            m['name'] = m['name'] or f"unidentified '{m['ch']}' ({m['fg']})"
            m['statue'] = m['name'].startswith(('statue', 'a statue'))
            if m['statue']:
                self.level().blocked.add(m['pos'])
            m['hostile'] = not m['pet'] and not m['peaceful'] and not m['statue'] and (m['ch'] != 'I' or m['dist'] <= 1)
            # sessile, only hurt you if you hit them: never a reason to hold still, and never walk into them
            m['passive'] = bool(re.search(r'floating eye|mold|shrieker|gas spore|acid blob|jelly', m['name'])) or (m['ch'] == 'e' and m['fg'] in ('blue', 'white', 'gray'))
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
        d = lv[0] + lv[2] - (self.snap.status.get('xl') or 1)  # the -1 called an owlbear (difficulty 7) 'weaker' than XL 7; it killed Jev from 70 HP  # lv[2]: danger factor from monsters.json (fight/avoid tip in lv[3], stats in lv[4])
        rel = 'much weaker than you' if d <= -3 else 'weaker than you' if d < 0 else 'about your level' if d <= 1 else 'stronger than you' if d <= 4 else 'much stronger than you'
        return f" (difficulty {lv[0]}, speed {lv[1]}, {lv[4]}, {rel}{'; ' + lv[3] if lv[3] else ''})"

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
        for it in uniq:  # price-ID'd types read like named ones to the rest of the bot ('healing' in text is already trusted)
            look = appearance(it['text'])
            tag = {('potion', 20): 'healing', ('scroll', 20): 'identify', ('scroll', 80): 'enchant armor or remove curse'}.get((look[0], min(self.run.get('prices', {}).get(look) or {0})) if look and len(self.run.get('prices', {}).get(look) or ()) == 1 else None)
            if tag:
                it['text'] += f' (priced as {tag})'
            if it['text'] in self.run.get('empty_wands', ()):
                it['text'] += ' (empty, x:0)'
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
            head = next(l for l in blob.split('\n') if re.search(r'Things that (are|you feel) here', l))
            col = re.search(r'Things that', head).start()  # tty draws the list as an overlay over the map: read only its columns (a gnome corpse came back as 15 map rows, T2997)
            for l in blob.split('here:', 1)[1].split('\n'):
                done = '--More--' in l
                l = l[col:].replace('--More--', '').strip()
                if l and not l.startswith('Things') and len(l) > 2:
                    items.append(l)
                if done:
                    break
        alt = re.search(r'altar to .+? \((lawful|neutral|chaotic|unaligned)\)', blob.replace('\n', ' '))
        if alt and self.snap and self.snap.me:
            self.run.setdefault('altars', {})[(self.snap.status.get('dlvl'), self.snap.me)] = alt[1]
            self.level().notes.add(f'{alt[1]} altar')
        return [i for i in items if not re.search(r'engraving|written|There is|Dlvl|St:', i)]

    # ---------- options ----------
    def build_options(self):
        """Every legal, concrete thing worth doing now: id -> (label, detail, run())."""
        snap, s, lv = self.snap, self.snap.status, self.level()
        me = snap.me
        mons = self.monsters()
        hostiles = [m for m in mons if m['hostile']]
        self.avoid = {m['pos'] for m in hostiles if m['passive'] and 'shrieker' not in m['name']}
        # user: you can walk away from a found mimic (speed 3), but it can follow and hide again, so the 'new' item on the way back is the mimic
        seen = self.level().__dict__.setdefault('mimics', set())
        seen |= {m['pos'] for m in hostiles if 'mimic' in m['name']}
        self.avoid |= {(x, y) for (mx, my) in seen for x in range(mx - 2, mx + 3) for y in range(my - 2, my + 3)
                       if (g := snap.at(x, y)) and g.ch in ')[%?/=!("*$`0' and not snap.is_monster(x, y)}
        # a gas spore's blast next to a shopkeeper has killed two runs: leave those alone entirely
        hostiles = [m for m in hostiles if not ('gas spore' in m['name'] and any(o['peaceful'] and cheb(o['pos'], m['pos']) <= 2 for o in mons))]
        dist, prev = self.dijkstra()
        # a monster we cannot reach (behind walls, across water) is not a reason to stand still
        # unless it is shooting: rested 15 turns on Elbereth while unreachable Uruk-hai shot it 29 -> 5, dead (T5766)
        shot = (s.get('turn') or 0) - self.run.get('shot_turn', -99) <= (20 if any(m['name'] == self.run.get('shooter') and 2 <= m['dist'] <= 8 for m in hostiles) else 3)  # 2+: one hill orc's dart made the adjacent orcs 'shooters' for 20 turns: engrave/attack/engrave alternation, 50 -> 0 (T2512)  # an Uruk-hai shot between Elbereth waits 4 turns apart: 16 -> 0 (T4338)  # one volley is 3-4 messages: "shoots 2 arrows", "1st hits", "2nd misses" pushed 'shoots' out of a 3-line window; Jev waited on Elbereth at 4 HP under Uruk-hai fire (T7290)
        near = [m for m in hostiles if m['dist'] <= 6 and not m['passive'] and (m['dist'] <= 2 or m['pos'] in dist or shot or (MONSTERS.get(self.species(m)) or [0, 0])[1] >= 15)]  # a plains centaur (speed 18) 3 steps off behind a wall wasn't 'near': no Elbereth wait at 15/47, explored off it into its kicks, dead (T7850)  # <= 1: a jaguar 2 steps off (square not in dist) left only 'explore' while an Uruk-hai's wand of striking took 34 -> 0 (T7138)
        opts, charge = {}, None
        if shot and any(m['name'] == self.run.get('shooter') and 'weaker' in self.threat(m) for m in hostiles) and any('weaker' not in self.threat(m) and m['dist'] <= 3 for m in hostiles):  # a hobbit's dagger beside two fire ants ('your level') dropped the Elbereth wait at 27/47: dead (T4266)
            shot = False  # a goblin's thrown dagger pulled Jev off Elbereth into a killer bee hive at 8/29, dead (T2693)
        self.run['adj_names'] = {m['name'] for m in hostiles if m['dist'] <= 1}
        hp, hpmax = s.get('hp', 1), s.get('hpmax', 1)
        danger = f" You are at {hp}/{hpmax} HP: one or two more hits could kill you." if hp * 3 < hpmax else ''

        # attacking from Elbereth erases it and costs alignment (5.0: "You feel like a hypocrite"); only @ and minotaurs ignore it
        # wiki (Elbereth): rest on it, then scuff it and attack, re-engrave when hurt. allmain.c spawns a monster every ~70 turns: 910 waits on Elbereth
        # in a closed Dlvl 8 room at 50/58 filled it with apes, fire ants and zombies, dead (T3499)
        camped = sum(h['choice'] == 'wait' and 'Elbereth' in h['outcome'] for h in self.history[-50:]) >= 40 and hp >= (0.85 if any(m['dist'] <= 5 and 'weaker' not in self.threat(m) and not m['passive'] for m in hostiles) else 0.6) * hpmax  # camped at 36/59: hit a giant rat off Elbereth with a plains centaur and fire ant near, 37 -> 0 in 2 turns (T5097)
        # monmove.c: a scared monster with no square to flee to panic-attacks every turn; a plains centaur boxed in by hill orcs took 28 -> 9 on Elbereth (T5761)
        boxed = [m for m in hostiles if m['dist'] == 1 and not m['passive'] and not any(snap.walkable(x, y) and not snap.is_monster(x, y) and cheb((x, y), me) > 1
                 for x in range(m['pos'][0] - 1, m['pos'][0] + 2) for y in range(m['pos'][1] - 1, m['pos'][1] + 2))]
        on_e = self.engraved_here() and hp < 0.9 * hpmax and not shot and not camped and not boxed  # zapped on Elbereth by an adjacent orc, the only option left was 'retreat' (T4400); healthy: fight from it rather than wait out a speed-1 fog cloud
        for m in hostiles:
            if m['dist'] == 1 and m['pos'] not in self.avoid and not ((on_e or shot and self.engraved_here() and hp < 0.9 * hpmax and m['name'] != self.run.get('shooter')) and m['ch'] != '@' and 'minotaur' not in m['name']):  # shot by a hobgoblin, Jev hit the adjacent rothe off Elbereth instead: 13 -> 0 (T2445)
                if m['name'] == "unknown '@'" and (lv.town or any(o['peaceful'] and o['ch'] == '@' for o in mons) or (s.get('turn') or 0) - self.run.get('hit_turn', -99) > 1):  # hit in the Mines dark by two farlook-failed Woodland-elves, explored instead of fighting: 67 -> 0 (T3567)
                    continue  # unidentified @ can be a shopkeeper or watchman: Jev hit Sarnen beside a mimic in her shop, wand of striking, dead (T5361)
                low = re.compile(r'shrieker|brown pudding|black pudding|grid bug|newt|lichen')  # swatted a grid bug at 29/84 beside an ape: 29 -> 20 -> 0 (T6191)
                if low.search(m['name']) and any(o['dist'] == 1 and not low.search(o['name']) for o in hostiles):
                    continue  # no attacks: Jev hit a shrieker 3 turns while a werejackal and iguana killed it (T1402); hit a brown pudding 4 times (iron splits it, uhitm.c) while an owlbear crushed it 53 -> 8, dead (T5320)
                if 'gelatinous cube' in m['name'] and any(o['dist'] <= 3 and o is not m and not o['passive'] for o in hostiles):
                    continue  # hitting one paralyzes you (passive AD_PLYS, no free action): frozen, an elf mummy and the cube took 67 -> 0 (T9389)
                d = DIR_OF[(m['pos'][0] - me[0], m['pos'][1] - me[1])]
                opts[f'attack_{d}'] = (f"Attack {m['name']} ({DIR_NAME[d]})", f"Melee the adjacent {m['name']} to the {DIR_NAME[d]}.{danger}", lambda d=d: self.act_fight(d))
        if self.history and self.history[-1]['choice'] == 'elbereth' and self.history[-1]['outcome'] == 'engraved Elbereth' and self.engraved_here() and not any(m['dist'] <= 1 and (m['ch'] == '@' or 'minotaur' in m['name']) for m in hostiles):
            opts = {k: v for k, v in opts.items() if not k.startswith('attack_')} or opts  # engrave, attack (erases it), engrave... 4 times beside two Mordor orcs, 17 -> 6, dead (T4528)
        atk = [m for m in hostiles if m['dist'] == 1 and f"attack_{DIR_OF.get((m['pos'][0] - me[0], m['pos'][1] - me[1]))}" in opts]
        if len(atk) >= 3:  # mobbed: switching between sewer rats and a rothe (3 attacks a turn), 26 -> 6 at XL 4 (T3797); kill the worst one first
            top = max(atk, key=lambda m: (not m['passive'], 'were' in m['name'], (MONSTERS.get(self.species(m)) or [0])[0]))  # never a passive one (back from rat form, punched an acid blob 3 turns while 3 rats bit 24 -> 0, T1591); the summoner first (mhitu.c: weres summon help 1 in 10 attacks, either form): a wererat in @ form kept calling rats, newts and a rothe while Jev hit the centipede, 51 -> 4 (T1233)
            opts = {k: v for k, v in opts.items() if not k.startswith('attack_') or k == f"attack_{DIR_OF[(top['pos'][0] - me[0], top['pos'][1] - me[1])]}"}
        were_throw = None  # an animal-form were's bite gives lycanthropy 1 in 4 hits (uhitm.c mhitm_ad_were): 44 of 509 runs caught it; wiki: kill them before melee range
        nymph_throw = None  # nymphs stole a ration, spear, shield and slime molds in one game: hit them before they arrive
        missiles = [it for it in self.inventory if re.search(r'\b(daggers?|knife|knives|darts?|shuriken|spears?|javelins?)\b', it['text'])
                    and 'weapon in' not in it['text'] and 'wielded' not in it['text'].replace('not wielded', '')]
        # hand-thrown arrows do rnd(2) (uhitm.c): only for passives. Boxed by a floating eye with 7 arrows, meleed it, paralysed, starved (T2426)
        arrows = [it for it in self.inventory if re.search(r'\b(arrows?|bolts?|rocks?)\b', it['text'])]  # a thrown rock does d3 (objects.c): stood on 8 rocks and meleed a floating eye, frozen (T6695)
        last_resort = not missiles and not arrows and not any(not m['passive'] for m in hostiles) and any('floating eye' in m['name'] and m['dist'] <= 3 for m in hostiles) \
            and sum(h['choice'] == 'wait_eye' for h in self.history[-20:]) >= 5  # only once waiting failed: a missed spear flew past an eye out of reach, bare-handed 170 turns (T7302)
        if last_resort:
            # nothing else to throw: the wielded spear beats melee (an eye that survives a hit freezes you up to 127 turns): meleed a blocking eye, frozen, rothe (T5195)
            arrows = [it for it in self.inventory if 'weapon in' in it['text'] and re.search(r'\b(daggers?|knife|spear|javelin)\b', it['text'])]
        if (missiles or arrows) and not on_e:
            for m in hostiles:
                dx, dy = m['pos'][0] - me[0], m['pos'][1] - me[1]
                if (missiles or m['passive']) and not (last_resort and 'floating eye' not in m['name']) and not ('unidentified' in m['name'] and self.level().town) and (1 if m['passive'] and 'gas spore' not in m['name'] else 2) <= m['dist'] <= 6 and (dx == 0 or dy == 0 or abs(dx) == abs(dy)) and self.clear_line(me, m['pos']):
                    d = DIR_OF[((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))]
                    it = (missiles or arrows)[0]
                    opts[f'throw_{d}'] = (f"Throw {it['text']} at {m['name']}", f"Throw item {it['letter']} {DIR_NAME[d]} at {m['name']} {m['where']}. Safe way to hit monsters you must not melee (floating eyes, molds); pick it up again afterwards.", lambda l=it['letter'], d=d: self.act_throw(l, d))
                    if 'nymph' in m['name'] and m['dist'] >= 2:
                        nymph_throw = f'throw_{d}'
                    if 'were' in m['name'] and m['ch'] != '@' and not self.run.get('lycanthropy'):
                        were_throw = f'throw_{d}'
        food = [it for it in self.inventory if FOOD.search(it['text']) and 'lizard' not in it['text'] and not re.search(r'potion|gem|stone|glass|spellbook|wand|ring|scroll|amulet|opener|tins?\b', it['text'])]
        for m in hostiles:  # dog.c tamedog via dothrow.c befriend_with_obj: any food thrown at a hostile domestic d/f makes it peaceful at worst (tame if it likes it); horses only take veggy food
            dx, dy = m['pos'][0] - me[0], m['pos'][1] - me[1]
            sp = self.species(m)
            if sp in DOMESTIC and m['dist'] <= 6 and (dx == 0 or dy == 0 or abs(dx) == abs(dy)) and self.clear_line(me, m['pos']):
                ok = [it for it in food if not sp.endswith(('pony', 'horse')) or re.search(r'apple|carrot|banana|melon|orange|pear|slime mold|kelp|lichen', it['text'])]
                ok.sort(key=lambda it: not re.search(r'tripe|meatball|corpse|apple|carrot', it['text']))
                if ok and (len(food) >= 2 or re.search(r'tripe|meatball|corpse', ok[0]['text'])):
                    d = DIR_OF[((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))]
                    opts = {f'tame_{d}': (f"Throw {ok[0]['text']} to the {m['name']}", f"A hostile {sp} becomes peaceful (or your pet) when you throw it food it eats: cheaper than fighting it.", lambda l=ok[0]['letter'], d=d: self.act_throw(l, d))} \
                        if not any(o['dist'] <= 2 and not o['passive'] and self.species(o) not in DOMESTIC for o in hostiles) else {**opts, f'tame_{d}': (f"Throw {ok[0]['text']} to the {m['name']}", f"A thrown food item makes a hostile {sp} peaceful or tame.", lambda l=ok[0]['letter'], d=d: self.act_throw(l, d))}
                    break
        wand = next((it for it in sorted(self.inventory, key=lambda i: not re.search(r'wand of (sleep|cold|fire|striking|magic missile|lightning)', i['text'])) if re.search(r'\bwand\b', it['text'])
                     and not re.search(r'probing|light|nothing|digging|opening|locking|enlightenment|secret door|create monster|wishing|undead turning|polymorph|make invisible|speed monster', it['text'])
                     and it['text'] not in self.run.get('bad_wands', ()) and not re.search(r':0\)', it['text'])
                     and self.run.setdefault('zaps', {}).get((it['text'], s.get('dlvl')), 0) < 4), None)  # a silent unknown wand (polymorph) zapped 379 times at molds turned one into a gargoyle that pinned Jev until it starved (T5526)
        if wand:  # walled in by floating eyes once for 13000 turns with an unknown wand in the pack
            for m in hostiles:
                if 'unidentified' in m['name'] and self.level().town:
                    continue  # darts at an unidentified blue 'G' in Minetown hit a peaceful gnome lord: the watch killed Jev (T2570)
                dx, dy = m['pos'][0] - me[0], m['pos'][1] - me[1]
                # passive only when boxed in: an ID zap at a floating eye 3 steps off was polymorph, it became a red dragon (T4125)
                # also in a losing melee: two unknown wands stayed in the pack while an ogre took 69 -> 0 (T4539)
                # cold bounces can't hurt a Valkyrie: a wand of cold sat unused while a pony took 50 -> 0 in a small room (T3251)
                # 'weaker' foes count when adjacent: two Woodland-elves took 67 -> 0 while the wand of magic missile went at a C 5 steps south (T5738)
                if ('wand of' in wand['text'] and not re.search(r'sleep|fire|cold|lightning|magic missile', wand['text']) or 'wand of cold' in wand['text'] or self.ray_room(me, (dx, dy)) >= 7 or 'wand of' not in wand['text'] and hp * 3 < hpmax and m['dist'] <= 1) \
                        and (m['passive'] and len(dist) <= 3 or 'nymph' in m['name'] and 'wand of' in wand['text'] or hp < 0.5 * hpmax and ('weaker' not in self.threat(m) or m['dist'] <= 1)) and (2 if 'gas spore' in m['name'] else 1) <= m['dist'] <= 6 and (dx == 0 or dy == 0 or abs(dx) == abs(dy)) and self.clear_line(me, m['pos']):
                    d = DIR_OF[((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))]
                    opts[f'zap_{d}'] = (f"Zap {wand['text']} at {m['name']}", f"Zap wand {wand['letter']} {DIR_NAME[d]} at the {m['name']} {m['where']}. Unknown effect; many wands kill or move monsters, and it identifies the wand.", lambda l=wand['letter'], d=d, t=(wand['text'], s.get('dlvl')): self.act_zap(l, d, t))
        # yellow light: its only attack is a 10d20-turn blinding explosion (monsters.h AT_EXPL), speed 15 so no outrunning it; Elbereth stops it (wiki). Blinded twice, both dead to unseen biters (T4631, T2307)
        # a jabberwock (difficulty 18) 3 squares off at XL6 got "Close in on" and no Elbereth: 67 -> 0 in two turns (T4199). @ and minotaurs ignore Elbereth
        dread = [m for m in hostiles if (m['dist'] <= 5 and 'much stronger' in self.threat(m) or 'yellow light' in m['name']
                 or m['dist'] <= 2 and ('stronger' in self.threat(m) or 'your level' in self.threat(m) and s.get('hp', 1) < 0.6 * s.get('hpmax', 1)) and MONSTERS.get(self.species(m), (0, 0))[1] > 12) and m['ch'] != '@' and 'minotaur' not in m['name']]  # a giant spider (speed 15, 'stronger') at XL4: three melee swings 35 -> 11 before Elbereth was offered (T2036); a jaguar ('your level') approached at 28/53 just after a prayer, 28 -> 0 (T3737)
        swarm = [m for m in hostiles if m['dist'] <= 5 and (MONSTERS.get(self.species(m)) or [0, 0])[1] >= 15 and 'weaker' not in self.threat(m) and m['ch'] != '@']
        dread += swarm if len(swarm) >= 2 else []  # two soldier ants (speed 18, bite+sting) at full HP got only attack/approach: 53 -> 0 in two turns (T5703)
        pack = len(near) >= 5 or len(near) >= 3 and sum((MONSTERS.get(self.species(m)) or [(s.get('xl') or 1) if 'unseen' in m['name'] else 1])[0] for m in near) > 2 * (s.get('xl') or 1)  # unseen = XL: blind among 4 unseen wolves at 88/88, '<' close, fought to 0 (T9557)  # 9 level-1 killer bees summed under 2 XL, '<' a step away: poisoned at 25/72 (T8697)  # stepped off Elbereth into four wargs: 69 -> 0 HP in 4 turns
        hallu = bool(set(s.get('conditions', [])) & {'Hallu', 'Hal', 'Hl'})  # names are random: closed in on a 'nickelpede' that was a mumak at 39/73, dead (T7654)
        # a pyrolisk's fire gaze reaches across the room and Elbereth does nothing about it (wiki); it is slow (6) with a 1d6 bite: close in.
        # Waited on Elbereth 2 squares from one at 16/75 while it gazed, dead (T7302)
        for m in near[:2] if not (danger or hp * 2 < hpmax or pack or hallu and hp < 0.8 * hpmax) else [m for m in near if 'pyrolisk' in m['name'] or shot and m['name'] == self.run.get('shooter') and 'weaker' in self.threat(m) and not any(o is not m and o['dist'] <= 3 and not o['passive'] for o in near)]:  # left Elbereth at 37/84 to charge a shooting plains centaur past an ape and a fire ant: 37 -> 0 (T6191)  # Elbereth doesn't stop wands: a fleeing hill orc zapped striking at 13/54 while Jev waited and explored, dead (T4612)  # walking into a fight at a third of max HP killed three giant-bat runs; at 18/47 closed in on a giant ant + werejackal, 18 -> 6, failed prayer (T4446)
            step = m['dist'] > 1 and m['pos'] in dist and self.first_step(prev, me, m['pos'])
            if step and snap.at(me[0] + DIRS[step][0], me[1] + DIRS[step][1]).ch == '^':
                continue  # it comes to us: left an Elbereth doorway onto a known trap toward a jaguar, fell asleep, an owlbear killed Jev at 66/88 (T10632)
            if m['dist'] > 1 and m['pos'] in dist and not re.search(r'unicorn|yellow light|nymph|rope golem|owlbear|mumak', m['name']) and 'stronger' not in self.threat(m) and not (self.standing_on() in ('<', '>') and 'weaker' not in self.threat(m)) and not ('your level' in self.threat(m) and hp < 0.67 * hpmax) and not ('weaker' not in self.threat(m) and sum(o['dist'] <= 8 and not o['passive'] and 'weaker' not in self.threat(o) for o in hostiles) >= 2):  # closed in on 3 Woodland-elves ('avoid if two or more') at 61/71, AC 5: 61 -> 0 (T8554)  # approach/retreat 4 times at 53/103 with a gargoyle ('fight if over 2/3 HP'): 53 -> 27 -> 0 (T12980)  # stepped off '>' toward a tiger at its level, a leocrotta joined, 56 -> 0 a step from the stairs (T8476)  # polymorphed weak, left Elbereth to close on a giant ant with a giant spider near: dead (T5835); let them come, first hit is ours  # nymph: stepping up to one cost a shield and a helm in one game, AC 10, dead (T6402); throw or let her come  # yellow light: its explosion blinds 10d20 turns, 5 of 6 blind deaths; throw instead (wiki). unicorn: speed 24, keeps its distance, butt+kick took 24 HP in one turn
                opts[f"approach_{m['pos'][0]}_{m['pos'][1]}"] = (f"Close in on {m['name']}", f"Step toward {m['name']} {m['where']}." + (' It is shooting you and Elbereth does not stop that: kill it.' if shot and m['name'] == self.run.get('shooter') else ''), lambda m=m: self.act_go(m['pos'], steps=1, adjacent_ok=True))
                if shot and m['name'] == self.run.get('shooter') and (danger or hp * 2 < hpmax):
                    charge = f"approach_{m['pos'][0]}_{m['pos'][1]}"
        strong = False
        open_n = lambda q: sum(snap.walkable(q[0] + dx, q[1] + dy) for dx, dy in DIRS.values())
        pack_near = [m for m in near if m['dist'] <= 5]
        gap = min((m['dist'] for m in pack_near), default=0)
        spd = 20 if any(re.search(r'speed boots.*being worn', it['text']) for it in self.inventory) else 12  # 'very fast' boots: 12 * 5/3
        outrun = near and all((MONSTERS.get(self.species(m)) or [0, 99])[1] * 1.5 <= spd for m in near)
        if near:
            if self.engraved_here() and (not shot or any(m['dist'] <= 1 and m['name'] != self.run.get('shooter') for m in near)):  # shot, but a rothe adjacent: Elbereth still stops its 3 bites (T2445)  # Elbereth only stops melee (wiki); stepping off to 'retreat' threw away fresh Elbereths in two rothe deaths
                # a soldier ant (speed 18) fled the Elbereth and hovered: Jev walked off it to open doors at 69/69 and 49/69, bitten 69 -> 45, booby-trapped door, dead (T7557)
                fastbad = not camped and any((MONSTERS.get(self.species(m)) or [0, 0])[1] >= 15 and 'stronger' in self.threat(m) for m in near)
                if (hp < 0.7 * hpmax or dread or fastbad or hp < 0.9 * hpmax and any(m['dist'] <= 1 for m in near)) and not any((m['ch'] == '@' or 'minotaur' in m['name']) and m['dist'] <= 2 for m in near):  # dist: an unfarlooked '@' 5 squares off (Minetown) removed the wait at 12/63 among 8 monsters; Jev explored into a pony, dead (T7921)  # @ (elves, humans) and minotaurs ignore it (monmove.c onscary): sat 9 turns on it by a Woodland-elf, dead (T4259); 'stuck on Elbereth': up to 44% of a game's decisions were waits on it (0.9 before); at 77/80 HP Jev sat on Elbereth ~1400 turns watching a fog cloud
                    opts['wait'] = ('Stay on Elbereth one turn', 'You stand on Elbereth: most monsters will not melee you here, so waiting heals you safely. Stepping off or attacking loses the protection.', self.act_wait_elbereth)
                    if any('yellow light' in m['name'] for m in dread) or fastbad or any(m['dist'] <= 1 for m in near):  # at 64/81 on Elbereth (attacks dropped, no wait offered) Jev explored off it past an adjacent mumak: 64 -> 29 -> 0 (T8074)  # left a fresh Elbereth to explore with a yellow light 3 squares off, walked into it: blind, hill orcs 56 -> 0 (T4702)
                        opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'goto_', 'fetch', 'pickup'))}
            else:
                fast = [m['name'] for m in near if (MONSTERS.get(self.species(m)) or [0, 0])[1] >= spd]  # our speed is 12, 20 in speed boots
                if not shot and not any(m['dist'] <= 1 for m in near) and sum(h['choice'] == 'wait' and h['outcome'] == 'waited' for h in self.history[-5:]) < 5:  # held 74 turns Hungry for a mountain nymph 4 steps off that never came, starved (T4008)  # "let them come" while six jackals and a werejackal already bit: 42 -> 0 HP in 3 waits
                    opts['wait'] = ('Hold position one turn', 'Search in place for one turn and let monsters come to you (you get the first hit when they step adjacent).', lambda: self.act_keys('ms', 'waited'))
                weak_only = all('weaker' in self.threat(m) for m in near if m['dist'] <= 1) and any(m['dist'] <= 1 for m in near) and hp >= 0.25 * hpmax  # XL8 at 20/74 retreated twice from a rothe (speed 9: adjacent again each turn, 3 attacks), engraving garbled, dead (T13611)
                if not fast and not weak_only and not shot and hp < 0.7 * hpmax and self.retreat_dir(hostiles):  # one step back from a wand-zapping hill orc, 3 times at 5/45: zapped dead (T4400)  # at 50/53 Jev retreated 6 times from hill orcs, eating hits without swinging (T2966); retreating from a giant bat (speed 22) just gives it free hits
                    opts['retreat'] = ('Retreat one step', 'Step to the adjacent square farthest from visible hostiles.' + ' Everything nearby is slower than you, so you can open a gap.', lambda: self.act_retreat(hostiles))
            # wiki (Fighting in corridors): a pack surrounds you on up to 8 sides; in a corridor only one or two can reach you. User: get to a hallway rather than sit on Elbereth
            close = gap < 2 and not outrun  # user: with a crowd already adjacent in a room corner, back into the doorway/hallway 1-2 steps off instead of 100+ turns on Elbereth (T11330-11430)
            if len(pack_near) >= 2 + close and open_n(me) > 2 and (not close or hp >= 0.5 * hpmax) and sum(h['choice'] == 'choke' for h in self.history[-12:]) < 3:  # a pack 4 steps off that never came: choke <-> explore 34 times, Hungry to Weak, dead Fainting (T7245)  # walked off with two apes adjacent at 14/42: free hits, dead (T2116)
                choke = min((q for q, dq in dist.items() if 0 < dq <= (2 if close else 15) and open_n(q) <= 2 and q not in self.level().traps and not snap.is_monster(*q)
                             and min(cheb(q, m['pos']) for m in pack_near) >= min(gap, 3)), key=dist.get, default=None)
                if choke:
                    opts['choke'] = ('Fight from a corridor', f"Walk {dist[choke]} steps {compass(me, choke)} to a corridor or doorway square, so the {len(pack_near)} monsters can only reach you one or two at a time.", lambda q=choke: self.act_go(q, steps=15, stop_new=False))  # the pack is already in view: stopping on each 'new' one left a Mines walk at 1 step, 3 times, between garbled Elbereths (T5005)
            # jabberwock (difficulty 18) at XL 8, '<' 2 steps away: stood and fought, 85 -> 0 (T8069). Non-stalkers never follow upstairs (mondata.c levl_follower)
            strong = any('much stronger' in self.threat(m) for m in near)
            duo = sum(m['dist'] <= 2 and 'weaker' not in self.threat(m) for m in near) >= 2  # offered, not forced: two Woodland-elves at its level (ignore Elbereth): 55 -> 10 in 4 swings, no flee offered, '<' ~15 steps (T4650)
            ups_near = sorted((p for p in snap.find('<') if dist.get(p, 99) <= (60 if strong or outrun else 20 if duo else 8)), key=dist.get)  # speed boots beside a speed-8 giant zombie, '<' 12 steps off: Elbereth panic-attacks 91 -> 0 (T5790)  # a bones red dragon (speed 9) 3 steps off at XL 3: only explore was offered, breathed dead (T1893)
            if (danger or strong or pack or duo or outrun and hp < 0.5 * hpmax) and ups_near and self.standing_on() != '<' and s.get('dlvl', 1) > 1:
                p = ups_near[0]
                opts['flee_up'] = ('Run for the upstairs', f"The up staircase is {dist[p]} steps {compass(me, p)}: walk there and climb. Only monsters right next to you follow.", lambda p=p: self.flee_up(lambda: self.act_descend(p, '<', stop_new=False)))  # fleeing: 'a monster came into view' stopped it twice 2 steps from '<' with a quasit, Grey-elf and elf zombie on it, 24 -> 0 (T10457)
            if snap.lines[me[1]] and self.standing_on() == '<' and s.get('dlvl', 1) > 1:
                opts['upstairs'] = ('Flee up the stairs', 'Climb the up staircase you are standing on; adjacent monsters may follow.', lambda: self.flee_up(lambda: self.act_keys('<', 'went up')))
            if self.standing_on() == '>' and (danger or strong or pack or duo) and 'upstairs' not in opts and 'flee_up' not in opts:
                opts['downstairs'] = ('Flee down the stairs', 'Take the down staircase you are standing on to get away; only adjacent monsters may follow.', lambda: self.act_keys('>', 'went down'))
        hops = sum(h['choice'] in ('upstairs', 'flee_up', 'leave_nymph', 'downstairs') for h in self.history[-6:]) >= 4  # leave_nymph down into a weak pack, flee up, leave again: 14 round trips, then a gamble prayer angered Tyr (T8484)
        adj = [m for m in near if m['dist'] <= 1]
        # a speed-12+ monster adjacent hits on every step of a long walk: ran 15 steps for '<' at 18/94 beside a Grey-elf (ignores Elbereth), 18 -> 8, gamble prayer, dead (T13186)
        chased = 'upstairs' not in opts and any((MONSTERS.get(self.species(m)) or [0, 0])[1] >= 12 for m in adj) and min((dist.get(p, 99) for p in snap.find('<')), default=99) > 3
        # a blocked walk is a free hit: 6 'flee_up ... blocked after 1 steps' beside an Uruk-hai, 31 -> 0 (T7304)
        if chased or any(h['choice'] == 'flee_up' and 'blocked' in h['outcome'] for h in self.history[-3:]):
            opts.pop('flee_up', None)
        # a wraith, a soldier and a pony followed each trip: 7 stair hops on Dlvl 9/10, 71 -> 0 with attacks offered each time (T8105). Adjacent monsters follow: fight them
        if adj and any(k.startswith('attack_') for k in opts) and sum(h['choice'] in ('upstairs', 'flee_up', 'downstairs', 'dodge') for h in self.history[-3:]) >= 2:
            opts = {k: v for k, v in opts.items() if k not in ('upstairs', 'flee_up', 'downstairs')}
        if (strong or pack) and not hops and ({'flee_up', 'upstairs', 'downstairs'} & opts.keys()) and not ('upstairs' not in opts and adj and (chased or all('weaker' in self.threat(m) for m in adj))):  # walked 4 steps to '<' with a werejackal and its jackals adjacent (all weaker): 14 -> 0 in free hits (T2336)  # a werewolf's summoned wolves (no M2_STALK: can't follow) took 34 -> 6 in a turn, '<' one step away (T5826)
            opts = {k: v for k, v in opts.items() if not k.startswith(('attack_', 'approach_', 'explore'))}
            if 'upstairs' in opts and sum(m['dist'] <= 1 for m in near) >= 3:  # arrived on Dlvl 4 into 3 wolves, a Woodland-elf and a rothe: zapped striking 3 times on '<', 23 -> 6, prayed too soon (T9414)
                opts = {k: v for k, v in opts.items() if k in ('upstairs', 'pray')}
        walled = len(dist) <= 3 and any(m['passive'] and m['dist'] == 1 for m in hostiles)  # boxed in by floating eyes
        # at 56/64 Jev wrote Elbereth instead of closing on a large kobold, which stood off and zapped lightning until it died (T9749)
        # blind at 8/76, unseen apes' hits lost in 5-turn rests: rested to death with no Elbereth offered (T6987)
        if dread:
            opts = {k: v for k, v in opts.items() if not k.startswith(('approach_', 'explore'))}
        # uhitm.c: no "Really attack?" while Hallu/Conf/Stun; hallucinating, Jev hit peacefuls, alignment went negative ("You had sinned"), the first prayer failed, fainted, dead (T2759)
        # hack.c: Stunned, every move goes a random direction: six "You attack thin air" swings in Orc Town, 24 -> 0 (T4713)
        stun = bool(set(s.get('conditions', [])) & {'Stun', 'Stn'})
        if not hallu:
            self.run['peace_pos'] = (s.get('dlvl'), {m['pos'] for m in mons if m['peaceful']})
        elif self.run.get('peace_pos', (None,))[0] == s.get('dlvl'):  # hallucinating, the shopkeeper showed as a 'raging nerd': zapped fire at Zhangmu, his wand killed Jev (T3000)
            pp = self.run['peace_pos'][1]
            opts = {k: v for k, v in opts.items() if not (k.startswith(('attack_', 'zap_', 'throw_')) and k[-1] in DIRS
                    and any((me[0] + DIRS[k[-1]][0] * i, me[1] + DIRS[k[-1]][1] * i) in pp for i in range(1, 1 + (1 if k.startswith('attack_') else 13))))}
        if stun or set(s.get('conditions', [])) & {'Hallu', 'Hal', 'Hl', 'Conf', 'Cnf'} and (s.get('turn') or 0) - self.run.get('hit_turn', -99) > 2:
            opts = {k: v for k, v in opts.items() if not k.startswith(('attack_', 'approach_', 'throw_', 'zap_', 'explore', 'retreat', 'choke', 'goto_'))} or opts
            if stun:
                opts.setdefault('wait', ('Wait out the stun', 'You are stunned: any move or attack goes in a random direction. Search in place one turn until it wears off.', lambda: self.act_keys('ms', 'waited')))
        horn = next((it for it in self.inventory if 'unicorn horn' in it['text'] and not re.search(r'\bcursed', it['text'])), None)
        ills = set(s.get('conditions', [])) & {'Stun', 'Stn', 'Conf', 'Cnf', 'Hallu', 'Hal', 'Hl', 'Blind', 'Blnd', 'Bl'}
        if horn and ills and not any('being worn' in it['text'] and re.search(r'blindfold|towel', it['text']) for it in self.inventory):  # apply.c use_unicorn_horn: fixes stun, confusion, hallucination, blindness (not lost stats in 5.0)
            opts = {'unihorn': (f"Apply {horn['text']}", f"A unicorn horn cures {', '.join(sorted(ills))}: apply it (may take a couple of tries).", lambda l=horn['letter']: self.act_keys('a' + l, 'applied the unicorn horn')),
                    **{k: v for k, v in opts.items() if k != 'wait'}}
        big_hit = bool(self.history) and (self.history[-1]['hp'] or 0) - hp >= hp and any(m['dist'] <= 1 for m in hostiles)  # one more turn like the last one kills
        # operator: Elbereth is for emergencies; the default is back into a corridor and fight one at a time (was hp < 0.7 or any pack: 30-140 engravings a game, mostly forced)
        # monmove.c: scared with no square to flee to (MMOVE_NOMOVES) sets panicattk, so Elbereth cannot stop a boxed monster; engrave/attack alternation
        # against a scorpion in a dead-end corridor gave it a free turn each engraving, 33/78 -> 6, a too-soon prayer, dead (T12125)
        # only when the boxed ones are all that is near: a crowd boxes its own members, the rest still flee; jackals, a giant ant and Mordor orcs, no Elbereth offered, 17 -> 0 on attacks only (T5086 werejackal)
        # AT_HUGS (monsters.h): once held, engrave.c can_reach_floor is FALSE and you cannot step away, so engrave before contact: an owlbear took 51/94 to 0 in 4 turns, Elbereth refused 'cannot reach the floor' (T9944)
        hugger = (s.get('turn') or 0) - self.run.get('held', -99) > 2 and hp < 0.75 * hpmax and any(m['dist'] <= 3 and HUGGERS.search(m['name']) for m in hostiles)
        if (near and hp < 0.45 * hpmax or hugger or dread or pack and open_n(me) > 2 and 'choke' not in opts and hp < 0.6 * hpmax or walled or self.unseen_attacker() or 'Blind' in s.get('conditions', []) and hp < 0.7 * hpmax) and not self.engraved_here() and not (boxed and not walled and len(near) <= len(boxed)) and not (near and all(m['ch'] == '@' or 'pyrolisk' in m['name'] for m in near)) and not any(m['ch'] == '@' and m['dist'] == 1 for m in hostiles) \
                and not set(s.get('conditions', [])) & ({'Stun', 'Stn', 'Conf', 'Cnf', 'Lev'} | (set() if big_hit else {'Hallu', 'Hal', 'Hl'})) \
                and sum(h['choice'] == 'elbereth' and 'interrupted' in h['outcome'] for h in self.history[-4:]) < 2 \
                and (s.get('turn') or 0) - self.run.get('no_engrave', -99) > 5 \
                and not (any(m['dist'] == 1 and m['name'] in self.run.get('e_blockers', ()) for m in hostiles) and (s.get('turn') or 0) - self.run.get('engrave_interrupted', -99) <= 5):  # count: unseen biters left adj_names empty, 16 interrupted engravings in a row while Hungry turned Weak, then Fainting (T5312)  # @ ignore it (monmove.c onscary: S_HUMAN); 2 Elbereths at 9/49 beside a Woodland-elf, a rock mole also near, dead (T2543); engrave.c scrambles writing
            opts['elbereth'] = ('Engrave Elbereth', 'Write Elbereth in the dust here with a finger (1 turn). Most monsters will not melee you while you stand on it; attacking from it erases it.' + (' The best move when badly hurt.' if danger else '') + (' Scared monsters flee, so this can drive off the ones boxing you in.' if walled else ''), self.act_elbereth)
        if hugger and 'elbereth' in opts:
            opts = {k: v for k, v in opts.items() if not k.startswith(('attack_', 'approach_')) and k not in ('rest', 'wait')}
        if big_hit and {'elbereth', 'retreat', 'flee_up', 'upstairs'} & opts.keys():  # hallucinating, a 'shrieker' was a dwarf king: 35 -> 14 in a turn, threw a dart, dead (T4026)
            opts = {k: v for k, v in opts.items() if not k.startswith(('attack_', 'throw_', 'approach_')) and k not in ('rest', 'wait')}
        if hp < 0.5 * hpmax and ('elbereth' in opts or self.engraved_here()):  # choke <-> Elbereth alternation at 21/68 -> 10: each step off wasted the engraving (T5005)
            opts.pop('choke', None)
        held = len(pack_near) >= 2 and open_n(me) <= 2 and not strong and not shot  # already in the corridor: fight them one at a time, don't stop to engrave
        if ('choke' in opts or held) and hp >= 0.5 * hpmax and not self.unseen_attacker():
            if 'choke' in opts and opts.get('wait', ('',))[0].startswith('Stay on Elbereth'):
                del opts['wait']  # 0.4: at 25/53 Elbereth was dropped for a walk to a corridor beside a rothe, 25 -> 8 garbling retries (T3712)  # wiki: Elbereth is breathing room; a corridor is how to actually fight a group
            opts.pop('elbereth', None)
            if 'choke' in opts and len(pack_near) >= 3:
                opts = {k: v for k, v in opts.items() if not k.startswith(('attack_', 'approach_', 'wait', 'explore', 'throw_'))}  # standing in the open with 3+ around: every turn spent swinging there lets all of them hit

        # the bounce risk is only for unknown wands: a known wand of fire zapped at an adjacent foe in a corridor bounced back, 26 -> 0 (T7065)
        # an ape took 38 -> 3 with only 'attack' on offer, prayer 100 turns old, two unknown potions and an unknown wand unused (T4683)
        # 11/47 beside a Woodland-elf hitting for 7-11 a turn, prayer unused but not yet 'trouble', 5 unknown potions: dead (T4520)
        # 11/63 among three hill orcs and a wand of striking, above prayer's 1/7, six unknown potions unused: dead (T6093)
        no_god = self.run.get('prayed_turn') is not None and (s.get('turn') or 0) - self.run['prayed_turn'] < 500 or self.run.get('god_angry')
        if danger:
            for it in sorted(self.inventory, key=lambda i: 'healing' not in i['text']):  # healing first: the break offered an unknown yellow potion over 2 potions of healing, dead (T8671)  # unknown potion beside a Woodland-elf at 25/90: asleep, dead (T9392); an unknown potion on a working Elbereth: 11% heal, sleeping killed a Jev the warhorse was fleeing from
                if re.search(r'\bpotions?\b', it['text']) and (not self.engraved_here() or shot and LOW_HP(s) or 'healing' in it['text']) and ('healing' in it['text'] or LOW_HP(s) or no_god or not any(m['dist'] <= 1 for m in hostiles) or hp * 4 < hpmax and (sum(m['dist'] <= 1 for m in hostiles) >= 2 or any(m['dist'] <= 1 and 'weaker' not in self.threat(m) for m in hostiles))) \
                        and not re.search(r'sleeping|blindness|hallucination|confusion|booze|sickness|paralysis|water|oil|clear', it['text']):  # clear = water: 4 blind quaffs of it vs a housecat pack (T2801); drank a known potion of sleeping held by an ape (T9512)
                    opts[f"quaff_{it['letter']}"] = (f"Quaff {it['text']}", f"Drink this potion hoping it heals.{danger}", lambda l=it['letter']: (self.act_keys('q' + l, 'quaffed'), self.read_inventory())[0])  # stale inventory re-offered a drunk potion 3-4 times in a fight (T2801, T5616)
                    break

        fatal = [c for c in s.get('conditions', []) if c in ('FoodPois', 'Fpois', 'Poi', 'TermIll', 'Ill', 'Stone', 'Ston', 'Sto', 'Slime', 'Slim', 'Slm', 'Strngl', 'Stngl', 'Str', 'InLava', 'Lav')]  # kill in a few turns; prayer cures
        lyc = self.run.get('lycanthropy') and not any(m['dist'] <= 2 for m in hostiles)  # 'cure it mid-fight at 60%+ HP' spent the prayer at 24/32 beside a wererat, dead at 7/32 (T1231): reverted  # not mid-fight: curing it at 18/46 beside the wererat spent the prayer, dead 5 turns later (T3790); slow, and each were bite re-infects: it follows the normal timeout (two runs prayed every 4 turns into "Then die, mortal!")
        me = self.snap.me
        walled = me and all((g := self.snap.at(me[0] + dx, me[1] + dy)) is None or g.ch in ' |-0' and not self.snap.is_door(me[0] + dx, me[1] + dy) for dx, dy in DIRS.values())  # pray.c stuck_in_wall: 8 rock/wall/boulder neighbours is major trouble; a monster's scroll of earth boxed Jev in Sokoban, 2000 turns searching, starved (T7613)
        # pray.c TROUBLE_CURSED_LEVITATION is major trouble: cursed levitation boots, 1400 turns of 'take it off' (fails) and no prayer, starved (T3026)
        stuck_lev = any(re.search(r'\bcursed\b.*levitation.*being worn', it['text']) for it in self.inventory)
        trouble = LOW_HP(s) or s.get('hunger') in ('Weak', 'Fainting') or fatal or lyc or walled or stuck_lev
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
        # being hit counts as adjacent: blinded by a yellow light, the biting housecat vanished from view, prayer 962 turns on was withdrawn, forced to rest, dead (T5933)
        # tripe-only Weak bets at 500 too: eat.c vomits a non-orc 1 in 2 (confused, stunned): ate it 886 turns after praying, two rothes found it stunned, dead (T3736)
        # Fainting bets at 300 (P ~.66): 177 turns fainting 325 after a prayer, a snake killed it mid-faint long before starvation (T3298)
        # eat.c newuhs: Weak is uhunger 1-50 and the step to Fainting faints at once (u.uhs <= WEAK), so 'Fainting' is only seen after the first faint;
        # Weak with no food in the pack bets at 300 like Fainting: Weak 357 turns after praying, fainted beside a jaguar, dead (T10134)
        # starving is certain death, so hunger bets earlier (1000 let a Weak Jev faint to death 640 turns after praying; 600 did it again at 524, T5771)
        if trouble and not self.run.get('god_angry') and (fatal or starving or (turn - last >= {'Weak': 1000 if not any(m['dist'] <= 1 for m in hostiles) and turn - self.run.get('hit_turn', -99) > 2
                                                                                      and not all('tripe' in it['text'] for it in self.inventory if FOOD.search(it['text'])) else 500 if any(FOOD.search(it['text']) for it in self.inventory) else 300, 'Fainting': 300}.get(s.get('hunger'), 500) if last is not None else turn >= 110)):
            opts['pray'] = ('Pray to Tyr', f"You are in trouble ({fatal[0] + ': fatal within a few turns unless cured' if fatal else 'low HP' if LOW_HP(s) else 'boxed in by boulders and walls with no way out' if walled and s.get('hunger') not in ('Weak', 'Fainting') else 'lycanthropy: you will turn into a jackal' if lyc and s.get('hunger') not in ('Weak', 'Fainting') else s.get('hunger')}). Last prayer: {'never' if last is None else 'turn ' + str(last)}. Current turn {s.get('turn')}. A successful prayer fully heals.", self.act_pray)
        # a fresh Elbereth beats a coin-flip prayer: 176 turns after praying, the forced gamble at 10/54 on a new Elbereth angered Tyr, dead to an Uruk-hai (T4295)
        elif not self.run.get('god_angry') and s.get('exp') is not None and (LOW_HP(s) or s.get('hunger') == 'Fainting' and any(m['dist'] <= 3 and not m['passive'] for m in hostiles)) and (any(m['dist'] <= 7 for m in hostiles) or self.unseen_attacker() or turn - self.run.get('hit_turn', -99) <= 3) and last is not None and turn - last >= 100 \
                and not (self.engraved_here() and s.get('hp', 1) > 5 and not shot and turn - self.run.get('hit_turn', -99) > 3 and not any(m['ch'] == '@' or 'minotaur' in m['name'] for m in hostiles if m['dist'] <= 7)):  # stung on Elbereth (a cornered scared monster panic-attacks, monmove.c) at 7/60 171 turns after praying: no gamble, the soldier ant finished it (T6021)  # exp None: polymorphed, 0 HP only reverts form; gambled at 3/3 HD2 and angered Tyr (T8484)  # a quasit's wand took 29 -> 0 from range; 3/54 HP 243 turns after a prayer, no gamble offered, dead (T5218). rnz(350)<=200+t is ~50% at t=100; failing angers Tyr, but death was certain
            opts['pray'] = ('Pray to Tyr (gamble)', f"Last prayer was only {turn - last} turns ago: Tyr may well be angry (bad luck, maybe smiting). But {'fainting from hunger' if s.get('hunger') == 'Fainting' else 'at ' + str(s.get('hp')) + ' HP'} with a monster attacking, this may be the last chance.", self.act_pray)

        if turn - max(self.run.get('soko_broke', {}).values(), default=-9999) < 600 * len(self.run.get('soko_broke', {})):
            opts.pop('pray', None)  # broke a Sokoban boulder: Luck < 0 makes pray.c p_type 1, the prayer fixes nothing
        holy = next((it for it in self.inventory if re.search(r'\bholy water|blessed (clear )?potions? of water', it['text'])), None)
        if holy and self.run.get('lycanthropy'):  # potion.c: blessed water cures lycanthropy ("You feel purified") and saves the prayer
            opts['holy_water'] = (f"Quaff {holy['text']}", 'Holy water cures lycanthropy without using a prayer.', lambda l=holy['letter']: (self.act_keys('q' + l, 'quaffed holy water'), self.read_inventory())[0])
            opts.pop('pray', None) if not LOW_HP(s) and not fatal else None
        cure = next((it for it in self.inventory if re.search(r'lizard corpse|acid blob corpse|potion of acid', it['text'])), None)
        if cure and set(fatal) & {'Stone', 'Ston', 'Sto'}:  # eat.c fix_petrification: a lizard or acidic corpse (or acid, potion.c) cures stoning without using the prayer
            opts = {'unstone': (f"{'Quaff' if 'potion' in cure['text'] else 'Eat'} {cure['text']}", 'You are turning to stone: this cures it at once.', lambda it=cure: self.act_keys('q' + it['letter'], 'quaffed acid') if 'potion' in it['text'] else self.act_eat(it['letter']))}
        if 'pray' in opts and not fatal and not starving and not LOW_HP(s) and s.get('hunger') != 'Fainting' and any('nymph' in m['name'] and m['dist'] <= 7 for m in hostiles):
            del opts['pray']  # helpless 3 turns: prayed Weak with a wood nymph 3 steps off, it took mithril, chain mail and every weapon; AC 10 bare-handed till death (T3753)
        if not self.run.get('god_angry') and (turn - last >= 800 if last is not None else turn >= 300):  # prayer ready: fight on, pray at low HP
            opts = {k: v for k, v in opts.items() if not (k.startswith('quaff_') and 'healing' not in v[0])}  # a swirly potion of sleeping at 15/50, prayer 1460 turns old: frozen, killed by a pony

        # shop floor gold belongs to the shopkeeper: picking it up billed Jev, who then could not leave and died to Mr. Kipawa; eating its food kept another Jev locked in a shop for 4000 turns
        # walking distance, not cheb: outside a Minetown wall a shop 3 squares off dropped every throw at a floating eye blocking the corridor; 300 turns Fainting, dead (T7682)
        shop = any(d == s.get('dlvl') and dist.get(p, 99) <= 7 and any(re.search(r'for sale|no charge', i) for i in v) for (d, p), v in self.run.get('here', {}).items()) or self.run.get('debt') == s.get('dlvl')
        if shop:  # an unknown wand zapped at a brown mold in Sipaliwini's store angered her: dead to her wand (T1314)
            # a known attack wand or a throw with no peaceful on the line or its bounce is safe: a fire ant panic-bit Jev 20 -> 0 in a shop door, magic missile unused (T4916)
            pp = {m['pos'] for m in mons if m['peaceful']}
            opts = {k: v for k, v in opts.items() if not k.startswith(('zap_', 'throw_')) or k[-1] in DIRS and (k.startswith('throw_') or re.search(r'wand of (sleep|cold|fire|striking|magic missile|lightning)', v[0]))
                    and not any((me[0] + DIRS[k[-1]][0] * i * sg, me[1] + DIRS[k[-1]][1] * i * sg) in pp for i in range(1, 14) for sg in (1, -1))}
        # eat.c: a poisonous corpse costs rnd(15) HP and maybe Str without poison resistance; fainting with no prayer, kobolds beat starving (killed 10, ate none, fainted to a kitten T3459)
        self.run['calm'] = not hostiles and s.get('hunger') in ('Hungry', 'Weak', 'Fainting')  # eat.c: a bat stuns 30 turns, a giant bat 60: bearable with nothing in view, and only when food matters
        # Hungry with no food in the pack, Jev left a fresh kobold corpse (T3902); the hunger prayer 840 turns on was smitten, fainted to a cave spider (T4427). eat.c: 4 in 5 poison costs rnd(15) HP or Str
        self.run['desperate'] = s.get('hunger') in ('Weak', 'Fainting') and ('pray' not in opts or not any(FOOD.search(it['text']) for it in self.inventory)) and s.get('hp', 1) > 15 \
            or s.get('hunger') == 'Hungry' and not any(FOOD.search(it['text']) for it in self.inventory) and s.get('hp', 1) > 30
        if s.get('hunger') in ('Hungry', 'Weak', 'Fainting'):
            for it in self.inventory:
                if re.search(FOOD, it['text']) and not any(n in it['text'] for n in NEVER_EAT) and it['text'] not in self.run.get('inedible', ()) \
                        and not re.search(r'potion|gem|stone|glass|spellbook|wand|ring|scroll|amulet|opener', it['text']) \
                        and (s.get('hunger') == 'Fainting' or not any(m['dist'] <= 1 and not m['passive'] for m in hostiles)) and (s.get('hunger') != 'Hungry' or 'tripe' not in it['text']) and ('lizard' not in it['text'] or s.get('hunger') == 'Fainting'):  # the lizard is the stoning cure
                    # eat.c: food older than 30 turns rots 1 in 7 (rations too), rotten can knock you out: ate a ration Weak beside a pony, unconscious, dead (T4291)
                    # tripe: rn2(2) vomiting for non-orc non-cavemen (eat.c); ate it Hungry beside a black unicorn, confused+stunned, dead (T4650)
                    opts[f"eat_{it['letter']}"] = (f"Eat {it['text']}", f"You are {s.get('hunger')}: eat item {it['letter']} from your pack now, before you weaken and faint (fainting next to a monster is how most of your games have ended).", lambda l=it['letter']: self.act_eat(l))
            here = [i for i in self.here_items() if 'corpse' in i and not any(n in i for n in self.never_eat())]
            age = s.get('turn', 0) - lv.corpses.get(me, s.get('turn', 0))
            fresh = [p for p, t0 in lv.corpses.items() if p != me and p in dist and s.get('turn', 0) - t0 < 35 and dist[p] < 15]
            if fresh and not here and not shop:
                p = min(fresh, key=dist.get)
                opts['goto_corpse'] = ('Go eat the fresh corpse', f"Walk {dist[p]} steps {compass(me, p)} to a corpse that appeared recently and eat it if it is safe.", lambda p=p: self.act_goto_corpse(p))
        if s.get('hunger') != 'Satiated' and not shop:
            here = [i for i in self.here_items() if 'corpse' in i and not any(n in i for n in self.never_eat())]
            age = s.get('turn', 0) - lv.corpses.get(me, -10**6)  # a corpse we did not see appear is of unknown age: treat as rotten
            why = ' Packed food is rare and most deaths so far were fainting from hunger: eating fresh kills now, even when not hungry, is what keeps you alive later.'
            # eat.c: rotted = age / (10 + rn2(20)), +2 if cursed; > 5 tainted (never before age 60 uncursed), > 3 only rnd(8) HP: so < 50 is safe, and arrival from 15 steps at < 35 stays under it (one Jev ate nothing for 1650 turns of kills, fainted, T4698)
            # lichens and lizards never rot; starving with no prayer left, a maybe-tainted corpse beats certain death (walked past a floating eye corpse, fainted to a bat)
            if here and (age < 50 or re.search(r'lichen|lizard|acid blob', here[0]) or s.get('hunger') in ('Weak', 'Fainting') and 'pray' not in opts and age < 60):  # eat.c: tainted when age/(10+rn2(20)) > 5, never below 60 uncursed; a 234-turn horse killed a Weak Jev (T6692)  # a destroyed zombie's corpse is pre-aged: always tainted, Weak Jev ate one and died of food poisoning (T2797)
                opts['eat_corpse'] = (f"Eat the {here[0]} here", f"Eat {here[0]} on this square. It appeared about {age} turns ago (old corpses can be rotten or poisonous).{why}", self.act_eat_corpse)
            fresh = [p for p, t0 in lv.corpses.items() if p != me and p in dist and s.get('turn', 0) - t0 < 35 and dist[p] < 10]
            if fresh and not here and not near and 'goto_corpse' not in opts:
                p = min(fresh, key=dist.get)
                opts['goto_corpse'] = ('Go eat the fresh corpse', f"Walk {dist[p]} steps {compass(me, p)} to a corpse that appeared recently and eat it if it is safe.{why}", lambda p=p: self.act_goto_corpse(p))
        ew = next((it for it in self.inventory if re.search(r'\bwand\b', it['text']) and 'wand of' not in it['text'] and it['text'] not in self.run.setdefault('etested', set())), None)
        if ew and not hostiles and not LOW_HP(s) and s.get('hunger') not in ('Weak', 'Fainting') and 'Blind' not in s.get('conditions', []) and self.standing_on() not in ('<', '>', '_', '{', '#') and not self.soko():
            # wiki (Engrave-identification): digging, fire and lightning auto-identify; 3 unknown wands rode to a lightning death on Dlvl 10 with no '<' known (T5319)
            opts[f"engrave_id_{ew['letter']}"] = ((f"Engrave-test {ew['text']}", 'Nothing hostile in view: engrave with the unknown wand to learn what it is (digging is an escape hole).', lambda it=ew: self.act_engrave_id(it)))
        if 'eat_corpse' in opts and not near:  # taken 15 of 98 offers (explore won), and hunger is the top killer: eat it
            opts = {k: v for k, v in opts.items() if k in ('eat_corpse', 'pray')}
        if 'goto_corpse' in opts and s.get('hunger') not in ('Weak', 'Fainting') and min((dist[p] for p, t0 in lv.corpses.items() if p in dist and s.get('turn', 0) - t0 < 35), default=99) > 2 and (hp < 0.6 * hpmax or (s.get('turn') or 0) - self.run.get('hit_turn', -99) <= 10):
            del opts['goto_corpse']  # a fresh ape 1 step off at 38/93 Hungry was skipped by this, went stale, no food, fainted, mountain centaur (T8599)  # forced at 24/45 just after a hill orc fight: the next orc hit 24 -> 13 -> 3, prayed 158 turns on, dead (T4402)
        if 'goto_corpse' in opts and not near:  # passed up for explore/rest ~60% of the time; one Jev prayed 6 times for food in 7700 turns
            opts = {k: v for k, v in opts.items() if k in ('goto_corpse', 'pray')}
        if any(m['dist'] <= 1 for m in near):  # Weak, walked for a corpse through a bugbear + hobgoblin gang: free hits, dead (T4496)
            opts.pop('goto_corpse', None)
        # eat.c:1953: any corpse has a 1/7 rotten roll, ~1 in 37 meals knocks you out up to 10 turns; an elf takes ~15 turns to eat.
        # Elves out of sight in a dark room beat an unconscious Jev 46 -> 1 HP (T8218)
        if s.get('hunger') not in ('Weak', 'Fainting') and (any(m['dist'] <= 6 for m in hostiles) or (s.get('turn') or 0) - self.run.get('hit_turn', -99) <= 5
                                                             or s.get('hunger') != 'Hungry' and s.get('hp', 1) < 0.5 * s.get('hpmax', 1)):  # Not hungry at 16 HP, ate an orc corpse in an orc pack's room: hit mid-meal 16 -> 9, gamble prayer angered Tyr, fainted later (T3978)
            opts = {k: v for k, v in opts.items() if k not in ('eat_corpse', 'goto_corpse')}
        if s.get('hunger') not in ('Weak', 'Fainting') and any(m['dist'] <= 2 for m in near):  # eating twice mid-swarm took 25 HP to 1 (giant rat, T2344)
            opts = {k: v for k, v in opts.items() if not k.startswith(('eat_', 'goto_corpse'))}

        if shop and self.run.get('debt'):  # broke and billed, the shopkeeper blocks the door forever: sell things (general stores buy anything)
            if s.get('gold'):
                opts['sell_pay'] = ('Pay the shopkeeper', 'You owe the shopkeeper and now have gold; pay so they let you out.', self.act_pay)
            for it in [it for it in self.inventory if not re.search(r'weapon in|being worn|gold piece', it['text'])][:3]:
                opts[f"sell_{it['letter']}"] = (f"Sell {it['text']} to pay your debt", "You owe the shopkeeper and have no gold, so they will not let you leave. Drop this to sell it for credit, then pay.", lambda l=it['letter']: (self.act_keys('d' + l, 'sold'), self.act_keys('p', 'paid'))[1])
        worn = ' '.join(it['text'] for it in self.inventory if 'being worn' in it['text'])
        for i, item in enumerate(self.here_items()[:4]):
            price = re.search(r'for sale, (\d+) zorkmid', item)
            look = appearance(item)
            if price and look:  # price-ID: every quote narrows what this appearance can be
                n = re.match(r'(\d+) ', item)
                cands = price_bases(look[0], int(price[1]) // (int(n[1]) if n else 1), s.get('ch') or 11)
                old = self.run.setdefault('prices', {}).get(look)
                self.run['prices'][look] = cands & old if old and cands & old else cands
            known = self.run.get('prices', {}).get(look) if look else None
            # what is worth gold: AC first (user: mithril; 5.0 is about low AC), then scrolls of identify (20) / enchant armor or remove curse (80) and healing potions (20)
            why = ('Mithril: AC 5-6 body armor that never rusts.' if 'mithril' in item and (suit_ac(item) or 0) > max((suit_ac(it['text']) or 0 for it in self.inventory if 'being worn' in it['text']), default=0)
                   else 'Better body armor than you wear: lower AC.' if (suit_ac(item) or 0) > max((suit_ac(it['text']) or 0 for it in self.inventory if 'being worn' in it['text']), default=0) + 1
                   else 'A helmet for your bare head: lower AC.' if re.search(r'orcish helm|dwarvish iron helm|hard hat|elven leather helm|leather hat', item) and not re.search(r'helm|hat|cap', worn)
                   else 'Boots for bare feet: lower AC.' if re.search(r'low boots|walking shoes|high boots|jackboots|iron shoes|hard shoes', item) and not re.search(r'boots|shoes', worn)
                   else 'A key or lock pick: opens locked boxes and doors (a priority item).' if UNLOCKER.search(item) and not any(UNLOCKER.search(it['text']) for it in self.inventory)
                   else 'A unicorn horn cures confusion, stun, blindness and sickness (a priority item).' if 'unicorn horn' in item and not any('unicorn horn' in it['text'] for it in self.inventory)
                   else 'Priced like a scroll of identify (base 20).' if look and look[0] == 'scroll' and known == {20}
                   else 'Priced like enchant armor or remove curse (base 80): both worth reading.' if look and look[0] == 'scroll' and known == {80}
                   else 'Priced like a potion of healing (base 20).' if look and look[0] == 'potion' and known == {20}
                   else None)
            if price and (FOOD.search(item) and 'corpse' not in item or why) and int(price[1]) <= s.get('gold', 0) and not self.run.get('debt'):
                opts[f'buy_{i}'] = (f"Buy {item}", f"Pick up {item} and pay {price[1]} of your {s.get('gold')} gold. " + (why or 'Packed food prevents fainting from hunger.'), lambda item=item: (self.act_pickup(item), self.act_pay())[1])
                continue
            armed = any(WEAPON.search(it['text']) for it in self.inventory)  # a nymph took the spear; the filter left 2 scimitars on the floor, bare-handed vs hill orcs, dead (T2578)
            daggers = sum(int(n[1]) if (n := re.match(r'(\d+) ', it['text'])) else 1 for it in self.inventory if 'dagger' in it['text'])
            # user: no gems (not playing for score; a gray stone can be a loadstone), no random weapons: the spear stays until Mjollnir; 2-3 daggers pry boxes and get thrown
            if re.search(r'\b(gems?|stones?|rocks?|glass)\b', item) and 'luckstone' not in item or WEAPON.search(item) and armed and not re.search(r'dagger|pick-axe|Mjollnir|Excalibur', item) or 'dagger' in item and daggers >= 3:
                continue
            if shop or 'for sale' in item or 'corpse' in item and not ('lichen' in item or 'lizard' in item and not any('lizard' in it['text'] for it in self.inventory)) or HEAVY.search(item) or item in self.run.get('heavy', ()):
                continue
            opts[f'pickup_{i}'] = (f"Pick up {item}", f"Pick up {item} from this square.", lambda item=item: self.act_pickup(item))
        box = next((i for i in self.here_items() if re.search(r'\b(chest|large box)\b', i) and 'for sale' not in i), None)
        if box and not shop and not any(m['dist'] <= 6 for m in hostiles) and self.run.setdefault('looted', {}).get((s.get('dlvl'), me), 0) < 2:  # 5.0 mklev.c: 2/3 of levels above the Oracle get a box, half with healing potions; the Mines entry level's always has food
            opts['loot'] = (f"Open {box} and take what is inside", 'Boxes on early levels often hold potions of healing, enchant scrolls or food. If it is locked: unlock it with a key or lock pick, else pry it with a dagger, else kick it open.', self.act_loot)
        if 'Burdened' in s.get('conditions', []) or 'Stressed' in s.get('conditions', []):
            for it in self.inventory:
                if (HEAVY.search(it['text']) or JUNK.search(it['text'])) and not re.search(r'weapon in|being worn|alternate weapon|mithril|at the ready|quiver|pick-axe|mattock', it['text']):
                    opts[f"drop_{it['letter']}"] = (f"Drop {it['text']}", f"You are {'Burdened' if 'Burdened' in s['conditions'] else 'Stressed'}: slower, and you can't fight or flee well. {it['text']} is heavy and of little use.", lambda l=it['letter']: (self.act_keys('d' + l, 'dropped it'), self.read_inventory())[0])
            spots = [] if near or self.soko() else [q for u in snap.find('<') for dx, dy in DIRS.values() if (q := (u[0] + dx, u[1] + dy)) in dist and dist[q] <= 40 and snap.at(*q).ch in '.' + ''.join(')[%?/=!("$')]
            if spots:  # wiki Stash: leave spares next to the up stairs (not on '>': they fall down), monsters don't act while you're off-level
                q = min(spots, key=dist.get)
                for k in [k for k in opts if k.startswith('drop_')]:
                    l, txt = k[5:], opts[k][0][5:]
                    opts[k] = (f"Stash {txt} next to the up stairs", f"{opts[k][1]} Leave it beside the '<' {dist[q]} steps {compass(me, q)}; you can come back for it.", lambda l=l, txt=txt, q=q: self.act_stash(l, txt, q))
            if 'Stressed' in s['conditions'] and not near and any(k.startswith('drop_') for k in opts):  # Stressed 1600 turns with spare banded mail, 2 Uruk-hai shields, 2 iron shoes: half speed, killed by a mob (T7699)
                opts = {k: v for k, v in opts.items() if k.startswith(('drop_', 'eat_', 'wear_')) or k == 'pray'}
            opts = {k: v for k, v in opts.items() if not (k.startswith('pickup_') and JUNK.search(v[0]) and 'mithril' not in v[0])}
        lev = next((it for it in self.inventory if re.search(r'levitation|invisibility', it['text']) and re.search(r'being worn|on (left|right) hand', it['text'])), None)
        if lev and 'pray' in opts and re.search(r'\bcursed\b', lev['text']) and 'uncursed' not in lev['text']:
            opts = {'pray': opts['pray']}
        elif lev and (not near or 'invisib' in lev['text']):  # -2 levitation boots floated Jev over the stairs for 2400 turns until it starved
            # invisible, the hero has no @ on screen: the bot took an elf for itself while a soldier ant ate it (T5244)
            opts = {f"remove_{lev['letter']}": (f"Take off {lev['text']}", 'It keeps you from playing normally (no stairs while levitating; while invisible you cannot see where you are). Remove it.', lambda it=lev: self.act_keys(('R' if 'hand' in it['text'] else 'T') + it['letter'] + '\x1b', 'took it off'))}
        # cursed plain cloak: only blocks body-armor swaps (wiki), and any cloak is MC1 against were bites; cursed mithril still beats AC 7+.
        # Unknown-look cloaks (tattered cape, opera cloak...) can be invisibility: still need a known BUC.
        # Same for unknown-look boots, gloves and helmets: 'riding boots' were cursed levitation, starved on Dlvl 3 (T3026)
        worn_ac = max((suit_ac(it['text']) or 0 for it in self.inventory if 'being worn' in it['text']), default=0)
        better_body = any((suit_ac(it['text']) or 0) > worn_ac and 'being worn' not in it['text'] and it['text'] not in self.run.get('unwearable', {}) for it in self.inventory)
        if not near and not set(s.get('conditions', [])) & {'Blind', 'Conf', 'Cnf', 'Hallu', 'Hal', 'Hl', 'Stun', 'Stn'} and not shop:
            for it in self.inventory:  # identify, enchant armor (worn armor only: else the scroll is wasted) and remove curse are always safe to read
                if re.search(r'scrolls? of (identify|remove curse|enchant armor)|priced as (identify|enchant armor)', it['text']) and ('identify' in it['text'] or 'remove curse' in it['text'] or worn):
                    opts[f"read_{it['letter']}"] = (f"Read {it['text']}", 'Identify shows what an unknown item is; enchant armor lowers AC by 1 (or more); remove curse frees cursed gear.', lambda l=it['letter']: self.act_read(l))
        if not near or self.engraved_here() and not any(m['dist'] <= 1 for m in near):  # a nymph's charm left the mithril-coat in the pack: 50 turns waiting on Elbereth at AC 11, quasit 22 -> 1, dead (T9072)
            for it in self.inventory:
                t = it['text']
                if re.search(r'\b(armor|mail|helmet|helm|cap|hat|cloak|mantelet|wrapping|mithril-coat|boots|shoes|gloves|gauntlets|shield|robe|apron|shirt|coat|jacket|tunic)\b', t) and 'being worn' not in t and not re.search(r'levitation|invisibility', t) and not (re.search(r'\b(riding|combat|jungle|hiking|mud|buckled|snow) boots|\b(old|padded|riding|fencing) gloves|\b(plumed|etched|crested|visored) helmet', t) and not re.search(r'\b(uncursed|blessed)\b', t)) and not (re.search(r'cloak|mantelet|mithril', t) and not re.search(r'\b(uncursed|blessed)\b', t) and not (re.search(r'\b(dwarvish|hooded|orcish|leather|elven|oilskin) cloak|mantelet|faded pall|mummy wrapping', t) and not better_body) and not ('mithril' in t and not worn_ac)) and (s.get('ac') or 0) > self.run.setdefault('unwearable', {}).get(t, -99):  # AC got worse since the failed try (nymph stole the worn armor): try again
                    opts[f"wear_{it['letter']}"] = (f"Wear {t}", "Put on this armor (takes a few turns; may be cursed if unidentified).", lambda it=it: self.act_wear(it))
            worn = next((it for it in self.inventory if 'being worn' in it['text'] and suit_ac(it['text']) is not None), None)
            better = max((it for it in self.inventory if 'being worn' not in it['text'] and (suit_ac(it['text']) or 0) > (suit_ac(worn['text']) if worn else 99)
                          and it['text'] not in self.run.setdefault('unwearable', {})), key=lambda it: suit_ac(it['text']), default=None)
            if better and not any(re.search(r'cloak|wrapping|mantelet|faded pall|cape|robe|apron', it['text']) and 'being worn' in it['text'] for it in self.inventory):  # 'cannot wear armor over a cloak'
                opts[f"wear_{better['letter']}"] = (f"Swap {worn['text']} for {better['text']}", f"Body armor: {better['text']} gives {suit_ac(better['text'])} AC, {worn['text']} only {suit_ac(worn['text'])}. Take it off, put the better one on.", lambda w=worn, b=better: self.act_swap(w, b))
            sor = next((it for it in self.inventory if re.search(r'polished silver shield|shield of reflection', it['text']) and 'being worn' not in it['text'] and it['text'] not in self.run['unwearable']), None)
            held = next((it for it in self.inventory if re.search(r'\bshield\b', it['text']) and 'being worn' in it['text']), None)
            if sor and held:  # the polished silver shield is always reflection (objects.h): carried unworn beside a +3 small shield to a jaguar death (T3976)
                opts[f"wear_{sor['letter']}"] = (f"Swap {held['text']} for {sor['text']}", 'A polished silver shield is a shield of reflection: rays (wands, breath) bounce off you. Worth more than a few points of AC.', lambda w=held, b=sor: self.act_swap(w, b))
            wand = next((it for it in self.inventory if 'wand of wishing' in it['text'] and not re.search(r':0\)', it['text'])), None)
            if wand and not self.run.get('wand_empty'):  # carried an identified wand of wishing unused to an Elvenqueen death at AC 10 (T6359)
                opts['wish'] = (f"Zap {wand['text']}", f"Make a wish: {WISHES[min(self.run.get('wishes', 0), len(WISHES) - 1)]}.", lambda l=wand['letter']: self.act_wish(l))
            ls = next((it for it in self.inventory if re.search(r'amulet of (life saving|reflection|guarding|ESP)', it['text']) and 'being worn' not in it['text'] and not re.search(r'\bcursed', it['text'])), None)  # an uncursed amulet of guarding (AC 2, MC 2) rode in the pack to a soldier ant death (T8671)
            if ls and not any('amulet' in it['text'] and 'being worn' in it['text'] for it in self.inventory):
                opts['wear_amulet'] = (f"Put on {ls['text']}", 'A known good amulet: life saving brings you back once, reflection bounces rays, guarding gives AC and magic cancellation.', lambda l=ls['letter']: self.act_keys('P' + l, 'put on the amulet'))

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
            # '>' in view behind a closed door into an explored room: no door had a blank side, 12000 turns of searching on Dlvl 1, starved (T12215)
            lost = [p for p in snap.find('>') if p not in dist]
            if snap.is_door(*door) and spots and (any(snap.at(*q) is not None and snap.at(*q).ch == ' ' for q in orth) or lost and any(q not in dist for q in orth)):
                q = min(spots, key=dist.get)
                doors.append((min((cheb(door, p) for p in lost), default=0) if lost else dist[q], door, q))
        for _, door, q in sorted(doors)[:2]:
            if door in lv.locked and (cheb(door, me) <= 1 or watched):
                continue  # kick_<dir> covers it; in town a locked door stays shut
            what = 'locked door' if door in lv.locked else 'closed door'
            opts[f'door_{door[0]}_{door[1]}'] = (f"Go through the {what} {compass(me, door)}", f"Walk {dist[q]} steps to the {what} {compass(me, door)}, open it (kicking it if locked). What lies behind is unexplored.", lambda q=q, door=door: self.act_kick_door(q, door))
        if (not near or s.get('hunger') in ('Weak', 'Fainting')) and not shop:  # starving beats a hovering monster; only stepped-on items were ever picked up; Jev fainted twice with food lying in view
            objs = [q for c in ')[%?/=!("$' for q in snap.find(c)]
            if self.run.get('dropped') == (s.get('dlvl'), me) or not (s.get('title') or '').startswith('Were') and self.run.get('dropped', (0,))[0] != s.get('dlvl'):
                self.run.pop('dropped', None)
            loot = [q for q in objs if q in dist and 0 < dist[q] <= (80 if s.get('hunger') in ('Weak', 'Fainting') and snap.at(*q).ch == '%' else 15) and ((s.get('dlvl'), q) not in self.run['here'] or self.run.get('dropped') == (s.get('dlvl'), q)) and lv.corpses.get(q, -1) < 0
                    and sum(cheb(q, o) <= 3 for o in objs) < 6]  # a dense cluster is a shop
            if loot:
                starving = s.get('hunger') in ('Weak', 'Fainting')
                q = min(loot, key=lambda q: (not (starving and snap.at(*q).ch == '%'), dist[q]))  # starving: food first
                g = snap.at(*q).ch
                what = {'%': 'food', '$': 'gold', '[': 'armor', ')': 'a weapon', '!': 'a potion', '?': 'a scroll', '/': 'a wand', '=': 'a ring', '"': 'an amulet', '(': 'a tool'}[g]
                opts['fetch'] = (f"Go look at the item {compass(me, q)} ({what}?)", f"Walk {dist[q]} steps {compass(me, q)} to the '{g}' on the floor and see what it is; food keeps you from fainting, armor lowers AC.", lambda q=q: self.act_go(q))
        for (dl, q), items in list(self.run.get('stashes', {}).items()):  # armor stolen by a nymph / lost to a were-change: the spare is in the stash
            if dl != s.get('dlvl') or near or 'Burdened' in s.get('conditions', []) or self.soko():
                continue
            if me == q:
                del self.run['stashes'][(dl, q)]
                continue
            need = [t for t in items if t not in self.run.setdefault('stash_tried', set()) and (sl := next((r for r in SLOTS.values() if re.search(r, t)), None)) and not any(re.search(sl, it['text']) and 'being worn' in it['text'] for it in self.inventory)]
            if need and q in dist:
                opts['stash_fetch'] = (f"Go back to your stash for {need[0]}", f"You left {', '.join(items)} beside the up stairs {dist[q]} steps {compass(me, q)}. You wear nothing in that slot now: pick it up and put it on.", lambda q=q, need=need: (self.run['stash_tried'].update(need), self.act_go(q))[1])
        d = self.run.get('dropped')  # the shield and helm a were-form shed: fetch's 15-step radius lost them for good (AC 6 -> 10, dead to a rothe T6437)
        if d and d[0] == s.get('dlvl') and dist.get(d[1]) and not near and not (s.get('title') or '').startswith('Were'):
            opts['fetch_gear'] = ('Go back for the gear you dropped', f"Your armor and weapon fell off when you changed form. They lie {dist[d[1]]} steps {compass(me, d[1])}: walk there, pick them up and put them back on.", lambda q=d[1]: self.act_go(q))
        packed = sum(bool(FOOD.search(it['text'])) for it in self.inventory)
        if not near and s.get('gold', 0) >= 5 and packed < 3:  # a Jev with 236 gold starved to death: shops sell food
            food = [q for q in snap.find('%') if q in dist and 0 < dist[q] <= 15 and (s.get('dlvl'), q) not in self.run['here'] and lv.corpses.get(q, -1) < 0
                    and sum(cheb(q, o) <= 3 for c in ')[%?/=!("' for o in snap.find(c)) >= 6]
            if food:
                q = min(food, key=dist.get)
                opts['shop_food'] = (f"Go look at the food for sale {compass(me, q)}", f"Walk {dist[q]} steps into the shop to see the '%' item and its price. You have {s.get('gold')} gold and {packed} food items packed.", lambda q=q: self.act_shop_go(q))
        if not near and s.get('gold', 0) >= 20 and 'shop_food' not in opts:  # armor (AC), scrolls, potions: stepping on each shows its price, which identifies some by type
            wares = [q for c in '[?!' for q in snap.find(c) if q in dist and 0 < dist[q] <= 20 and (s.get('dlvl'), q) not in self.run['here']
                     and sum(cheb(q, o) <= 3 for c2 in ')[%?/=!("' for o in snap.find(c2)) >= 6]
            if wares:
                q = min(wares, key=dist.get)
                opts['shop_look'] = (f"Go look at the {snap.at(*q).ch} for sale {compass(me, q)}", f"Walk {dist[q]} steps into the shop to see the item and its price (you have {s.get('gold')} gold). Armor lowers AC; a price can identify a scroll or potion.", lambda q=q: self.act_shop_go(q))
        gold, xl = s.get('gold', 0), s.get('xl') or 1
        if not near and not shop and gold < 4000:  # user: gold buys protection, then keep 2000-4000 for shopping; fetch's 15-step radius left games at 13-533 gold
            coins = [q for q in snap.find('$') if q in dist and dist[q] > 0 and (s.get('dlvl'), q) not in self.run['here'] and self.run.setdefault('gold_miss', {}).get((s.get('dlvl'), q), 0) < 3 and sum(cheb(q, o) <= 3 for c in ')[%?/=!("' for o in snap.find(c)) < 6]
            if coins and 'fetch' not in opts or coins and snap.at(*min(coins, key=dist.get)).ch == '$':
                q = min(coins, key=dist.get)
                opts['fetch_gold'] = (f"Pick up the gold {compass(me, q)}", f"Walk {dist[q]} steps to the '$'. You have {gold} gold: about {500 * xl} buys permanent AC from a temple priest, and more buys food and armor in shops.", lambda q=q: self.act_fetch_gold(q))
        priest = [m for m in mons if m['peaceful'] and re.match(r'(peaceful )?priest(ess)? of ', m['name'])]
        if priest and not near and gold >= 500 * xl + (4000 if self.run.get('protection') else 0):  # 5.0 priest.c: offering the larger "suggested" sum gives 1 AC per 2x base (base = peak XL x 150-250), any temple priest
            opts['donate'] = (f"Buy protection from the {priest[0]['name'].replace('peaceful ', '')}", f"You have {gold} gold. Walk to the priest ({priest[0]['where']}) and donate the larger suggested sum (2x a base of 150-250 per peak XL, so {300 * xl}-{500 * xl} gold); it buys 2-4 points of permanent divine protection (lower AC), then +1 per later purchase.", lambda p=priest[0]['pos']: self.act_donate(p))
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
        xl_low = (s.get('xl') or 1) < MINES_XL
        bad = {q for (dl, q), t0 in self.run.setdefault('bad_down', {}).items() if dl == s.get('dlvl') and s.get('turn', 0) - t0 < 3000}
        downs = [p for p in snap.find('>') + sorted(lv.stairs) if p in dist or p == me]
        # a bad '>' is skipped only when another way down exists: otherwise the level above dead-ends too and Jev cascades up to Dlvl 1 (starved, T7223)
        downs = [p for p in downs if p not in bad] or downs
        ms = self.run.get('mines_stair')
        if self.in_mines() and s.get('dlvl', 1) >= min(self.run.get('mines_dls') or {0}) + 2 and sum(m['ch'] == 'o' and not m['peaceful'] for m in mons) >= 5:
            self.run['orctown'] = True  # minetn-1.lua Orcish Town: dozens of orcs, no temple or shops; nothing there is worth the fight
        if ms and ms[0] == s.get('dlvl') and (xl_low or self.run.get('orctown')) and sum(lv.searched.values()) < 1500:
            downs = [p for p in downs if p != ms[1]]  # main dungeon first: Oracle, Sokoban, XP
        md = self.run.get('mines_dls') or {0}
        stuck_main = ms and sum(self.run['levels'].get(ms[0], Level()).searched.values()) >= 1500  # main '>' never found: the Mines are the only way on (500 sent an XL5 into Mines Dlvl 5 ~30 times, killed by a rothe T3492)
        mcap = self.in_mines() and self.run.get('orctown') or self.in_mines() and xl_low and (not self.run.get('soko_done') and not stuck_main or lv.town or s.get('dlvl', 1) >= min(md) + 3)
        too_deep = mcap or s.get('dlvl', 1) >= (s.get('xl') or 1) + 2  # pace: Dlvl <= XL+1 (XL+2 still lost most runs on Dlvl 4-5 before T2000)
        ups = [p for p in snap.find('<') if p in dist]
        above = self.run['levels'].get(s.get('dlvl', 1) - 1)
        if too_deep and ups and (self.standing_on() != '<' or mcap) and (mcap or not (above and sum(above.searched.values()) >= 800)) and (dist[ups[0]] <= 2 or not any(m['dist'] <= 1 for m in hostiles)):  # walked for '<' 50 steps off with Mordor orcs and a snake adjacent: 7 tries, 44 -> 0, dead praying (T3746)  # the level above already waited out its pace cap: going back just ping-pongs (4 <-> 5 25 times in 100 turns, T4478)  # XL5 on Dlvl 7 died to a winter wolf; XL+3 was too late
            opts['ascend'] = ('Head back upstairs', f"This level is far too deep for experience level {s.get('xl')}. Walk to the up staircase ({dist[ups[0]]} steps {compass(me, ups[0])}) and climb to Dlvl {s.get('dlvl', 0) - 1}.", lambda p=ups[0]: self.act_descend(p, '<'))
        if too_deep and not ups and not self.in_mines() and any(k.startswith('explore_') for k in opts):
            # a hole dropped XL4 Jev from Dlvl 5 to 7: 300 turns of fetches, pickups and hidden-door searches before a yellow light and an orc band, dead (T2696)
            opts = {k: v for k, v in opts.items() if not k.startswith(('fetch', 'goto_', 'sell_', 'buy_'))}  # rest stays: it is also the heal-up option
        if len(snap.find('{')) >= 4:  # the Oracle's four fountains: Sokoban's entrance is the second '<' one level down
            self.run['oracle'] = s.get('dlvl')
        soko_hunt = s.get('dlvl') == (self.run.get('oracle') or -9) + 1 and len(snap.find('<')) < 2 and not self.run.get('soko_done') and self.frontiers(dist)
        if soko_hunt or mcap or s.get('dlvl', 1) >= (s.get('xl') or 1) + 1 and not (s.get('hunger') in ('Weak', 'Fainting') and 'pray' not in opts) or s.get('hp', 1) < 0.8 * s.get('hpmax', 1) or s.get('ac', 0) >= 9 and s.get('dlvl', 1) >= 4:  # stripped by nymphs to AC 10, Jev went down to Dlvl 7 and died to a Woodland-elf (T6265)  # Weak with no prayer: a new level has corpses, staying only starves (searched Weak -> Fainting beside '>', T2566)  # rest first; fleeing downward from a fight at this depth is how the pony and giant ant runs ended
            pass
        elif self.standing_on() == '>':
            opts['descend'] = ('Go down the stairs', f"You are on the down staircase to Dlvl {s.get('dlvl', 0) + 1}.", lambda: self.act_keys('>', 'descended'))
        elif downs:
            opts['descend'] = ('Head for the downstairs', f"Walk to the known down staircase ({dist[downs[0]]} steps {compass(me, downs[0])}) and descend to Dlvl {s.get('dlvl', 0) + 1}.", lambda p=downs[0]: self.act_descend(p))
        pick = next((it for it in self.inventory if re.search(r'pick-axe|dwarvish mattock', it['text'])), None)
        if pick and not near and s.get('dlvl', 1) < (s.get('xl') or 1) + 1 and not soko_hunt and not mcap and self.standing_on() not in ('<', '>', '_', '{'):
            # same pace as the stairs: 'not too_deep' let XL5 dig 6 -> 7 and XL6 7 -> 8, dead to a giant spider (T4825)
            opts['dig_down'] = ('Dig down with the pick-axe', f"Apply {pick['text']} downward to dig a hole to Dlvl {s.get('dlvl', 0) + 1} (takes several turns; skips the rest of this level).", lambda l=pick['letter']: self.act_dig(l))
        # resting at full HP was Jev's favourite way to do nothing (537 of 650 choices in one game); searching has its own option
        if not near and not any(m['dist'] <= 4 and not m['passive'] for m in hostiles) and not self.unseen_attacker() and s.get('hp', 1) < 0.85 * s.get('hpmax', 1):  # a pony 3-4 squares off but outside 'dist' (unreachable square): rested 15 turns at 16/41, 18 -> 7, dead praying (T2658)  # blind, Jev rested beside an orc and died (T3212)
            opts['rest'] = ('Rest and search 15 turns', 'Stay put for up to 15 turns to regain HP. Interrupted if a monster appears.', lambda: self.act_search(15))
        elif not near and s.get('hp', 1) < 0.5 * s.get('hpmax', 1) and any(m['dist'] <= 4 and not m['passive'] for m in hostiles):
            opts['wait'] = ('Wait one turn', 'Hurt, with a monster close by: let it come to you and get the first hit rather than walking around.', lambda: self.act_keys('ms', 'waited'))
        if not fr and not downs and ups and sum(lv.searched.values()) >= 1000 and not self.soko() and s.get('dlvl', 1) > 1:  # Dlvl 1's '<' leaves the dungeon
            # a Mines level whose '>' was never found: 6000 turns of searching, living on prayer, fainted (T11246). Go up, try another way down
            opts['dead_end'] = ('Give up on this level and go back up', f"You have searched this level for {sum(lv.searched.values())} turns without finding a way down. Climb to Dlvl {s.get('dlvl', 0) - 1} and look for another down staircase.", lambda p=ups[0]: self.act_dead_end(p))
        hole = min(((h, q) for h in sorted(lv.holes) for q in dist if max(abs(q[0] - h[0]), abs(q[1] - h[1])) == 1), key=lambda t: t[0][0] != t[1][0] and t[0][1] != t[1][1], default=None)  # orthogonal first: no diagonal steps into doorways
        if hole and not fr and not downs and not ups and not self.soko():
            # a kobold dug a hole in the only doorway: refusing it boxed Jev in a stub for 5000 turns, starved (T9952). trap.c: holes drop 1+ levels in this dungeon
            opts['dead_end'] = ('Jump into the hole', f"The only way out is a hole/trap door at {hole[0]}. Step into it and fall to a lower level.", lambda h=hole: self.act_hole(*h))
        if 'dead_end' in opts and not near:
            opts = {k: v for k, v in opts.items() if k in ('dead_end', 'pray') or k.startswith(('eat_', 'pickup_'))}  # pickups: stood on a wand and a scroll, both dropped by this filter, starved (T6672)
        if not fr and not downs:
            if not walled: self.run['walled'] = s.get('turn') or 0
            # boxed in by Minetown's peaceful gnomes, meleed the eye at once: frozen, killed by an imp (T7290). Wait them out first.
            long_walled = walled and (s.get('turn') or 0) - self.run.setdefault('walled', s.get('turn') or 0) > 200
            if walled and not long_walled:
                opts['wait_eye'] = ('Search 10 turns and let it drift off', 'A monster you must not melee boxes you in. Floating eyes drift and peacefuls wander off; waiting is safe, hitting it risks long paralysis.', lambda: self.act_search(10) if self.engraved_here() else self.act_elbereth())  # hostile eyes keep approaching: 3 sat in a corridor 4000 turns, starved (T12136); Elbereth makes them flee (monmove.c onscary)
            molds = [m for m in hostiles if m['pos'] in self.avoid and (long_walled or self.blindfold() or ('floating eye' not in m['name'] and not (m['ch'] == 'e' and m['fg'] == 'blue')))
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
                           else "You blindfold yourself first, so its gaze cannot freeze you" if m['ch'] == 'e' and self.blindfold()
                           else "Last resort: if it survives a hit it may paralyze you for a long time while other monsters attack; killing it in one blow is safe" if m['ch'] == 'e'
                           else "It hurts you passively when you hit it; the fight stops if HP gets low")
                    opts['kill_blocker'] = (f"Kill the {m['name']} blocking the way", f"The {m['name']} {m['where']} blocks the only way out: you are stuck here until it dies. Walk next to it and fight it. {why}.", lambda m=m: self.act_kill_blocker(m['pos']))
                    rk = next((i for i in self.here_items() if re.search(r'\brocks?\b', i) and 'for sale' not in i), None)
                    if m['ch'] == 'e' and any(k.startswith(('throw_', 'zap_')) for k in opts):
                        del opts['kill_blocker']  # throw at it instead: melee paralyses for up to 127 turns
                    elif m['ch'] == 'e' and rk and not self.blindfold():
                        opts['kill_blocker'] = ('Pick up the rocks here to throw at the eye', 'Rocks thrown at the floating eye hurt it without touching it; melee risks paralysis.', lambda rk=rk: self.act_pickup(rk))
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
        if not fr and not downs and not near and 'kill_blocker' not in opts and 'dead_end' not in opts:  # walled in: searching finds nothing  # search_hidden won 123 of 125 dead_end offers: 5000 turns on one Dlvl 3, starved (T6672)
            spot = self.search_spot(dist)
            if spot:
                opts['search_hidden'] = ('Search for hidden passages', f"No unexplored edges or downstairs are known. Walk {dist[spot]} steps {compass(me, spot)} to a likely spot (dead end or wall) and search there.", lambda: self.act_search_at(spot))
            # never read unknown scrolls (only known or price-ID'd identify): ZLORFIK read here 'to find the stairs' was punishment, ball and chain, dead to a pony (T3251)
        m = self.soko()
        if m and m[0].startswith('soko1'):  # 5.0 premaps Sokoban's boulders on arrival; a '0' that shows up later is one of soko1's two giant mimics (dat/soko1-*.lua appear_as boulder)
            real = self.level().__dict__.setdefault('soko_boulders', set(snap.find('0')))
            fake = set(snap.find('0')) - real
            if fake and self.run.get('fake_log') != len(fake):
                self.run['fake_log'] = len(fake)
                self.log(f"sokoban: boulder(s) at {sorted(fake)} were not premapped: giant mimics", 'warn')
            for q in fake:  # giant mimic: 2x 3d6 claws and sticky (monsters.h); only worth a fight when strong and healthy
                d = next((k2 for k2, (dx, dy) in DIRS.items() if (me[0] + dx, me[1] + dy) == q), None)
                if d and (s.get('xl') or 0) >= 10 and hp >= 0.8 * hpmax and not near:
                    opts[f'mimic_{d}'] = ('Attack the fake boulder (giant mimic)', 'This boulder was not on the premapped Sokoban level, so it is a giant mimic. Hit it first while it pretends, at full HP.', lambda d=d: self.act_fight(d))
        if m and re.search(r'\b(exit|leave|quit|skip|abandon|forget)\b.*\bsoko', self.order, re.I):
            self.run['soko_done'] = True  # operator order 'exit sokoban': the only option left was soko_push, so the order never reached a choice
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
                    new = sokoban.replan(m, me, set(snap.find('0')) - (set(snap.find('0')) - self.level().__dict__.get('soko_boulders', set(snap.find('0')))), set(snap.find('^'))) if tries[m[0]] <= 3 else None
                    self.log(f"sokoban {m[0]}: push {i + 1} off-plan; replan -> {len(new) if new else 'no solution, leaving'}", 'warn')
                    pick = next((it for it in self.inventory if re.search(r'pick-axe|dwarvish mattock', it['text'])), None)
                    if new:
                        self.run['soko_plan'][m[0]] = new
                        self.run.setdefault('soko_stuck', {}).pop((m[0], i), None)
                    elif pick and snap.at(*b).ch == '0' and (behind in dist or behind == me) and m[0] not in self.run.setdefault('soko_broke', {}):
                        # last resort, once per level: dig.c fracture_rock -> sokoban_guilt is Luck -1, back +1 per 600 turns (attrib.c)
                        opts = {k2: v for k2, v in opts.items() if k2 == 'pray' or k2.startswith('eat_')}
                        opts['soko_break'] = (f"Sokoban: break the stuck boulder {compass(me, b)} with the pick-axe",
                                              'No solution is left from here. Breaking one boulder costs 1 Luck (no successful prayer for about 600 turns) but reopens the puzzle.',
                                              lambda m=m, b=b, behind=behind, k=k, l=pick['letter']: self.act_soko_break(m, b, behind, k, l))
                    else:
                        self.run['soko_done'] = True
                if 'soko_push' in opts and not near and hp >= 0.6 * hpmax:  # forced push off Elbereth at 26/64 with fled orcs in view: 14 HP next turn, dead (T5149); a gargoyle out of view lifted the old hostiles gate, forced pushes at 20/57 then 10/57, dead (T9530)
                    opts = {k2: v for k2, v in opts.items() if k2 == 'soko_push' or k2 == 'pray' or k2.startswith('eat_')}
                opts.pop('descend', None)  # a gnome king nearby lifted the filter and Jev walked out with 8 of 41 pushes left
            elif not ups and not m[0].startswith('soko1'):  # plan 'done' but '<' unreachable: the step count ran past a 166-push plan, soko_up/descend ping-ponged 11000 turns, starved (T17559)
                tries = self.run.setdefault('soko_replans', {})
                tries[m[0]] = tries.get(m[0], 0) + 1
                new = sokoban.replan(m, me, set(snap.find('0')) - (set(snap.find('0')) - self.level().__dict__.get('soko_boulders', set(snap.find('0')))), set(snap.find('^'))) if tries[m[0]] <= 3 else None
                if new:
                    self.run.setdefault('soko_plan', {})[m[0]] = new
                else:
                    self.run['soko_done'] = True
            elif m[0].startswith('soko1'):
                self.run['soko_done'] = True  # top level solved: the zoo and prize are ordinary exploring from here
            elif ups and not near and not self.run.get('soko_done'):  # gave up on the level above: soko_up/descend ping-ponged 1400 times, 13000 turns (T20758)
                opts = {k2: v for k2, v in opts.items() if k2 == 'pray' or k2.startswith('eat_')}
                opts['soko_up'] = ('Sokoban: climb to the next puzzle level', 'This level is solved. The next Sokoban level is up these stairs.', lambda p=ups[0]: self.act_descend(p, '<'))
        uni = [u for u in hostiles if 'unicorn' in u['name'] and 1 < u['dist'] <= 6]
        dn = [p for p in snap.find('>') if p in dist]
        if m and uni and dn:  # Sokoban is no-teleport: a black unicorn there gets cornered and fights (speed 24, 1d12+1d6): 46 -> 0 beside a boulder push (T3549)
            self.run['unicorn_left'] = s.get('turn') or 0
            opts = {k2: v for k2, v in opts.items() if k2 == 'pray' or k2.startswith('quaff_')}
            opts['leave_unicorn'] = ('Leave Sokoban for now', f"A hostile {uni[0]['name']} is {uni[0]['dist']} steps away. In Sokoban it cannot teleport off, so it fights when cornered: go back down and return later.", lambda p=dn[0]: self.act_descend(p))
        elif not m and len(ups) >= 2 and not self.run.get('soko_done') and not near and hp >= 0.7 * hpmax and (s.get('turn') or 0) - self.run.get('unicorn_left', -999) > 300:
            p = max(ups, key=lambda u: cheb(u, lv.arrival or me))
            opts = {k2: v for k2, v in opts.items() if k2 == 'pray' or k2.startswith('eat_')}
            opts['enter_sokoban'] = ('Go up into Sokoban', f"This level has a second up staircase ({dist[p]} steps {compass(me, p)}): it leads to Sokoban, four puzzle levels with a known solution, safe food, rings, wands and a bag of holding or amulet of reflection at the top.", lambda p=p: self.act_descend(p, '<'))
        nexit = (downs[0], '>') if downs and s.get('dlvl', 1) <= (s.get('xl') or 1) else (ups[0], '<') if ups and s.get('dlvl', 1) > 1 else None  # XL3 on Dlvl 4: '>' was past pace, so Jev stayed 2000 turns while one wood nymph took 12 items incl. shield and spear, then died bare-handed (T3162)
        if nexit and nexit[1] == '<' and self.run.get('nymph_lvl') == s.get('dlvl'):  # up then straight back down: leave_nymph/descend ping-ponged Dlvl 10 <-> 9 for 400 turns, Weak with no food, fainted beside a barrow wight (T9310)
            nexit = None  # the elif below explores for '>' instead
        if self.run.get('nymph_lvl') == s.get('dlvl') and not hops and nexit and not near and not m and s.get('hp', 1) >= 0.8 * s.get('hpmax', 1):  # left at 38/55 into a Woodland-elf + Mordor orc: 38 -> 7 in 2 turns (T5934)
            # a nymph teleports back for more: one wood nymph took shield, spear, bag, ration and egg over 500 turns
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('eat_')}
            opts['leave_nymph'] = ('Leave this level (a nymph lives here)', f"A nymph on this level keeps coming back to steal your things. Walk to the staircase ({dist.get(nexit[0], 0)} steps) and leave.", lambda e=nexit: self.act_descend(e[0], e[1], stop_new=False))
        elif self.run.get('nymph_lvl') == s.get('dlvl') and not downs and not near:  # downstairs unknown: 1000 turns on a nymph level, five thefts (shield, mithril, shield, helm, daggers), AC 10, killed by a wolf (T4895)
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith(('eat_', 'explore', 'door_', 'search')) or k == 'rest' and s.get('hp', 1) * 2 < s.get('hpmax', 1)} or opts  # rest: at 6/51 this sent Jev exploring into a fire ant (T3848)
        if were_throw in opts and not any(m['dist'] <= 1 for m in hostiles):
            opts = {k: v for k, v in opts.items() if k.startswith(('throw_', 'zap_')) or k in ('elbereth', 'pray') or k.startswith('quaff_')}
        # meleed an animal-form werewolf from 63/63: bitten, feverish, became a wolf 34 turns later, burst out of the splint mail, dead at AC 10 (T2110). wiki: never melee one; Elbereth scares the animal form
        if not self.run.get('lycanthropy') and any(m['dist'] <= 1 and 'were' in m['name'] and m['ch'] != '@' for m in hostiles) and ('elbereth' in opts or self.engraved_here()):
            opts = {k: v for k, v in opts.items() if not k.startswith('attack_')} or opts
        if nymph_throw in opts and not any(m['dist'] <= 1 for m in hostiles):  # forced to throw at a nymph, a fire ant ate Jev at 10 HP
            opts = {k: v for k, v in opts.items() if k in (nymph_throw, 'pray') or k.startswith('eat_')}
        nym = [m['pos'] for m in hostiles if 'nymph' in m['name']]
        if nym != (self.run.get('nymph_still') or [None])[0]:
            self.run['nymph_still'] = (nym, s.get('turn') or 0)
        asleep = nym and (s.get('turn') or 0) - self.run['nymph_still'][1] >= 30  # a sleeping water nymph 2 steps off: 850 turns on Elbereth, starved (T3534); Valkyries are stealthy, walk on
        if not asleep and sum(h['choice'] == 'wait' for h in self.history[-80:]) < 70 and any('nymph' in m['name'] and m['dist'] <= 3 for m in hostiles) and not any(m['ch'] == '@' and m['dist'] <= 3 for m in hostiles) and (not shot or hp * 2 > hpmax):  # a hobbit's thrown dagger switched this off at 48/48: Jev attacked off Elbereth, the nymph took its armor, dead at AC 10 (T1554)  # nymphs respect Elbereth and steal by melee: one froze Jev and took spear + scale mail in a turn, AC 10, dead (T4896); four nymph-stripped deaths
            stuck = sum(h['choice'] == 'wait' for h in self.history[-40:]) >= 30  # 116 turns on Elbereth held off a mountain nymph while zombies, orcs and a jaguar gathered: charmed out of the banded mail mid-mob, dead from 48 HP (T5019)
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_') or k.startswith('zap_') and 'nymph' in v[0] or stuck and k == nymph_throw or k.startswith('wear_') and self.engraved_here() and not any(m['dist'] <= 1 for m in hostiles)} | ({'wait': ('Stay on Elbereth one turn', 'A nymph is near: she cannot steal from you while you stand on Elbereth.', self.act_wait_elbereth)} if self.engraved_here() else {'elbereth': ('Engrave Elbereth', 'A nymph is near: she steals armor and weapons by touch, but will not melee you on Elbereth.', self.act_elbereth)})  # charmed out of suit and shield beside a nymph: 300 turns at AC 10 on Elbereth with both in the pack, jaguar (T5123)
        if 'ascend' in opts and not any(m['dist'] <= 3 and not m['passive'] for m in hostiles) and s.get('hunger') not in ('Hungry', 'Weak', 'Fainting'):  # two rothes 2 steps off: forced to walk for '<', 46 -> 10, died praying (T2767)  # hungry descents were forced back up: 33 ascends/14 descends while starving (T3603)  # offered only, Jev rarely took it: 25 of 60 deaths were 2+ levels past XL
            opts = {k: v for k, v in opts.items() if k in ('ascend', 'pray') or k.startswith(('eat_', 'quaff_'))}
        # stall guard: an option picked 3 times in a row without the game clock moving is not working
        streak = []
        for h in reversed(self.history):
            if h['turn'] != s.get('turn'):
                break
            streak.append(h['choice'])
        if len(streak) >= 3 and len(set(streak[:3])) == 1:
            opts.pop(streak[0], None)
        if s.get('hunger') in ('Weak', 'Fainting') and not any(m['dist'] <= (7 if self.engraved_here() and s.get('hp', 1) * 2 < s.get('hpmax', 1) and s.get('hunger') == 'Weak' else 3) and not m['passive'] for m in hostiles):  # Weak at 21/54 left Elbereth to fetch food 33 steps off, a fire ant 5 steps away: 21 -> 4 (T4193)  # dist<=1 forced 'fetch' food off Elbereth past a rothe and elf zombie 2 steps away: 35 -> 0 (T4576)
            # sat 69 turns on Elbereth Weak -> Fainting with food in view, dead (T2958); wiki: Weak is major trouble, eat or pray
            food = {k: v for k, v in opts.items() if k == 'pray' or k.startswith(('eat_', 'goto_corpse')) or k == 'fetch' and '(food?)' in v[0]}
            opts = food or {k: v for k, v in opts.items() if k != 'rest' and not (s.get('hunger') == 'Fainting' and k.startswith('approach_'))} or opts  # Fainting closed in on an Uruk-hai, fainted beside it (T3278)  # rested 9 times Weak -> Fainting with food 20 steps off, past fetch's 15-step radius (T2773)
        if s.get('hunger') == 'Hungry' and not near:  # food is offered but passed up for exploring until Weak: 4 of the last 6 deaths fainted (T2801)
            opts = {k: v for k, v in opts.items() if k.startswith(('eat_', 'goto_corpse', 'buy_')) or k in ('pray', 'shop_food') or k == 'fetch' and '(food?)' in v[0]} or opts
        if s.get('hunger') in ('Weak', 'Fainting') and 'pray' not in opts and s.get('hp', 1) * 3 > s.get('hpmax', 1):  # no prayer, so waiting only starves: sat 60 turns on Elbereth at 25-32/65 Weak -> Fainting beside a weak orc shaman, fainted, fire ant (T5305)
            opts = {k: v for k, v in opts.items() if k not in ('wait', 'rest')} or opts
        if 'elbereth' in opts:  # at 4/54 Jev drank an unknown potion over Elbereth: sleeping, a fire ant killed it frozen (T4193)
            opts = {k: v for k, v in opts.items() if not k.startswith('quaff_') or 'healing' in v[0]}
        if s.get('hunger') in ('Weak', 'Fainting') and 'pray' in opts:  # Weak with an unseen thing 1 step off skipped the food filter: rested over a safe prayer, fainted, rothe (T3180)
            opts.pop('rest', None)
            if not any(k.startswith(('eat_', 'goto_corpse')) for k in opts):
                opts = {'pray': opts['pray']}  # Weak at low HP 844 turns after a prayer, offered 'pray' 4 times: swung at bees and descended instead, fainted, dead (T3493)
        if (s.get('turn') or 0) - self.run.get('held', -99) <= 2:  # owlbear crush: '<' tried 4 times 'held, and cannot go up', 82 -> 0 (T12770)
            # held: moving escapes 1 in 40 (hack.c); a rope golem choked Jev through 3 retreats (T5125). Wiki: Elbereth works while grabbed
            opts = {k: v for k, v in opts.items() if k in ('elbereth', 'pray') or k.startswith(('attack_', 'quaff_', 'zap_'))} or opts  # an uncursed wand of fire stayed unzapped while two rope golems choked Jev 70 -> 0 (T5699)
        if any(m['dist'] <= 1 and not m['passive'] for m in hostiles) and any(k.startswith(('attack_', 'flee_up', 'upstairs', 'retreat')) for k in opts):  # flee_up drops attacks, then explore was added back: explored 4 times beside Woodland-elves (T3567)  # explored away from 5 adjacent rats at 21/29: dead (T1354)
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore_', 'search', 'throw_', 'pickup_', 'fetch', 'door_'))}  # picked up loot 3 times with Woodland-elves hitting (T6490); threw daggers at a far orc-captain with a giant spider adjacent: 19 -> 8 HP, dead (T4825); walked for a locked door 3 times inside a wererat's rat swarm: 17 -> 0 (T5245)
        adj = [m for m in hostiles if m['dist'] <= 1 and not m['passive']]  # not adjacent yet: at 14/41 threw darts at an approaching hill-orc band, Elbereth next turn was interrupted, dead (T3736)
        prev = next((h for h in self.history[-2:-1] if h.get('hp') and (s.get('turn') or 0) - h['turn'] <= 3), None)
        losing = prev and prev['hp'] - s.get('hp', 0) >= s.get('hp', 0)  # an ape + pony took 34 -> 14 in two turns, Jev swung on with Elbereth offered: dead next turn (T3767)
        if 'elbereth' in opts and (not adj and s.get('hp', 1) < 0.4 * s.get('hpmax', 1) and sum(m['dist'] <= 4 and not m['passive'] for m in hostiles) >= 2 or adj and (len(adj) >= 2 and s.get('hp', 1) * 2 < s.get('hpmax', 1) or losing or pack and len(adj) >= 3 or sum(m['dist'] <= 2 and not m['passive'] for m in hostiles) >= 2 and s.get('hp', 1) < 0.6 * s.get('hpmax', 1) or s.get('hp', 1) < 0.6 * s.get('hpmax', 1) and any('stronger' in self.threat(m) for m in adj) or s.get('hp', 1) < 0.4 * s.get('hpmax', 1))) and not any(m['ch'] == '@' or 'minotaur' in m['name'] for m in adj) and not shot:  # shot: an Uruk-hai zapped magic missiles past its friend while this left only Elbereth (useless vs wands), 17 -> 3, dead (T6851)  # an Uruk-hai pack, 2 adjacent: swung from 44/66 to 23 with Elbereth on offer, then garbled, dead (T4643)  # swung at a giant ant (speed 18) from 23/62 to 14 with Elbereth on offer, then garbled + interrupted, dead (T5591)  # XL4 swung at a rope golem at 22/43 with Elbereth on offer: 22 -> 10, a snake interrupted the late engraving, dead (T2908)  # traded blows with 3 wolves 70 -> 6 with Elbereth on offer, died praying (T4527)
            opts = {k: v for k, v in opts.items() if k in ('elbereth', 'pray', 'upstairs', 'dig_down') or k == 'flee_up' and (outrun or any(dist.get(p, 99) <= 3 for p in snap.find('<'))) or k.startswith('quaff_')}  # '<' 3 steps: a magic trap blinded Jev and summoned hill orcs, a pony and a wolf beside it; only Elbereth, interrupted, 48 -> 0 (T5706)  # upstairs: arrived on '<' into ~10 monsters, only Elbereth left, 67 -> 8 -> prayed -> dead (T8603)
        g = self.run.get('gear_at')
        if g and g[0] == s.get('dlvl') and s.get('exp') is not None and not any(m['dist'] <= 1 for m in near):  # 'not near': a speed-3 rock mole stayed in view 230 turns, the shield never recovered, dead at AC 10 (T3665)
            if me == g[1]:
                pile = [q for c in ')[' for q in snap.find(c) if 0 < cheb(me, q) <= 3 and q in dist]
                self.run['gear_at'] = None if self.here_items() or not pile else (g[0], min(pile, key=dist.get))  # the pickup and wear options take it from here; the spot was recorded a step off, empty square cleared it and Jev descended with no spear or shield, AC 9, dead to a werejackal (T6987)
            elif g[1] in dist:
                if not near or (s.get('ac') or 0) >= 9:  # back from rat form at AC 10, a wererat 2 steps off: closed in instead, a rat pack took 48 -> 6, dead (T3091)
                    opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith(('eat_', 'pickup_', 'wear_', 'wield_'))}
                opts['recover_gear'] = ('Go back for your dropped armor', f"Your armor and weapon fell off when you changed form. They lie {dist[g[1]]} steps {compass(me, g[1])}: walk there, pick them up and put them back on.", lambda p=g[1]: self.act_go(p))
        tp = next((it for it in self.inventory if 'scroll of teleportation' in it['text']), None)
        # unknown scrolls are never read (operator rule; the emergency read could be fire, amnesia, punishment or create monster)
        if tp and 'pray' not in opts and s.get('hp', 1) * 2 < s.get('hpmax', 1) and (near or self.unseen_attacker()) and not self.soko():
            opts['teleport'] = (f"Read {tp['text']}", 'Teleports you to a random spot on this level, away from whatever is hurting you.', lambda l=tp['letter']: self.act_read(l))
        tw = next((it for it in self.inventory if 'wand of teleportation' in it['text'] and not re.search(r':0\)', it['text'])), None)
        if tw and 'teleport' not in opts and 'pray' not in opts and not self.soko() and (s.get('hp', 1) * 2 < s.get('hpmax', 1) and (near or self.unseen_attacker()) or s.get('hp', 1) < 0.7 * s.get('hpmax', 1) and any(m['dist'] <= 1 and 'stronger' in self.threat(m) for m in near)):  # a known wand of teleportation sat unused while a Green-elf and a soldier ant took 43 -> 0 at XL 5 (T3107); wiki (Escape items): zap yourself
            opts['teleport'] = (f"Zap {tw['text']} at yourself", 'Teleports you to a random spot on this level, away from everything hurting you.', lambda l=tw['letter']: (self.act_keys('z' + l + '.', 'teleported'), self.read_inventory())[0])
        # a mumak (stronger), an ogre and a soldier ant adjacent, prayer 75 turns old: the wand was offered only at 4 HP, dead mid-zap (T7569)
        mob = 'pray' not in opts and sum(m['dist'] <= 1 for m in near) >= 2 and any(m['dist'] <= 1 and 'stronger' in self.threat(m) for m in near)
        dig = next((it for it in self.inventory if 'wand of digging' in it['text'] and not re.search(r':0\)', it['text'])), None)
        if dig and (s.get('turn') or 0) - self.run.get('held', -99) > 1 and (s.get('hp', 1) * 2 < s.get('hpmax', 1) and any(m['dist'] <= 1 for m in near) or mob or not downs and not near and s.get('hunger') in ('Hungry', 'Weak', 'Fainting') and not any(FOOD.search(it['text']) for it in self.inventory)) and not self.soko() and self.standing_on() not in ('<', '>', '_', '\\', '{'):  # starving: fainted searching walls for 400 turns with this wand in the pack, dead to a goblin (T6106)  # a hill orc pack, a wand of digging unused, gamble prayer failed, dead (T2926)
            opts['dig_down'] = (f"Zap {dig['text']} down", 'Dig a hole through the floor and fall to the level below, leaving every monster here behind.', lambda l=dig['letter']: (self.act_keys('z' + l + '>', 'dug down'), self.read_inventory())[0])  # held: "You are being held, and cannot go down" x12 while a rope golem choked 47 -> 0 (T14075)
            if mob:
                opts = {k: v for k, v in opts.items() if not k.startswith(('attack_', 'elbereth'))}
        if 'pray' not in opts and s.get('hp', 1) * 3 < s.get('hpmax', 1) and any(k.startswith(('zap_', 'teleport', 'dig_down')) for k in opts):  # an unknown wand sat unzapped while a Woodland-elf meleed 30 -> 2, prayer 90 turns old (T5409)
            opts = {k: v for k, v in opts.items() if k.startswith(('zap_', 'quaff_', 'flee')) or k in ('elbereth', 'upstairs', 'ascend', 'teleport', 'dig_down')}
            if any(re.search(r'zaps (a|an) [\w ]*wand', r) for r in self.run['recent'][-3:]) and any(k.startswith(('zap_', 'teleport', 'dig_down')) for k in opts):
                opts.pop('elbereth', None)  # monmove.c m_move then mhitu.c find_offensive: a scared monster steps off and zaps from range; engraved beside a hill orc with a wand of striking at 12/62 over its own wand, dead (T6827)
        if any(m['dist'] == 1 and (MONSTERS.get(self.species(m)) or [0, 0])[1] >= 15 and not m['passive'] for m in hostiles) and any(k.startswith('attack_') for k in opts) and s.get('hp', 1) * 3 >= s.get('hpmax', 1):
            opts.pop('elbereth', None)  # engrave.c: engraving is an occupation that a hit interrupts; a soldier ant (speed 18) stung through it 43 -> 0 (T6798)
        shooter_adj = [m for m in hostiles if m['dist'] == 1 and m['name'] == self.run.get('shooter')]
        if shooter_adj and any(re.search(r'\b(shoots|throws|zaps)\b', r) for r in self.run['recent'][-3:]) and any(k.startswith('attack_') for k in opts):
            opts.pop('elbereth', None)  # a scared Uruk-hai beside the Elbereth square kept shooting poisoned arrows: engraved instead of hitting it at 16 HP, dead (T4657)
        if self.unseen_attacker():  # a fire ant bit from a square the map showed empty; 3 x 15-turn searches and explores, 47 -> 8, prayed too soon (T3879)
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'search', 'rest', 'door_', 'goto_', 'choke'))} or opts
            if not any(m['dist'] <= 1 for m in hostiles) and 'Blind' not in s.get('conditions', []):  # detect.c: searching maps an adjacent invisible monster as 'I', which gets an attack option
                opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'retreat'))}  # invisible Woodland-elves (ignore Elbereth): retreat/explore 4 times with no 'I' adjacent, 60 -> 0 (T6670)
                opts['find_unseen'] = ('Search one turn to find the unseen attacker', 'Something invisible is hitting you. Searching marks adjacent invisible monsters with an I so you can attack that square; walking away gives it free hits.', lambda: self.act_keys('s', 'searched'))
        adj = [m for m in hostiles if m['dist'] <= 1]
        if 'elbereth' in opts and hp < 0.7 * hpmax and any('put to sleep' in r for r in self.run['recent'][-3:]) and not any(m['ch'] == '@' for m in adj):
            opts = {k: v for k, v in opts.items() if not k.startswith('attack_')}  # asleep you take every bite free: a homunculus slept an armorless Jev 25 -> 6 while it swung instead of engraving (T2171)
        if adj and all((MONSTERS.get(self.species(m)) or [0, 99])[1] <= 3 and 'lichen' not in m['name'] for m in adj) and hp < 0.7 * hpmax and 'pray' not in opts and s.get('hunger') not in ('Weak', 'Fainting') and (s.get('turn') or 0) - self.run.get('held', -99) > 2 and self.retreat_dir(hostiles):  # stuck to a giant mimic: 'retreat' was the only option, 6 times 'You cannot escape', 62 -> 0 (T4379); monmove.c monflee releases the hero, so Elbereth or a fight it is  # starving: the slow thing is dinner; fainting with Tyr angry, Jev walked away from a rock mole 6 times and fainted to death (T6255)  # mimics (speed 3) hit through Elbereth (cornered: monmove.c panicattk); 100 turns re-engraving beside two drew a bones-level horde, dead (T4328)
            opts = {'retreat': ('Walk away from the slow monster', 'Step away: everything next to you moves at speed 3 or less, so two steps leave it behind for good.', lambda: self.act_retreat(hostiles))}
        if (s.get('turn') or 0) - self.run.get('held', -99) <= 2:  # held: 'flee_up' then 'retreat' never moved (T4379)
            opts = {k: v for k, v in opts.items() if not k.startswith(('retreat', 'flee'))}
            for m in [] if opts else adj:  # stuck to a giant mimic on burned Elbereth, only 'retreat' and 'flee_up' were left: 30 -> 13 (T2998)
                d = DIR_OF[(m['pos'][0] - me[0], m['pos'][1] - me[1])]
                opts[f'attack_{d}'] = (f"Attack {m['name']} ({DIR_NAME[d]})", 'You are stuck to it and cannot move away. Kill it.', lambda d=d: self.act_fight(d))
        if sum(m['dist'] <= 3 for m in near) >= 3:  # held a doorway against 15 Mines monsters, a kill left no one adjacent and explore stepped into the room: 22 -> 5 HP in 2 turns (T2970)
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'door_', 'search', 'goto_'))} or opts
        if near and 'wait' in opts and self.engraved_here() and s.get('hp', 1) * 2 < s.get('hpmax', 1):  # explored off Elbereth at 12/63 among 8 monsters, 3 times 'took damage after 1 steps' (T7921)
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'door_', 'sell_', 'approach_', 'fetch')) or k == charge}
        if charge in opts and sum(h['choice'].startswith('approach_') for h in self.history[-4:]) >= 2 and not any(m['dist'] <= 2 and m['name'] == self.run.get('shooter') for m in hostiles):
            del opts[charge]  # kited: a hill orc's returning aklys kept 4 steps off, forced 'close in' 3 times at 15-24/64 while an imp hit, dead (T4114)
        if charge in opts:
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'door_', 'sell_', 'fetch', 'wait', 'search', 'rest'))}
        if not near and ({'eat_corpse', 'goto_corpse'} & opts.keys()):  # the earlier forcing ran before explore/descend were added: 22 corpse offers, 2 taken, 4 hunger prayers, fainted (T3843)
            opts = {k: v for k, v in opts.items() if k in ('eat_corpse', 'goto_corpse', 'pray')}
        if self.history and 'blocked' in self.history[-1]['outcome'] and any(m['dist'] <= 1 for m in hostiles) and len(opts) > 1:
            opts.pop(self.history[-1]['choice'], None)  # hill orcs blocked the stairs path: 5 'ascend' bumps at 80/80 HP without a swing, dead (T6782)
        last = self.history[-5:]  # blocked walks cost a turn each, so the clock-frozen check misses them: 3500 turns bumping a shopkeeper past a floating eye
        if len(last) == 5 and len({h['choice'] for h in last}) == 1 and all('blocked' in h['outcome'] for h in last) and len(opts) > 1:
            opts.pop(last[0]['choice'], None)
        if len(streak) >= 4:  # several tries, clock frozen: everything tried this turn is failing
            for c in set(streak):
                if len(opts) > 1:
                    opts.pop(c, None)
        if s.get('hunger') in ('Hungry', 'Weak', 'Fainting') and not any(FOOD.search(it['text']) for it in self.inventory) and any(k == 'dig_down' or k.startswith(('door_', 'kick_', 'explore')) for k in opts):  # no food: searching walls only starves (picked search over a locked door 2 steps away while Fainting, T6106)
            opts = {k: v for k, v in opts.items() if k not in ('search_hidden', 'rest')}
        if downs or 'search_hidden' in opts and sum(lv.searched.values()) < 200:  # no stairs yet: search first; Asidonhopo's scuffed-sign shop door kicked at XL1 with search_hidden on offer, wand of striking (T596)  # a locked door can be a shop closed for inventory whose sign got scuffed: kicked one in, Mr. Kipawa killed Jev (runs before the empty guards: filtering after them left no options, 1100 turns searched)
            opts = {k: v for k, v in opts.items() if not (k.startswith('kick_') or 'locked door' in v[0])}
        if not opts and downs and s.get('dlvl', 1) >= (s.get('xl') or 1) + 1 and s.get('hunger') not in ('Hungry', 'Weak', 'Fainting') \
                and (sum(lv.searched.values()) < 400 or s.get('dlvl', 1) + 1 >= (s.get('xl') or 1) + 2 and sum(lv.searched.values()) < 800):  # 1500: ~95 pace rests = 1900 of 3200 turns waiting for XP, fainted to a dog (T3853); hunger was 5 of 12 deaths  # uncapped, an XL2 rested 91% of 8000 turns on Dlvl 3, living on prayers until one angered Tyr (T8071)  # 'anyway' to XL+2 just ping-pongs with the forced ascend (Green-elves, T5351)
            # Hungry is ~100 turns from Weak, where prayer takes over: Hungry 'anyway' took XL6 to Dlvl 8, ogre + giant spider (T5817)
            # 'anyway' took Jev past the pace limit 165 times in 60 games (median death XL5 on Dlvl 7): wait here for monsters and HP first
            opts['rest'] = ('Rest and search 20 turns', f"This level is cleared, but Dlvl {s.get('dlvl', 0) + 1} is too deep for experience level {s.get('xl')}. Wait here: wandering monsters bring experience, and HP recovers.", lambda: self.act_search(20))
        if any('yellow light' in m['name'] for m in hostiles):  # a 20-turn search with one 9 squares off (speed 15) never got interrupted: blinded, then a ghoul paralysed and killed Jev (T3521)
            opts.pop('rest', None)
        if (s.get('turn') or 0) - self.run.get('fled_up', -99) < 50 or s.get('exp') is None:  # polymorphed: as a 26-HP werewolf, Weak and Stressed, 'anyway' took it down twice into a werewolf's wolves, dead praying (T3894)  # fled a warg pack upstairs, walked straight back down into it (T5161)
            opts = {k: v for k, v in opts.items() if k not in ('descend', 'dig_down', 'leave_nymph')}
            downs = []
        if self.soko() and not self.run.get('soko_done'):  # a fresh replan offers no push that decision: 'anyway' walked out 3 times and burned every replan (T6359)
            downs = []
        if not opts and downs and not any(h['choice'] == 'ascend' for h in self.history[-8:]):  # ascend/'anyway' ping-ponged Minetown <-> Dlvl 7 for 300 Hungry turns, fainted, killed (T5236)  # the pace gate is advice; idle-searching a cleared level only burns food (one run searched 400+ turns in a corridor)
            opts['descend'] = ('Take the downstairs anyway', f"Nothing else is reachable on this level. Walk to the down staircase ({dist.get(downs[0], 0)} steps) and descend to Dlvl {s.get('dlvl', 0) + 1}.", lambda p=downs[0]: self.act_descend(p))
        if not opts and (s.get('turn') or 0) - self.run.get('fled_up', -99) < 50:  # '>' blocked after fleeing up, level done: 3500 random 'feel around' steps beside the stairs (T11530)
            opts['rest'] = ('Rest and search 20 turns', 'You just fled up from danger below and this level is done: rest here before going back down.', lambda: self.act_search(20))
        rec = self.run.get('recent', [])
        trap_i = max((i for i, t in enumerate(rec) if re.search(r'bear trap closes on your|caught in a bear trap', t)), default=-1)
        if trap_i > max((i for i, t in enumerate(rec) if 'wriggle free' in t), default=-1) and not any(m['dist'] <= 1 and not m['passive'] for m in hostiles):
            # hack.c trapmove: every diagonal move try frees a bear-trapped foot a step (orthogonal 1 in 5); searching never does. Searched 60 turns trapped 2 steps from '>', Weak -> Fainting, dead (T2566)
            d = next((k for k in 'yubn' if snap.at(me[0] + DIRS[k][0], me[1] + DIRS[k][1]).ch in '.#<>{_' and (me[0] + DIRS[k][0], me[1] + DIRS[k][1]) not in [m['pos'] for m in hostiles]), None)
            if d:
                opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith(('eat_', 'quaff_', 'attack_', 'throw_', 'zap_'))}
                opts['escape_trap'] = ('Pull free of the bear trap', 'Your foot is caught in a bear trap. Each diagonal move attempt loosens it; searching or waiting never does.', lambda d=d: self.act_escape_trap(d))
        if not opts:
            # nothing to do usually means level memory has walled us in (once for 7800 turns): forget it and look again
            lv.blocked.clear(); lv.dead.clear(); lv.near.clear()
            lv.resets += 1
            opts['wait'] = ('Wait one turn', 'Nothing else is possible right now; search in place for one turn.', lambda: self.act_keys('ms', 'waited'))
            # an unlit spot shows its neighbours blank, so no path leads anywhere: 2000 turns of 'wait' on Dlvl 7 (T11000-13200). Feel around instead
            dark = [k for k, v in DIRS.items() if (g := snap.at(me[0] + v[0], me[1] + v[1])) and (g.ch == ' ' or snap.walkable(me[0] + v[0], me[1] + v[1]))]
            if dark and sum(h['choice'] == 'wait' for h in self.history[-5:]) >= 3 and not hostiles:
                opts['wait'] = ('Feel around in the dark', 'Nothing is reachable on the map: step into an unseen square next to you.', lambda d=random.choice(dark): self.act_keys(d, 'stepped into the dark'))
            # a trap door dropped Jev into a shop closed for inventory: 10000 turns waiting at a locked door (T399-T10300). wiki: unlock it, teleport out, or kick it and pay 400zm
            if lv.resets > 300:
                d = next((k for k, v in DIRS.items() if not (v[0] and v[1]) and (me[0] + v[0], me[1] + v[1]) in lv.locked), None)
                if d:
                    opts = {f'kick_{d}': ('Kick the locked door', 'Trapped for hundreds of turns with no other way out.', lambda d=d: self.act_kick(d, force=True))}
        # Jev never picked "Wear" over exploring (194 offers after a monkey stole the shield) and has no wield option at all
        # never a known-cursed one (welded: a cursed orcish dagger over an uncursed dagger, killed by an ogre T4539); known-safe first at equal rank
        weapon = min((it for it in self.inventory if WEAPON.search(it['text']) and not re.search(r'(?<!un)cursed', it['text']) and it['text'] not in self.run.setdefault('unwieldable', set())),
                     key=lambda it: (WEAPON_RANK.index(WEAPON.search(it['text'])[1]), not re.search(r'uncursed|blessed', it['text'])), default=None)
        if weapon and self.inventory and not any('weapon in' in it['text'] for it in self.inventory):
            opts = {f"wield_{weapon['letter']}": (f"Wield {weapon['text']}", 'You are fighting bare-handed.', lambda l=weapon['letter']: self.act_wield(l))}
        elif not near and (art := next((it for it in self.inventory if 'named' in it['text'] and WEAPON.search(it['text']) and 'weapon in' not in it['text'] and it['text'] not in self.run['unwieldable']), None)):
            opts = {f"wield_{art['letter']}": (f"Wield {art['text']}", 'An artifact weapon beats anything else you carry.', lambda l=art['letter']: self.act_wield(l))}
        elif not near and any(k == 'wish' or k.startswith('wear_') for k in opts):  # an early {'wish'}-only filter dropped wear and later rest/explore came back: a wished-for GDSM sat unworn, 'wish' untaken 100 times, AC 5, fire ant (T4663)
            opts = {k: v for k, v in opts.items() if k == 'wish' or k.startswith('wear_')}
        elif not near and 'fetch_gear' in opts:
            opts = {k: v for k, v in opts.items() if k in ('fetch_gear', 'pray') or k.startswith('eat_')}
        if not near and ('rest' in opts or 'wait' in opts) and s.get('hp', 1) < (0.75 if (s.get('turn') or 0) - self.run.get('hit_turn', -99) <= 50 else 0.5) * s.get('hpmax', 1):  # explored on at 11/65 HP into a giant beetle  # a jaguar fled off Elbereth out of view, Jev explored at 27/54 into it: 28 -> 0 (T3976)
            opts = {k: v for k, v in opts.items() if not k.startswith(('explore', 'door', 'descend', 'approach', 'kick', 'goto', 'search'))}
        if (s.get('title') or '').startswith('Were'):  # animal form: armor falls off, paws can't wear or carry much
            opts = {k: v for k, v in opts.items() if not k.startswith(('pickup_', 'wear_', 'fetch'))}
        if any(k.startswith('explore') for k in opts) and not any(re.search(r'\b(key|lock pick|credit card)\b', it['text']) for it in self.inventory):
            opts = {k: v for k, v in opts.items() if not (k.startswith('door_') and tuple(map(int, k.split('_')[1:])) in self.level().locked)}  # a scuffed "Closed for inventory" sign: kicked in Cahersiveen's door with 3 explore options open, his wand, dead (T245)
        if 'Overloaded' in s.get('conditions', []):  # a wererat Jev tried to walk 291 times under a Valkyrie's pack  # stale inventory re-offered dropped items 20 times as a wererat, 'You don't have that object', bitten 34 -> 15 meanwhile, prayer spent, died (T5593)
            opts = {k: v for k, v in opts.items() if k == 'pray'}
            for it in self.inventory:
                if not re.search(r'weapon in|being worn|gold piece', it['text']):
                    opts[f"drop_{it['letter']}"] = (f"Drop {it['text']}", 'You are Overloaded and cannot move at all. Drop heavy things (armor, weapons, rations, tools) first.', lambda l=it['letter']: (self.act_keys('d' + l, 'dropped it'), self.read_inventory())[0])
        if not near and any(k.startswith('sell_') for k in opts):  # Jev chose "explore" into Chicoutimi 3000 times instead
            opts = {k: v for k, v in opts.items() if k.startswith('sell_')}
        if set(s.get('conditions', [])) & {'Conf', 'Cnf', 'Stun', 'Stn'} and (not near or any(m['peaceful'] and m['dist'] <= 1 for m in mons)):  # hack.c: Stunned always, Confusion 1 in 5 confdir()s the move or attack: a stunned swing at a mimic hit Izchak, dead (T2680)  # a confused bump into a shopkeeper attacks him
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_')} | {'rest': ('Wait until you are steady', 'You are confused or stunned: moves go in random directions and can attack peacefuls. Nothing hostile is near, so wait it out.', lambda: self.act_keys('5s', 'waited'))}
        if self.run.get('engulfed'):  # a flag: 'laden with moisture' spam pushed 'engulfs you' out of a 3-message window, Jev searched inside a fog cloud for 20 turns (T5756)
            # inside a vortex (shown as Blind) Jev chose 'wait until you can see' twice: 51 -> 13 HP, dead (T8226). Any hit lands on the engulfer.
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_')} | {'attack_k': ('Attack the monster engulfing you', 'You are engulfed: every attack hits the engulfer, and killing it or hurting it enough frees you. Waiting only lets it digest or burn you.', lambda: self.act_fight('k'))}
            dart = next((it for it in self.inventory if re.search(r'\b(daggers?|knives|darts?|shuriken)\b', it['text']) and 'weapon in' not in it['text']), None)
            if dart and self.run.get('engulfer') in ('energy vortex', 'fire vortex'):  # monsters.h: passive AT_NONE (lvl+1)d4 shock/fire on every melee hit; thrown missiles skip passive() (transcripts: a Valkyrie with Mjollnir died meleeing one)
                opts['attack_k'] = (f"Throw {dart['text']} at the {self.run['engulfer']}", 'Meleeing it zaps you back for 7-28 each hit; a thrown missile always hits the engulfer and takes no passive damage.', lambda it=dart: self.act_throw(it['letter'], 'k'))
        elif 'Blind' in s.get('conditions', []):  # a blind step into an unseen watchman angered the whole Minetown watch
            fight = {k: v for k, v in opts.items() if k in ('pray', 'elbereth') or k.startswith(('quaff_', 'attack_', 'eat', 'wield_', 'zap_'))}  # zaps point at the monster biting you: a blind Jev with a wand of cold only had 'swing', 62 -> 8, died praying (T5509)  # weaponless, opts was just 'wield': this dropped it and a blind Jev waited while a dog bit 37 -> 0 (T4631)  # blind engraving still scares: invisible quasits drained a blind Jev who could only swing
            # 'You feel an unseen monster' is just sensing: swung at it blind in Aklavik's store, and she zapped Jev dead (T3012)
            w = self.run.get('welcome') or (None, -999)  # blind on Zum Loch's door after a yellow light: swung at the felt shopkeeper, dead to her wand (T17928)
            shop = shop or (w[0] == s.get('dlvl') and turn - w[1] < 100)
            if (shop or lv.town) and not any(re.search(r"\b(It|The [a-z' -]+?) (hits|bites|touches|stings|butts|kicks|claws)", m) for m in self.run['recent'][-2:]):  # blind on a Mines level, 'The grid bug bites!' didn't count as being attacked: waited 55 -> 6 beside it and a rothe, died praying (T15494)  # blind swings at the unseen shopkeeper angered Ms. Tipor, twice-dead to her wand  # Minetown: swung at a felt 'I', a peaceful watchman: the watch killed Jev (T6313)
                fight = {k: v for k, v in fight.items() if not k.startswith(('attack_', 'zap_'))}
            # resting while unseen things bit a blind Jev from 54 to 4 HP (twice) is worse than swinging back
            if self.unseen_attacker() and not any(k.startswith(('attack_', 'wield_')) for k in fight):  # blind and Weak, bitten by unseen things with only pray/rest: rested 12 times 44 -> 21 (T2471)
                fight.pop('rest', None)
                if not self.engraved_here():
                    fight['elbereth'] = ('Engrave Elbereth', 'You are blind and something unseen is biting you. Engraving works blind and scares most monsters off.', self.act_elbereth)
            felt = [m for m in hostiles if m['dist'] == 1 and 'unseen' in m['name']]
            if felt and not shop and (s.get('turn') or 0) - self.run.get('engrave_interrupted', -99) <= 5:  # blind, 5 Elbereths in a row "interrupted" by unseen fire ants, never swung back: 36 -> 0 (T5164)
                fight.pop('elbereth', None)
                for m in felt:
                    d = DIR_OF[(m['pos'][0] - me[0], m['pos'][1] - me[1])]
                    fight.setdefault(f'attack_{d}', (f"Attack the unseen creature ({DIR_NAME[d]})", 'Engraving keeps getting interrupted by its attacks: fight back.', lambda d=d: self.act_fight(d)))
            opts = fight if any(k.startswith(('attack_', 'wield_', 'elbereth')) for k in fight) else fight | {'rest': ('Wait until you can see', 'You are blind: walking bumps into unseen monsters and attacks them, peaceful or not. Wait for your sight to return.', lambda: self.act_keys('5s', 'waited'))}
        # a pack at any HP: left a working Elbereth at 40/44 to throw at bugbears and a goblin gang, dead 4 turns later
        # Weak is only nutrition 1-50 (eat.c): 23 turns camping on Elbereth there fainted Jev into a kitten's jaws (T4709)
        duo = sum(m['dist'] <= 3 and not m['peaceful'] and 'weaker' not in self.threat(m) for m in hostiles) >= 2  # explored off a fresh Elbereth at 32/38 with a wolf and a lizard 2 steps off; the warg joined: 32 -> 0 in 3 turns (T3260)
        # fast and not weak: a soldier ant (speed 18) out of view for 10 turns, Jev left the Elbereth wait at 22/53 to rest 15 turns, it came back: 22 -> 0 (T7927)
        if any(('much stronger' in self.threat(m) or (MONSTERS.get(self.species(m)) or [0, 0])[1] >= 15 and 'weaker' not in self.threat(m)) and m['dist'] <= 7 for m in hostiles):
            self.run['scary_turn'] = s.get('turn') or 0
        scary = (s.get('turn') or 0) - self.run.get('scary_turn', -99) <= 20  # XL4 on Elbereth, a soldier ant stepped out of view: fetched an item at 36/36, it came back, 12-step run for '<', dead (T2653)
        if self.engraved_here() and s.get('hunger') not in ('Weak', 'Fainting') and (pack or duo or scary or s.get('hp', 1) < 0.75 * s.get('hpmax', 1)) and (scary or any(m['ch'] != '@' and m['dist'] <= 7 for m in hostiles)) \
                and not shot and not camped and not boxed and not any('not protecting' in h['outcome'] for h in self.history[-6:]) \
                and not (s.get('hunger') == 'Hungry' and not pack and sum(h['choice'] == 'wait' for h in self.history[-20:]) >= 15) \
                and not any((m['ch'] == '@' and ('were' not in m['name'] or m['dist'] <= 1) or 'minotaur' in m['name']) and m['dist'] <= 7 for m in hostiles):  # an adjacent wererat in @ form hit through it while only 'wait' was offered: 12 -> 0 (T8786)  # a were-@ summons rats/jackals that do respect it: left Elbereth at 24/36 for a wererat, summoned rats 25 -> 0 in 2 turns (T1818)  # a bugbear threw daggers at a waiting Jev (Elbereth only stops melee): 13 -> 0 (T2350)  # a Woodland-elf (ignores Elbereth) walked up to a waiting Jev: 36 -> 0 (T7182)
            # stepping off a working Elbereth at a third HP with rothes/apes in view ended two runs in one hour
            opts = {k: v for k, v in opts.items() if k in ('pray', 'teleport') or k == 'flee_up' and s.get('hp', 1) >= s.get('hpmax', 1) / 3 or k.startswith(('quaff_', 'eat', 'wear_'))} | {'wait': ('Stay on Elbereth one turn', 'You are hurt and monsters are in view; Elbereth keeps most of them off while you heal.', self.act_wait_elbereth)}  # flee_up only above a third: at 4/68 it stepped off a working Elbereth twice toward '<' 3 steps off, a jaguar (speed 15) caught it (T9280)  # flee_up kept: 16 forced waits at 55/55 Hungry 2 steps from '<' while an orc horde gathered; Weak, prayer failed, pony 55 -> 0 (T5858)
        # hit through Elbereth twice by a soldier ant, then 6 turns alternating Elbereth (2 garbled), wait and one attack: 58 -> 0 (T5688). Once it fails here, commit to fighting
        if any('not protecting' in h['outcome'] for h in self.history[-6:]) and any(k.startswith('attack_') for k in opts) and not any(k.startswith(('quaff_', 'zap_')) or k in ('pray', 'teleport', 'flee_up') for k in opts):
            opts = {k: v for k, v in opts.items() if k not in ('elbereth', 'wait')}
        # yellow light: its explosion is its attack (mhitu.c AT_EXPL); killing it does not explode (mon.c). On Elbereth in a crowd it can't flee, panic-attacks (monmove.c)
        # and blinds anyway: waited at 72/72 beside one, blinded, 3 unseen rothes 72 -> 0 (T5778). Wiki: kill it, or be blind already
        yl = [m for m in hostiles if 'yellow light' in m['name'] and m['dist'] == 1]
        cover = next((it for it in self.inventory if re.search(r'\b(blindfold|towel)\b', it['text'])), None)  # wiki (Yellow light): be blind already when it explodes
        stuck_on = cover and re.search(r'\bcursed\b', cover['text']) and 'uncursed' not in cover['text']  # 'R' fails on a cursed one: 3000+ unblind decisions on T3457 (run 202507)
        if stuck_on and 'being worn' in cover['text'] and (s.get('turn') or 0) - (self.run.get('prayed_turn') or -2000) > 1000:
            opts = {'pray': ('Pray to Tyr', 'A cursed towel/blindfold over your eyes is major trouble (pray.c TROUBLE_CURSED_BLINDFOLD): a safe prayer uncurses it.', self.act_pray)}
        elif cover and 'being worn' in cover['text'] and not stuck_on and not any('yellow light' in m['name'] for m in hostiles):
            opts = {'unblind': ('Take off the ' + cover['text'], 'No yellow light in view any more: see again.', lambda l=cover['letter']: (self.act_keys('R' + l, 'took it off'), self.read_inventory())[0])}
        elif yl and cover and 'Blind' not in s.get('conditions', []):  # melee missed one at 36/56: blinded, unseen fire ants, dead (T5164)
            opts = {'blindfold': ('Put on the ' + cover['text'], 'A yellow light is next to you: its explosion only blinds, so cover your eyes first and it does nothing.', lambda l=cover['letter']: (self.act_keys('P' + l, 'put it on'), self.read_inventory())[0])}
        elif yl and 'Blind' not in s.get('conditions', []) and not LOW_HP(s):
            d = DIR_OF[(yl[0]['pos'][0] - me[0], yl[0]['pos'][1] - me[1])]
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_')} | {f'attack_{d}': ('Kill the yellow light', 'It explodes and blinds you for 10-200 turns when it attacks, and cornered on Elbereth it still attacks. Killing it is safe: it only explodes as an attack.', lambda d=d: self.act_fight(d))}
        # a safe prayer fully heals; Jev chose Elbereth over it at 1 HP and died. 500+ turns on, rnz(350) - elapsed < 200 most of the time:
        # Jev threw darts at 8 HP instead of a 700-turn gamble and died (T5087)
        if 'elbereth' in opts and 'gamble' in opts.get('pray', ('',))[0] and (s.get('turn') or 0) - (self.run.get('prayed_turn') or 0) < 200 and len(opts) > 1:
            del opts['pray']  # 144 turns after praying, a wererat's rats at 10/50: the gamble over a ~72% Elbereth angered Tyr, dead (T1583)
        if LOW_HP(s) and 'pray' in opts:  # the gamble (100+ turns) is ~.5-.87: Jev engraved at 1 HP 478 turns after praying and died (T4535)
            # a gamble prayer is ~.6 at 250 turns (rnz(350) simulated); a known attack wand at the attacker beats it: pray-only at 8/62 with a wand of cold, dead (T5509)
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith('quaff_') and 'healing' in v[0] or k == 'dig_down' and 'gamble' in opts['pray'][0]
                    or k in ('elbereth', 'wait', 'teleport') and 'gamble' in opts['pray'][0] and turn - (self.run.get('prayed_turn') or 0) < 200  # pray-only on Elbereth 113 turns on: "Thou art arrogant", lost a level, dead (T7362) # rnz(350) is ~.5 at 100-200 turns vs ~.72 for a dust Elbereth: pray-only 123 turns on at 11/69 by a jaguar, dead (T7122)
                    or k.startswith('zap_') and 'gamble' in opts['pray'][0] and re.search(r'wand of (sleep|cold|fire|striking|magic missile|lightning)', v[0])}  # chose an unknown black potion over a ~.7 prayer at 8/43: dead (T3559)
            if 'gamble' in opts.get('pray', ('',))[0] and ('dig_down' in opts and 'Zap' in opts['dig_down'][0] or 'teleport' in opts):
                del opts['pray']  # a hole is sure, a prayer 290 turns on is not: chose the gamble over a wand of digging at 9 HP, a little dog bit it dead mid-prayer (T3624)
        if 'flee_up' in opts and len(opts) > 1 and all(h['choice'] == 'flee_up' and 'after 1 steps' in h['outcome'] for h in self.history[-2:]):
            opts.pop('flee_up')  # 4 one-step flee_ups between an elf mummy, a Woodland-elf and soldier ants, 55 -> 0, wand of fire and 2 healing potions unused (T8671)
        if 'flee_up' in opts and not any(dist.get(q, 99) <= 1 for q in self.snap.find('<')) \
                and any(m['dist'] <= 1 and m['ch'] not in '@&' and 'minotaur' not in m['name'] and (MONSTERS.get(self.species(m)) or [0, 0])[1] > 12 for m in hostiles):
            opts.pop('flee_up')  # walked for '<' with a jaguar (speed 15, 3 attacks) adjacent: 31 -> 14 -> 8 -> 0 in two steps, Elbereth unused (T3778)
        if LOW_HP(s) and 'teleport' in opts and 'pray' not in opts and any(m['dist'] <= 1 and not m['peaceful'] for m in hostiles):
            opts.pop('flee_up', None)  # walking off at 1/74 beside a Green-elf took a hit per step: dead with 13 unread scrolls (T7362)
        if s.get('hunger') in ('Weak', 'Fainting') and 'goto_corpse' in opts and not starving and not LOW_HP(s):  # Weak, a fresh corpse 10 steps off: dropped a helm, prayed 790 turns on (failed), explored, fainted, giant spider (T7451)
            opts = {k: v for k, v in opts.items() if k == 'goto_corpse' or k.startswith(('attack_', 'eat', 'elbereth', 'zap_', 'quaff_'))}
        if self.standing_on() == '_':  # engraving on an altar: 'How darest thou desecrate my altar!' (pray.c altar_wrath), or Luck loss on a cross-aligned one
            opts.pop('elbereth', None)
        if 'pray' in opts and 'fatal within' in opts['pray'][1]:  # FoodPois with prayer ready: Jev rested and walked for corpses until it died (T2090)
            opts = {'pray': opts['pray']}
        zapper = next((m for m in hostiles if shot and m['name'] == self.run.get('shooter') and m['dist'] >= 2 and any(re.search(rf"The {re.escape(m['name'])} zaps", x) for x in self.run['recent'][-6:])), None)
        inline = lambda p, q: p[0] == q[0] or p[1] == q[1] or abs(p[0] - q[0]) == abs(p[1] - q[1])
        if zapper and inline(me, zapper['pos']):  # a werewolf's wand of fire hit 3 times 49 -> 18 while Jev explored down its line, then wolves finished it (T6060); rays only travel in the 8 directions
            safe = [d for d, (dx, dy) in DIRS.items() if snap.walkable(me[0] + dx, me[1] + dy) and not snap.is_monster(me[0] + dx, me[1] + dy) and not inline((me[0] + dx, me[1] + dy), zapper['pos'])]
            if safe:
                d = max(safe, key=lambda d: cheb((me[0] + DIRS[d][0], me[1] + DIRS[d][1]), zapper['pos']))
                o = ('Step out of the line of fire', f"The {zapper['name']} {zapper['where']} is zapping a wand along this line; rays only go straight or diagonal. Step where it has no line to you.", lambda d=d: self.act_keys(d, 'dodged'))
                opts = {'dodge': o} if hp < 0.5 * hpmax and not any(m['dist'] <= 1 and not m['passive'] for m in hostiles) else \
                    {k: v for k, v in opts.items() if k in ('pray', 'upstairs', 'flee_up') or k.startswith(('attack_', 'quaff_', 'zap_'))} | {'dodge': o}  # 'find_unseen' searched twice in a quasit's wand-of-fire line on '<': 55 -> 33 -> 0 (T15223)
        if (s.get('turn') or 0) - self.run.get('msg_turn', 0) <= 2 and any(re.search(r'whizzes by you|You hear a nearby zap', m) for m in self.run['recent'][-2:]):
            # a monster drank invisibility ("chugging sound"), zapped death from out of view; find_unseen stood in the line, the second ray killed (T8536)
            st = [(p, k) for k, ps in (('<', ups), ('>', downs)) for p in ps if p == me or dist.get(p, 99) <= 8]
            steps = [d for d, (dx, dy) in DIRS.items() if snap.walkable(me[0] + dx, me[1] + dy) and not snap.is_monster(me[0] + dx, me[1] + dy)]
            if st:
                p, k = min(st, key=lambda e: dist.get(e[0], 0))
                opts['dodge'] = ('Leave by the stairs', 'Something unseen is zapping rays at you; leave this level.', lambda p=p, k=k: self.act_keys(k, 'left by the stairs') if p == me else self.act_descend(p, k, stop_new=False))
            elif steps:
                opts['dodge'] = ('Step out of the line of fire', 'Something unseen is zapping rays at you; never stand still in its line.', lambda d=random.choice(steps): self.act_keys(d, 'dodged'))
            if 'dodge' in opts:
                opts = {k: v for k, v in opts.items() if k in ('dodge', 'pray') or k.startswith(('attack_', 'quaff_'))}
        if shot and self.standing_on() == '<' and s.get('dlvl', 1) > 1 and hp < 0.7 * hpmax and 'dodge' not in opts:  # a fled hill orc zapped striking at an Elbereth on '<': 43 -> 21 -> 14 -> 0 with only 'wait' offered (T2894)
            opts = {k: v for k, v in opts.items() if k == 'pray' or k.startswith(('attack_', 'quaff_'))}
            opts['upstairs'] = ('Flee up the stairs', 'You are being shot or zapped and Elbereth does not stop that: climb the stairs you stand on.', lambda: self.flee_up(lambda: self.act_keys('<', 'went up')))
        if opts.get('pray', ('',))[0] == 'Pray to Tyr':  # a safe prayer fixes hunger with no 1-in-2 tripe vomiting (T3736)
            if s.get('hunger') == 'Weak' and not fatal and not LOW_HP(s) and not hostiles and any(k.startswith('eat_') for k in opts):
                del opts['pray']  # prayed Weak with a tripe ration and nothing in view; 131 turns on, blind, a rabid rat at 11/38, no prayer left: dead (T4302)
            else:
                opts = {k: v for k, v in opts.items() if not (k.startswith('eat_') and 'tripe' in v[0])} or opts
        if any(re.search(r'pick-axe|dwarvish mattock', it['text']) for it in self.inventory):  # operator: never a second one (heavy: 100/120 wt)
            opts = {k: v for k, v in opts.items() if not (k.startswith(('pickup_', 'buy_')) and re.search(r'pick-axe|dwarvish mattock', v[0]))}
        elif not any(m['dist'] <= 5 and not m['passive'] for m in hostiles) and s.get('hp', 1) >= 0.6 * s.get('hpmax', 1):
            pk = next((k for k, v in opts.items() if k.startswith('pickup_') and re.search(r'pick-axe|dwarvish mattock', v[0])), None)
            dw = next((m for m in mons if re.search(r'\bdwarf\b(?! zombie| mummy)', m['name'] or '')), None)
            if pk:
                opts = {pk: opts[pk]}
            elif dw and any(m['pet'] and m['dist'] <= 6 for m in mons) and lv.__dict__.setdefault('shadowed', 0) < 40:
                # operator tip: a pet kills a (peaceful) mining dwarf for us, and its pick-axe drops for the taking
                q = min((q for q in dist if cheb(q, dw['pos']) == 1), key=dist.get, default=None)
                if q is not None:
                    lv.shadowed += 1
                    opts = {'shadow_dwarf': (f"Follow the {dw['name']} and let your pet kill it", f"No pick-axe yet: stay beside the {dw['name']} {dw['where']} so your pet attacks it; dwarves often carry a pick-axe.",
                                             lambda q=q: self.act_go(q, steps=3) if q != me else self.act_keys('s', 'waited for the pet'))}
        # operator: a wand of speed monster: zap yourself (intrinsic Fast) and the pet, then break it (apply.c do_break_wand:
        # a rnd(4*charges) magic blast, then speed for every adjacent square), so only with no hostiles in view and HP to spare
        sw = next((it['letter'] for it in self.inventory if 'wand of speed monster' in it['text']), None)
        if sw and not hostiles and s.get('hp', 0) >= max(35, 0.7 * s.get('hpmax', 1)):
            pet = next((m for m in mons if m['pet'] and m['dist'] == 1), None)
            if not self.run.get('speed_self'):
                opts = {'speed_self': ("Zap the wand of speed monster at yourself", "A wand of speed monster zapped at yourself makes you permanently fast.",
                                       lambda: (self.run.__setitem__('speed_self', 1), self.act_keys('z' + sw + '.', 'zapped speed at myself'))[1])}
            elif pet and not self.run.get('speed_pet'):
                d = DIR_OF[(pet['pos'][0] - me[0], pet['pos'][1] - me[1])]
                opts = {'speed_pet': ("Zap the wand of speed monster at your pet", "A fast pet keeps up with you and kills more.",
                                      lambda d=d: (self.run.__setitem__('speed_pet', 1), self.act_keys('z' + sw + d, 'zapped speed at the pet'))[1])}
            elif pet or not any(m['pet'] for m in mons):
                opts = {'break_speed': ("Break the wand of speed monster", "Its job is done: break it.",
                                        lambda: self.act_keys('a' + sw + 'y', 'broke the wand of speed monster'))}
        # operator: lichen corpses never rot (eat.c nonrotting_corpse): carry a few as emergency food
        lichens = sum(int(m[1] or 1) for it in self.inventory for m in [re.match(r'(\d+ )?.*lichen corpse', it['text'])] if m)
        lk = next((k for k, v in opts.items() if k.startswith('pickup_') and 'lichen corpse' in v[0]), None)
        if lichens < 4 and not any(m['dist'] <= 1 and not m['passive'] for m in hostiles):
            if lk:
                opts = {lk: opts[lk]}
            elif (s.get('turn') or 0) - self.run.get('lichen_kill', -99) <= 3:
                q = next((q for q in snap.find('%') if cheb(q, me) == 1 and q in dist), None)
                if q:
                    opts = {'get_lichen': ('Step onto the lichen corpse', 'Lichen corpses never rot: pick it up as emergency food.', lambda q=q: self.act_go(q, steps=1))}
        darts = sum(int(m[1] or 1) for it in self.inventory for m in [re.match(r'(\d+ )?.*\bdarts?\b(?! trap)', it['text'])] if m)
        if darts >= 10:
            opts = {k: v for k, v in opts.items() if not (k.startswith('pickup_') and re.search(r'\bdarts?\b', v[0]))}
        elif not any(not m['passive'] for m in hostiles) and s.get('hp', 1) >= 0.7 * s.get('hpmax', 1) and not self.soko():
            # operator: farm a dart trap for ~10 darts. #untrap from beside it: success drops 50-rnl(50) darts (trap.c disarm_shooting_trap);
            # a "Whoops" walks us onto it for one dart (1d3; 1 in 6 poisoned, and poison is 1 in 30 deadly without resistance)
            kinds = lv.__dict__.setdefault('trap_kind', {})
            for q in snap.find('^'):
                if q not in kinds and q in dist and dist[q] <= 8:
                    kinds[q] = self.farlook(q)
            lv.__dict__.setdefault('dart_traps', set()).update(q for q, k in kinds.items() if 'dart trap' in k)
            tries = lv.__dict__.setdefault('untrap_tries', {})
            for trap in sorted(lv.dart_traps):
                q = min((q for q in dist if cheb(q, trap) == 1 and q not in lv.traps), key=dist.get, default=None)
                if q is not None and tries.get(trap, 0) < 15:
                    opts = {'untrap_darts': (f"Disarm the dart trap {compass(me, trap)} for darts", f"You carry {darts} darts. Stand beside the dart trap and #untrap it: success leaves a stack of darts to throw.", lambda trap=trap, q=q: self.act_untrap_darts(trap, q))}
                    break
        # 0.75 while rest is on offer: forced to the gold at 10/18 (XL1) after a rolling boulder, a second trap on the way, dead (T363)
        if 'fetch_gold' in opts and not any(not m['passive'] for m in hostiles) and s.get('hp', 1) >= (0.75 if 'rest' in opts else 0.5) * s.get('hpmax', 1) and s.get('hunger') not in ('Weak', 'Fainting'):
            opts = {'fetch_gold': opts['fetch_gold']}  # operator: gold buys priest protection, then 2000-4000 for shops; offered 45 times, taken 14, games ended at 16-160 gold
        rid = next((k for k, v in opts.items() if k.startswith('read_') and 'identify' in v[0]), None)  # operator: read identify as soon as anything major is unknown
        if rid and not hostiles and any(re.search(r'\b(wand|ring|amulet)\b(?! of| mail)|scrolls? labeled|potions?\b(?! of)', it['text']) and not re.search(r'\bcalled\b|\bnamed\b', it['text']) for it in self.inventory if it['letter'] != rid[5:]):
            opts = {rid: opts[rid]}
        prio = next((k for k, v in opts.items() if k.startswith(('pickup_', 'buy_')) and (UNLOCKER.search(v[0]) or 'unicorn horn' in v[0] or WEAPON.search(v[0]) and not any(WEAPON.search(it['text']) for it in self.inventory))), None)
        if prio and not hostiles:  # user: a key/lock pick and a unicorn horn are priority items
            opts = {prio: opts[prio]}
        eid = next((k for k in opts if k.startswith('engrave_id_')), None)
        if eid and not hostiles:  # offered 39 times, explore always won: a balsa wand rode unknown to a fainting death (T7765)
            opts = {eid: opts[eid]}
        if (s.get('ac') or 10) > 0 and (s.get('turn') or 0) - self.run.get('held', -99) > 2:  # user: shop mimics (large/giant: 3d4-3d6 sticky claws) are for a very strong AC; they move at 3, so walk off
            for m in hostiles:
                if 'mimic' in m['name']:
                    d = next((k for k, (dx, dy) in DIRS.items() if (me[0] + dx, me[1] + dy) == m['pos']), None)
                    rest = {k: v for k, v in opts.items() if k not in (f'attack_{d}', f"approach_{m['pos'][0]}_{m['pos'][1]}")}
                    opts = rest or opts
        if 'upstairs' in opts and (s.get('turn') or 0) - self.run.get('held', -99) > 2 and any(m['dist'] <= 3 and HUGGERS.search(m['name']) for m in hostiles):
            opts = {'upstairs': opts['upstairs']}  # on '<' with an owlbear 2 squares off: wait, then 'choke' walked off the stairs, hugged, crushed 65 -> 0 (T4640)
        recent = self.history[-12:]
        if sum(h['choice'] == 'elbereth' for h in recent) >= 4 and len(recent) == 12 and s.get('hp', 0) <= recent[0].get('hp', 0):  # user: 'stop using elbereth so much': 100+ turns of re-engraving in a room corner while HP fell 61 -> 21 (T11430)
            rest = {k: v for k, v in opts.items() if k != 'elbereth' and not v[0].startswith('Stay on Elbereth')}
            opts = rest if any(k.startswith(('attack_', 'choke', 'upstairs', 'flee', 'retreat', 'zap_', 'throw_', 'quaff_', 'pray')) for k in rest) else opts  # it isn't working: fight, move or use an item instead
        return opts, mons

    def search_spot(self, dist):
        snap, lv = self.snap, self.level()
        best = None
        # wiki (Searching): hidden passages lead to the unmapped part. 14000 turns on a Dlvl 3 searching the explored west half while the east half stayed blank (T15494)
        W, H = 80, MAP_BOT + 1
        acc = [[0] * (W + 1) for _ in range(H + 1)]
        for y in range(H):
            row = snap.lines[y] if y < len(snap.lines) else ''
            for x in range(W):
                acc[y + 1][x + 1] = acc[y][x + 1] + acc[y + 1][x] - acc[y][x] + (MAP_TOP <= y and (x >= len(row) or row[x] == ' '))
        blank = lambda x, y: (lambda x0, x1, y0, y1: acc[y1][x1] - acc[y0][x1] - acc[y1][x0] + acc[y0][x0])(max(0, x - 10), min(W, x + 11), max(0, y - 5), min(H, y + 6))
        sale = [q for (dl, q), v in self.run.get('here', {}).items() if dl == snap.status.get('dlvl') and any('for sale' in i for i in v)]
        for p, d in dist.items():
            if any(cheb(p, q) <= 2 for q in sale):
                continue  # mkroom.c: a shop has exactly one door, so its walls hide nothing; 317 searches mostly inside one, starved (T6390)
            walls = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and (g := snap.at(p[0] + dx, p[1] + dy)) is not None and g.ch in ' |-')
            exits = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and snap.walkable(p[0] + dx, p[1] + dy))
            if walls < 3:
                continue
            g = getattr(lv, 'ghost', None)
            if g and (snap.status.get('turn') or 0) - g[1] < 300 and cheb(p, g[0]) <= 8:
                continue  # speed 3 vs 12: searching 8+ squares away buys ~30 uninterrupted turns before it drifts back
            score = lv.searched.get(p, 0) * 2 + d / 4 - (8 if snap.at(*p).ch == '#' and exits <= 1 else 0) - walls - blank(*p) / 12
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

    def act_read(self, letter):
        self.t.send('r' + letter)
        for _ in range(5):  # scroll of identify: pick the first thing in its menu
            lines = self.t.lines()
            kind, _ = top_prompt(lines)
            if kind == 'menu':
                items = [m.groups() for l in lines for m in [re.search(r'(?:^|\s)([a-zA-Z]) - (.*)', l)] if m]  # the menu lists only unidentified things
                rank = lambda x: next((i for i, w in enumerate(('wand', 'amulet', 'ring', 'armor|mail|cloak|boots|gloves|helm|shield|pall|cape|robe|apron|tunic', 'potion', 'scroll', 'spellbook')) if re.search(w, x[1])), 9 if re.search(r'gem|stone|glass|rock', x[1]) else 8)
                pick = min(items, key=rank)[0] if items else None  # gems last: an identify spent on a black gem leaves the wands unknown
                self.t.send((pick or '') + '\r')
            elif kind == 'more':
                self.add_msg(messages_from('\n'.join(lines)))
                self.t.send('\r')
            else:
                break
        self.settle()
        self.observe()
        self.read_inventory()
        return 'read it: ' + (self.run['recent'][-1] if self.run['recent'] else '')

    def act_wear(self, it):
        # body armor goes under the cloak: take a worn cloak off first (a cursed one stays, and the wear fails below), put it back after
        cloak = next((i for i in self.inventory if re.search(r'cloak|wrapping|mantelet|faded pall|cape|robe|apron', i['text']) and 'being worn' in i['text']), None) if suit_ac(it['text']) is not None else None
        if cloak:
            self.act_keys('T' + cloak['letter'], '')
        self.act_keys('W' + it['letter'], '')
        if cloak:
            self.act_keys('W' + cloak['letter'], '')
        self.read_inventory()
        now = next((i['text'] for i in self.inventory if i['letter'] == it['letter']), '')
        if 'being worn' in now:
            return 'wore armor'
        self.run['unwearable'][it['text']] = self.snap.status.get('ac') or 0  # wrong slot taken, two-handed weapon, too big...: stop offering it
        return 'could not wear it: ' + (self.run['recent'][-1] if self.run['recent'] else '')

    def act_untrap_darts(self, trap, q):
        lv = self.level()
        r = self.act_go(q)
        if self.snap.me != q:
            lv.untrap_tries[trap] = lv.untrap_tries.get(trap, 0) + 1
            return 'going to the dart trap: ' + r
        lv.untrap_tries[trap] = lv.untrap_tries.get(trap, 0) + 1
        self.act_keys('#untrap\r' + DIR_OF[(trap[0] - q[0], trap[1] - q[1])], '')
        news = ' | '.join(self.run['recent'][-3:])
        if 'You disarm' in news or self.snap.me == trap:  # disarmed, or "Whoops..." walked us onto it (a missed dart lies here)
            lv.dart_traps.discard(trap) if 'You disarm' in news else None
            self.act_go(trap, steps=1)
            dart = next((i for i in self.here_items() if re.search(r'\bdarts?\b', i)), None)
            if self.snap.me == trap and dart:
                self.act_pickup(dart)
                it = next((i for i in self.inventory if re.match(r'(\d+) .*\bdarts\b', i['text'])), None)
                if it and int(it['text'].split()[0]) > 10:
                    self.act_keys('d' + str(int(it['text'].split()[0]) - 10) + it['letter'], '')  # keep 10 (operator)
                    self.read_inventory()
        return 'untrap: ' + news[-120:]

    def act_fetch_gold(self, q):
        r = self.act_go(q)
        if self.snap.me != q:  # unreachable '$' (seen across rock): 6 blocked walks in a row (T2647)
            k = (self.snap.status.get('dlvl'), q)
            self.run['gold_miss'][k] = self.run['gold_miss'].get(k, 0) + 1
        return r

    def enhance(self):
        self.t.send('#enhance\r')
        time.sleep(0.3)
        lines = self.t.lines()
        if any('Pick a skill to advance' in l for l in lines):
            picks = [m for l in lines for m in re.finditer(r'(?:^|\s)([a-z]) - \s*([a-z][a-z -]+?)\s+\[', l)]
            wield = next((it['text'] for it in self.inventory if 'weapon in' in it['text']), '')
            pick = next((m for m in picks if m[2].strip().rstrip('s') in wield), picks[0] if picks else None)
            if pick:
                self.t.send(pick[1])
                time.sleep(0.3)
                if any('Pick a skill' in l for l in self.t.lines()):
                    self.t.send('\r')
                self.log(f'enhanced {pick[2].strip()}')
        self.t.send('\x1b')
        self.observe()

    def act_donate(self, pos):
        me = self.snap.me
        if cheb(me, pos) > 1:
            return 'toward the priest: ' + self.act_go(pos, adjacent_ok=True)
        self.t.send('#chat\r')
        self.t.send(DIR_OF[(pos[0] - me[0], pos[1] - me[1])])
        top = ' '.join(self.t.lines()[:2])
        m = re.search(r'suggested: (\d+) or (\d+)', top)
        if not m:
            self.t.send('\x1b')
            self.observe()
            return 'chatted: ' + ' | '.join(self.run['recent'][-2:])
        a, b = map(int, m.groups())
        gold = self.snap.status.get('gold', 0)
        offer = b if gold >= b else a if gold >= a else gold  # under a with more than 2x left over is 'Cheapskate' (raises the price); all of it is safe
        self.t.send(f'{offer}\r')
        self.observe()
        if offer == b:
            self.run['protection'] = self.run.get('protection', 0) + 1
        return f'offered {offer} (suggested {a} or {b}): ' + ' | '.join(self.run['recent'][-2:])

    def act_pay(self):
        self.t.send('p')
        time.sleep(0.5)
        if any('Pay for which' in l for l in self.t.lines()):  # used-up items (eaten shop food) come as a menu; settle() would Esc it
            self.t.send('.\r')
            time.sleep(0.5)
        raw = ' | '.join(l.strip() for l in self.t.lines()[:3] if l.strip())
        self.observe()
        return 'paid: ' + raw

    def act_stash(self, letter, text, q):
        r = self.act_go(q)
        if self.snap.me != q:
            return r
        self.act_keys('d' + letter, 'dropped')
        self.run.setdefault('stashes', {}).setdefault((self.snap.status.get('dlvl'), q), []).append(text)
        self.level().notes.add('stash')
        return f'stashed {text} by the up stairs'

    def act_keys(self, keys, what):
        before = self.snap
        inv = {i['letter']: i['text'] for i in self.inventory}
        self.t.send(keys)
        self.after_move(before)
        if keys[:1] == 'z' and keys[1:2] in inv and any(re.search(r'(?<!Unfortunately, n)Nothing happens', m) for m in self.run['recent'][-3:]):
            self.run.setdefault('empty_wands', set()).add(inv[keys[1]])  # zap.c dozap: !zappable -> "Nothing happens": 5 zaps of an empty wand of teleportation beside a jaguar, dead (T7489)
        return what

    def act_escape_trap(self, d):
        me, hp = self.snap.me, self.snap.status.get('hp')
        for _ in range(8):  # trap.c: rn1(4, 4) diagonal tries at most
            self.act_keys(d, '')
            if any('wriggle free' in t for t in self.run['recent'][-2:]) or self.snap.me != me:
                return 'pulled free of the bear trap'
            if self.snap.status.get('hp') != hp:
                return 'took damage while caught in the bear trap'
        return 'still caught in the bear trap'

    def act_fight(self, d):
        before = self.snap
        self.t.send('F' + d)
        self.after_move(before)
        self.run['elbereth'].discard((before.status.get('dlvl'), before.me))
        recent = ' '.join(self.run['recent'][-2:])
        q = (before.me[0] + DIRS[d][0], before.me[1] + DIRS[d][1]) if before.me else None
        if q and 'You kill' in recent and self.snap.at(*q) and self.snap.at(*q).ch in OBJECT_CHARS - {'%'} and not any(re.search(rf'You kill the [\w -]*{n}', recent) for n in self.never_eat()):
            self.level().corpses[q] = self.snap.status.get('turn') or 0  # a corpse under dropped arrows shows ')', so the '%' scan never dated it: stood on a fresh giant ant, ate 3 corpses in 8700 turns, fainted (T8693)
        return f'attacked {DIR_NAME[d]}'

    def act_go(self, target, steps=40, adjacent_ok=False, stop_new=True):
        """Walk toward target one step at a time; stop on new threats, damage or arrival."""
        taken = 0
        n_seen = len(self.hostile_glyphs())
        chs = {self.snap.at(*q).ch for q in self.hostile_glyphs()}
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
            if snap.me is None:  # @ not on screen (prayer, --More--): crashed flee_up mid-fight (T4041)
                return f'lost sight of yourself after {taken} steps'
            # monsters move, so compare counts rather than positions
            near = [q for q in self.hostile_glyphs() if cheb(q, snap.me) <= 7]  # by count alone, Izchak and a watchman leaving view hid a rope golem and a nymph arriving: walked into both, choked (T5445)
            if stop_new and near and (len(self.hostile_glyphs()) > n_seen or any(snap.at(*q).ch not in chs for q in near)):
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

    def act_descend(self, p, key='>', stop_new=True):
        r = self.act_go(p, stop_new=stop_new)
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
            real = self.level().__dict__.get('soko_boulders')
            if real is not None:  # keep the premapped set in step with pushes, so only mimics show up as unexplained '0's
                nb = (b[0] + DIRS[k][0], b[1] + DIRS[k][1])
                real.discard(b)
                real.update([nb] if self.snap.at(*nb) and self.snap.at(*nb).ch == '0' else [])
            if self.run.get('soko_plan', {}).get(m[0]):
                self.run['soko_plan'][m[0]].pop(0)
            return f"pushed the boulder {DIR_NAME[k]}" + (f": {news[:100]}" if news else '')
        if 'monster behind' in news or 'perhaps that' in news:
            self.act_keys('ms', '')  # let it move off: retrying in the same turn just tripped the stall guard
        key = (m[0], self.run['soko_step'].get(m[0], 0))
        fails = self.run.setdefault('soko_fails', {})
        fails[key] = fails.get(key, 0) + 1
        if 'in vain' in news or fails[key] >= 3:  # something unseen behind it: pushed 'in vain' 200+ turns (soko3-1 T3610); a repeated 'in vain' is deduped out of news, so count too: two stacked boulders, 'push failed' 30+ times (soko4 T7048)
            self.run.setdefault('soko_stuck', {})[key] = -99
        return 'push failed' + (f": {news[:120]}" if news else '')

    def act_soko_break(self, m, b, behind, k, letter):
        r = self.act_go(behind)
        if self.snap.me != behind:
            return 'sokoban: ' + r
        r = self.act_dig(letter, k)
        if self.snap.at(*b).ch == '0':
            return 'tried to break the boulder: ' + r
        self.run['soko_broke'][m[0]] = self.snap.status.get('turn') or 0
        self.run['soko_replans'][m[0]] = 0
        (self.level().__dict__.get('soko_boulders') or set()).discard(b)
        self.run['soko_stuck'][(m[0], self.run['soko_step'].get(m[0], 0))] = -99  # replan from the new layout
        return 'broke the boulder (Luck -1)'

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
        t0, hp0 = self.snap.status.get('turn'), self.snap.status.get('hp', 0)
        self.t.send('E')
        burn = None
        if 'write with' in self.t.lines()[0]:  # engrave.c: burned (fire/lightning) or dug Elbereth has no typos and never smudges when you're hit; only attacking from it erases it
            burn = next((it for it in self.inventory if re.search(r'\bwand of (fire|digging)\b', it['text']) and not re.search(r':0\)', it['text'])), None)
            self.t.send(burn['letter'] if burn else '-')
        for _ in range(6):
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
        if burn and 'too worn out to engrave' in ' '.join(self.run['recent'][-3:]):  # engrave.c zapwand: 0 charges; read as 'interrupted', 18 tries beside a nymph, then zapped down at 14 HP for nothing, dead to a giant ant (T3916)
            self.run.setdefault('empty_wands', set()).add(burn['text'])
            self.read_inventory()
            return 'the wand is empty: nothing written'
        if not self.elbereth_ok():
            if re.search(r"can't reach the (floor|ground)", ' '.join(self.run['recent'][-3:])):  # grabbed by a rope golem or in a pit: logged as 'garbled' 3 times at 5 HP, dead (T3597)
                self.run['no_engrave'] = self.snap.status.get('turn') or 0
                return 'could not engrave: cannot reach the floor'
            if 'written' not in self.last_read and self.snap.status.get('turn') == t0:  # no time passed: this form can't engrave (a wererat Jev), not an attack; blaming the rothe blocked Elbereth once back in dwarf form, 30 -> 0 (T7388)
                self.run['no_engrave'] = self.snap.status.get('turn') or 0  # in a spiked pit 'You can't reach the floor': offered and refused 3 times a turn while golems choked Jev (T5699)
                return 'could not engrave in this form'
            if 'written' not in self.last_read:  # 5.0 engraving is an occupation: a fast attacker interrupts it before any letter lands
                self.run['e_blockers'] = self.run.get('adj_names', ())  # a newt's hit blocked Elbereth against the rothe that came next: 19 -> 5, dead praying (T2568)
                self.run['engrave_interrupted'] = self.snap.status.get('turn') or 0
                return 'nothing got written: the attack interrupted the engraving'
            # mhitu.c never wipes engravings: a garble is the 1/25-per-letter typo, so one retry is a fresh ~72% (blocked at once, melee-only vs a plains centaur, dead T3823)
            if self.snap.status.get('hp', 0) < hp0 and any(h['choice'] == 'elbereth' and 'garbled' in h['outcome'] for h in self.history[-3:]):  # hit mid-engraving: 5 'garbled' retries beside a gnome king, 19 -> 10, dead (T4230)
                self.run['e_blockers'] = self.run.get('adj_names', ())
                self.run['engrave_interrupted'] = self.snap.status.get('turn') or 0
            return 'engraving came out garbled; not protected'  # engrave.c: each dust letter has a 1/25 typo, so a retry is a fresh ~72% shot; blocking retries after 2 garbles had 3 wolves bite 29 -> 0 (T2624)
        return 'engraved Elbereth'

    def act_engrave_id(self, it):
        self.run['etested'].add(it['text'])
        self.t.send('E')
        if 'write with' not in self.t.lines()[0]:
            self.t.send('\x1b')
            return 'could not engrave here'
        self.t.send(it['letter'])
        for _ in range(8):
            top = self.t.lines()[0]
            if 'add to the current engraving' in top or 'Call ' in top:
                self.t.send('n' if 'add to' in top else '\x1b')
            elif 'For what do you wish' in top:
                self.t.send('blessed +2 gray dragon scale mail\r')
            elif 'What do you want to' in top:
                self.t.send('x\r')
                break
            elif '--More--' in '\n'.join(self.t.lines()):
                self.add_msg(messages_from('\n'.join(self.t.lines())))
                self.t.send('\r')
            else:
                break
        self.observe()
        self.read_inventory()
        return 'engrave-tested: ' + ' '.join(self.run['recent'][-2:])[-120:]

    def flee_up(self, act):
        self.run['fled_up'] = self.snap.status.get('turn') or 0
        return act()

    def act_wait_elbereth(self):
        if not self.elbereth_ok():
            return 'Elbereth is gone'
        hp = self.snap.status.get('hp', 0)
        self.act_keys('ms', '')
        if self.snap.status.get('hp', 0) < hp:
            # monmove.c: a scared monster with no square to flee to panic-attacks anyway; one small hit in a crowd leaves the rest held off.
            # Treating it as failure dropped Elbereth for melee in a 12-monster swarm: 41 -> 0 in 8 turns (T1499)
            if hp - self.snap.status.get('hp', 0) < 0.1 * self.snap.status.get('hpmax', 1) and self.elbereth_ok():
                return 'a cornered monster panic-attacked; Elbereth is intact and still holds the rest off'
            self.run['elbereth'].discard((self.snap.status.get('dlvl'), self.snap.me))
            self.run['e_blockers'] = self.run.get('adj_names', ())  # a newt's hit blocked Elbereth against the rothe that came next: 19 -> 5, dead praying (T2568)
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
        with open(os.path.join(self.home, 'prayer.json'), 'w') as f:
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
            self.t.send('n' if any(n in top for n in self.never_eat()) else 'y')
        self.observe()
        self.read_inventory()
        if any("don't have anything to eat" in m['text'] or 'cannot eat' in m['text'] for m in self.messages[nmsg:]):
            self.run.setdefault('inedible', set()).add(text)
            return f'could not eat {text}'
        return 'ate'

    def act_eat_corpse(self):
        if not self.engraved_here() and self.snap.status.get('hunger') != 'Fainting':
            self.act_elbereth()  # eat.c: 1 in 7 corpses is rotten, up to 10 turns out cold; a fresh rothe's packmate killed an unconscious Djev from 46/46 (T3021)
        self.t.send('e')
        turn = self.snap.status.get('turn') or 0
        fresh = {k for t0, k in self.run.get('kills', []) if turn - t0 <= 30}
        for _ in range(8):  # eat.c asks per floor corpse: an old newt sat above a fresh quasit, 'y' to the first prompt, tainted, dead (T10532)
            top = self.t.lines()[0]
            m = re.search(r'There (?:is|are) (?:an? |\d+ )?(.+?) corpses? here; eat', top)
            if not m:
                self.t.send('\x1b')
                break
            if any(m[1] == k or m[1].endswith(' ' + k) for k in fresh | {'lichen', 'lizard'}) and not any(n in top for n in self.never_eat()):
                self.t.send('y')
                if self.snap.me:  # a fresh lizard sat on an old hill orc, ate both, food poisoning (T2656)
                    self.level().corpses[self.snap.me] = -10**6
                break
            self.t.send('n')
        self.observe()
        key = (self.snap.status.get('dlvl'), self.snap.me)
        self.run['here'][key] = self.look_here()
        return 'ate corpse'

    def blindfold(self):
        return None if 'Blind' in str(self.snap.status.get('conditions')) else \
            next((i for i in self.inventory if re.search(r'\b(blindfold|towel)\b', i['text']) and not re.search(r'\bcursed', i['text'])), None)

    def act_kill_blocker(self, pos):
        self.avoid.discard(pos)
        r = self.act_go(pos, adjacent_ok=True)
        me = self.snap.me
        if not me or cheb(me, pos) != 1:
            return 'going to the blocker: ' + r
        d = DIR_OF[(pos[0] - me[0], pos[1] - me[1])]
        g = self.snap.at(*pos)
        ch = g.ch
        # floating eye: its passive gaze only freezes a hero who can see it (uhitm.c passive AD_PLYS !canseemon); wiki: blindfold up, then melee.
        # Meleed one sighted with a blindfold in the pack: frozen while Hungry, starved (T5165)
        fold = self.blindfold() if ch == 'e' and g.fg == 'blue' else None
        if fold:
            self.act_keys('P' + fold['letter'], '')
            exp = self.snap.status.get('exp')
            for i in range(12):
                if self.snap.status.get('exp') != exp or self.snap.status.get('hp', 0) < 0.5 * self.snap.status.get('hpmax', 1):
                    break
                self.act_fight(d)
            self.t.send('R')
            if 'What do you want to remove' in self.t.lines()[0]:
                self.t.send(fold['letter'])
            self.settle()
            self.observe()
            self.read_inventory()
            return 'blindfolded, killed the floating eye' if self.snap.status.get('exp') != exp else f'blindfolded, fought the floating eye {i + 1} times'
        for i in range(10):
            g = self.snap.at(*pos)
            if not g or g.ch != ch or self.snap.status.get('hp', 0) < 0.5 * self.snap.status.get('hpmax', 1):
                break
            self.act_fight(d)
        return 'killed the blocker' if (g := self.snap.at(*pos)) is None or g.ch != ch else f'fought the blocker {i + 1} times; it still stands'

    def ray_room(self, a, v):
        """Squares a ray travels from a toward v before a wall: zap.c buzz() range is rn1(7,7) (7..13) and bounces: a wall under 7 away can send it back through us."""
        sx, sy = (v[0] > 0) - (v[0] < 0), (v[1] > 0) - (v[1] < 0)
        for k in range(1, 14):
            g = self.snap.at(a[0] + sx * k, a[1] + sy * k)
            if g is None or g.ch in '|- ' or g.ch == '#' and g.fg not in ('green', 'cyan'):
                return k
        return 14

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
        self.run['fired_turn'] = self.snap.status.get('turn') or 0
        self.t.send(key)
        if re.search(r'throw|zap', self.t.lines()[0].lower()):
            self.t.send(letter)
        if 'direction' in self.t.lines()[0].lower():
            self.t.send(d)
        elif 'wish' in self.t.lines()[0].lower():  # an unknown wand zapped at a red mold was wishing: the Escape here threw the wish away (T2871)
            return self.wish()
        else:
            self.t.send('\x1b')
        self.observe()
        self.read_inventory()
        return f"{'zapped' if key == 'z' else 'threw'} item {letter} {DIR_NAME[d]}"

    def wish(self):
        n = self.run.get('wishes', 0)
        self.run['wishes'] = n + 1
        self.t.send(WISHES[min(n, len(WISHES) - 1)] + '\r')
        self.observe()
        self.read_inventory()
        return 'wished for ' + WISHES[min(n, len(WISHES) - 1)] + ': ' + (self.run['recent'][-1] if self.run['recent'] else '')

    def act_zap(self, l, d, t):
        self.run['zaps'][t] = self.run['zaps'].get(t, 0) + 1
        out = self.act_throw(l, d, 'z')
        if any('vanishes!' in m for m in self.run['recent'][-3:]):  # unknown oak wand was make invisible: zapped 3x at a rope golem that then choked Jev unseen (T5475)
            self.run.setdefault('bad_wands', []).append(t[0])
        return out

    def act_wish(self, letter):
        self.t.send('z' + letter)
        if '--More--' in ''.join(self.t.lines()[:3]):
            self.t.send('\r')
        if 'wish' in self.t.lines()[0].lower():
            return self.wish()
        self.t.send('\x1b')
        self.observe()
        self.read_inventory()
        if not any('Unfortunately' in m for m in self.run['recent'][-2:]):  # zap.c: bad luck burns a charge, "Unfortunately, nothing happens."; plain "Nothing happens." is no charges
            self.run['wand_empty'] = True
        return 'the wand did nothing: ' + (self.run['recent'][-1] if self.run['recent'] else '')

    def act_shop_go(self, q):
        """Step toward a shop item, searching once whenever untested items are adjacent: dosearch0 -> mfind0 always unmasks an adjacent mimic (detect.c)."""
        me, tested = self.snap.me, self.level().__dict__.setdefault('mimic_tested', set())
        adj = {(me[0] + dx, me[1] + dy) for dx, dy in DIRS.values()}
        if any(p not in tested and self.snap.at(*p) and self.snap.at(*p).ch in ')[%?/=!("*' for p in adj):
            tested |= adj
            return self.act_keys('s', 'searched for shop mimics')
        return self.act_go(q, steps=1)

    def act_goto_corpse(self, p):
        r = self.act_go(p)
        if self.snap.me != p:
            return 'going to the corpse: ' + r
        if not any('corpse' in i and not any(n in i for n in self.never_eat()) for i in self.here_items()):
            self.level().corpses.pop(p, None)  # a bat corpse was re-offered 3 times
            food = next((i for i in self.here_items() if FOOD.search(i) and not re.search(r'corpse|egg|glob|for sale', i)), None)
            if food:  # the '%' was a slime mold, tripe or fortune cookie: walked off from them 6 times while starving
                return self.act_pickup(food)
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

    def act_loot(self):
        """user: unlock with a key/lock pick; else pry with a spare dagger (never force with the main weapon: a blunt one bashes and breaks potions); else kick."""
        key = (self.snap.status.get('dlvl'), self.snap.me)
        self.run.setdefault('looted', {})[key] = self.run['looted'].get(key, 0) + 1
        seen = []

        def box(keys):
            self.t.send(keys)
            for _ in range(12):
                lines = self.t.lines()
                kind, text = top_prompt(lines)
                seen.append(lines[0].strip())
                if kind == 'menu':
                    self.t.send('o' if 'Do what with' in text else 'aA\r' if 'what type' in text else '.\r' if 'Take out what' in text else '\x1b')
                elif kind == 'more':
                    self.t.send('\r')
                elif kind in ('yn', 'ask'):
                    self.t.send('y' if re.search(r'loot it\?|force its lock\?|unlock it\?|Unlock it with', text) else '\x1b')
                else:
                    break
            return ' '.join(seen)

        if 'locked' not in box('#loot\r'):
            pass
        elif (tool := next((it for it in self.inventory if UNLOCKER.search(it['text'])), None)):
            if re.search(r'succeed in (unlocking|picking)', box('a' + tool['letter'])):
                box('#loot\r')
        elif (dagger := next((it for it in self.inventory if 'dagger' in it['text'] and re.search(r'\b(uncursed|blessed)\b', it['text']) and 'weapon in' not in it['text']), None)):
            main = next((it for it in self.inventory if 'weapon in' in it['text']), None)  # known-BUC dagger only: a cursed one welds to the hand
            box('w' + dagger['letter'])
            ok = re.search(r'succeed in forcing', box('#force\r'))
            if main:
                box('w' + main['letter'])
            if ok:
                box('#loot\r')
        else:  # dokick.c: a kicked box can burst open ('WHAMM!' when it holds); potions inside may break
            me = self.snap.me
            spot = next((q for d, (dx, dy) in DIRS.items() if not (dx and dy) and self.snap.walkable(*(q := (me[0] + dx, me[1] + dy))) and not self.snap.is_monster(*q) and self.snap.at(*q).ch in '.#'), None)
            if spot and self.act_go(spot, steps=1) and self.snap.me == spot:
                for _ in range(5):  # dokick.c: 'THUD!' = it stayed put and held; otherwise it opened or slid off (kicking the empty square strains a muscle)
                    n = len(seen)
                    box('\x04' + DIR_OF[(me[0] - spot[0], me[1] - spot[1])])
                    if 'break open' in ' '.join(seen[n:]) or 'THUD' not in ' '.join(seen[n:]):
                        break
                self.act_go(me, steps=1)
                if self.snap.me == me:
                    box('#loot\r')
        self.observe()
        self.read_inventory()
        self.run['here'][key] = self.look_here()
        return ' '.join(' '.join(seen).split())[-150:] or 'looted'

    def act_altar(self, q):
        r = self.act_go(q)
        if self.snap.me != q:
            return 'heading for the altar: ' + r
        key = (self.snap.status.get('dlvl'), q)
        self.run['here'][key] = self.look_here()
        return f"the altar is {self.run.setdefault('altars', {}).setdefault(key, 'unknown')}"  # blind or garbled: don't revisit forever

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
        if re.search(r'Wield .* instead\?', self.t.lines()[0]):  # wield.c ready_weapon on the quivered dagger; 'q' left a disarmed Jev bare-handed, killed by a lynx (T4777)
            self.t.send('y')
        self.observe()
        self.read_inventory()
        if any('weapon in' in it['text'] for it in self.inventory):
            return 'wielded it'
        self.run.setdefault('unwieldable', set()).add(next((it['text'] for it in self.inventory if it['letter'] == letter), ''))
        return 'could not wield it'

    def act_dig(self, letter, d='>'):
        weapon = next((it['letter'] for it in self.inventory if 'weapon in' in it['text'] and it['letter'] != letter), None)
        dl = self.snap.status.get('dlvl')
        self.t.send('a' + letter)
        for _ in range(4):
            top = self.t.lines()[0]
            if 'direction' in top:
                self.t.send(d, timeout=10)
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
        return f'dug through to Dlvl {new}' if new != dl else 'dug' if d != '>' else 'dug but did not fall through (interrupted?)'

    def act_kick_door(self, spot, door):
        r = self.act_go(spot)
        if self.snap.me != spot:
            return 'going to the locked door: ' + r
        d = DIR_OF[(door[0] - spot[0], door[1] - spot[1])]
        if door in self.level().locked and not self.level().town and any(re.search(r'\b(key|lock pick|credit card)\b', it['text']) for it in self.inventory):
            self.act_go(door, steps=1)  # autounlock: 'Unlock it with your key?' -> y (answer_yn)
            if any('succeed in unlocking' in m['text'] for m in self.messages[-8:]):
                self.level().locked.discard(door)
        if door not in self.level().locked:
            self.level().blocked.discard(door)
            self.level().dead.discard(door)
            r = self.act_go(door, steps=1)
            if self.snap.at(*door).ch != '+':
                return 'opened the door'
            if door not in self.level().locked:
                return 'door did not open: ' + r
            return 'the door is locked'  # decide again: a locked door can be a closed shop (T245)
        sale = [p for (dl, p), v in self.run.get('here', {}).items() if dl == self.snap.status.get('dlvl') and any('for sale' in i for i in v)]
        # dokick.c: only a shop's own door (shop cost) or a door in Minetown (the watch) is punished. Any shop on the level vetoed every door:
        # 4400 turns on Dlvl 2 beside an unkicked locked door 15 squares from the shop, starved (T6390)
        # a chime outside the Mines (no watch, a fountain means nothing): 20 vetoes of the one locked door on Dlvl 2 in 9000 turns, starved (T9979); after 5, kick
        lv = self.level()
        if lv.town and (any(cheb(p, door) <= 3 for p in sale) or (not sale or self.snap.find('{')) and (self.in_mines() or lv.__dict__.get('vetoes', 0) < 5)):
            lv.vetoes = lv.__dict__.get('vetoes', 0) + 1
            lv.dead.add(door)
            return 'did not kick: shopkeepers and the watch punish broken doors'
        for i in range(6):
            if self.act_kick(d).startswith('did not'):
                return 'did not kick: something is written outside this door (shop sign?)'
            if door not in self.level().locked or self.hostile_glyphs():
                break
        return 'kicked the door open' if door not in self.level().locked else 'kicked the door; still shut'

    def act_kick(self, d, force=False):
        # a locked shop has "Closed for inventory" in the dust outside; kicking it in got Jev zapped by the shopkeeper
        nmsg = len(self.messages)
        self.t.send(':')
        raw = ' '.join(l.rstrip() for l in self.t.lines()[:3])
        self.observe()
        # the sign is dust and gets scuffed, so any writing outside a locked door counts
        if not force and self.level().town and (self.in_mines() or self.level().__dict__.get('vetoes', 0) < 5) or not force and re.search(r'written here|for inv', raw + ' '.join(m['text'] for m in self.messages[nmsg:])):
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

    def never_eat(self):
        return tuple(n for n in NEVER_EAT if not (n in ('kobold', 'bat', 'dog', 'cat', 'kitten', 'acid blob') + POISONOUS and n not in BAD_EFFECT and self.run.get('desperate') or n == 'bat' and self.run.get('calm')))  # calm: 33 giant bats killed, none eaten, 5 hunger prayers, the 5th angered Tyr, fainted (T7450)  # bat only stuns, pets only aggravate (eat.c): Weak with no prayer, explored off a 50-turn giant bat corpse, fainted, dead (T1956)

    def unseen_attacker(self):
        if self.snap and (self.snap.status.get('turn') or 0) - self.run.get('msg_turn', 0) > 2:
            return False  # recent only changes on a new message: a stale 'The lizard bites!' kept find_unseen going 3600 turns at full HP, 20 hunger prayers, fainted (T20037)
        # wiki (Ghost): speed 3, a 1d1 touch, AC -5: not a threat, lure it off; treated as an unseen attacker it pinned Jev to find_unseen/Elbereth on its own bones level (T6700-7000)
        volley = any(re.search(r'\b(shoots|throws)\b', m) for m in self.run['recent'][-3:])  # mthrowu.c: a multishot volley's 2nd arrow prints 'It misses.': find_unseen 5 times while an Uruk-hai shot, 33 -> 0 (T4657)
        return any(re.search(r"\bIt (bites|touches|stings|butts|kicks)|feel an unseen monster|You hear a nearby zap|The bolt of \w+ hits you", m) or not volley and re.search(r"\bIt (hits|misses)", m) for m in self.run['recent'][-2:]) \
            or self.snap.me and not any(cheb(q, self.snap.me) <= 1 for q in self.hostile_glyphs()) and any(re.search(r"\bThe [\w -]+ (hits|bites|stings|butts|kicks|touches|misses)!", m) and 'ghost' not in m for m in self.run['recent'][-1:])  # a named fire ant bit from a square the map never showed: 'rest' was the only option, 33 -> 0 (T5586)

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
            me = self.snap.me  # mobbed at 23/62 (soldier ants, elf mummy, ogre adjacent) the filters left nothing: searched 10 turns, dead (T8764)
            adj = {DIR_OF[(m['pos'][0] - me[0], m['pos'][1] - me[1])]: m['name'] for m in mons if m['dist'] == 1 and not m['pet'] and not m['peaceful']}
            if adj:
                opts = {f'attack_{d}': (f"Attack {n} ({DIR_NAME[d]})", f"Melee the adjacent {n}.", lambda d=d: self.act_fight(d)) for d, n in adj.items()}
        state = self.state_text(mons)
        t1 = time.time()
        question = QUESTIONS['action']['instructions']
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
            qs = questions(criteria)
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
        h = dict(id=self.decision['id'], at=now(), turn=s.get('turn') or 0, dlvl=s.get('dlvl') or 0, hp=s.get('hp'), choice=key, label=label,
                 p=probs.get(key, 1.0), confidence=conf, n_options=len(opts), latency_ms=meta['latency_ms'], outcome=outcome,
                 ms=dict(build=round((t1 - t0) * 1000), act=round((time.time() - t2) * 1000)))
        with self.lock:
            self.history.append(h)
            del self.history[:-200]
        with open(os.path.join(self.run_dir, 'decisions.jsonl'), 'a') as f:
            f.write(json.dumps(dict(h, state=state, criteria=criteria, answers=answers, model=meta.get('model'), screen=self.snap.lines)) + '\n')
        if meta.get('model') and meta['model'] not in self.run['models']:  # the engine's own version string (jev-1.13.0); a game continued on another engine lists both
            self.run['models'].append(meta['model'])
            self.runs[-1]['models'] = self.run['models']
            self._save_runs()
        self.log(f"T{h['turn']} {key} p={h['p']:.2f} -> {outcome}")

    # ---------- lifecycle ----------
    def new_run(self):
        rid = datetime.now().strftime('%Y%m%d-%H%M%S')
        self.run_dir = os.path.join(self.home, rid)
        os.makedirs(self.run_dir, exist_ok=True)
        self.run = dict(id=rid, started=now(), ended=None, character='dwarven Valkyrie', turns=0, max_dlvl=1, death=None, score=None,
                        engine='jev' if not self.jev.local else os.environ.get('JEV_LABEL') or self.jev.model, models=[], decisions=0, levels={}, under={}, here={}, elbereth=set(), prayed_turn=None, recent=[], death_msgs=[])
        self.history.clear()
        self.runs.append({k: self.run[k] for k in ('id', 'started', 'ended', 'character', 'turns', 'max_dlvl', 'death', 'score', 'engine', 'models')})
        self._save_runs()
        self.log(f'new run {rid} ({self.mode})')

    def end_run(self):
        blob = ' '.join(self.run['death_msgs'])
        m = re.search(r'((?<!is )(?<!are )(?<!was )killed by (?:M[rs]s?\. )?[^.!\n]+?|died of [^.\n]+|[Pp]oisoned by [^.\n]+|[Tt]urned to slime[^.\n]*|starved to death|drowned [^.\n]+|choked [^.\n]+|quit|escaped)\s*(?:$|\s{2}|\n|\.)', blob)
        self.run['death'] = m[1].strip() if m else ('died' if 'You die' in blob else 'game ended')
        try:  # the screen scrape misreads tombstones and other games' high-score lines; the local xlogfile is exact
            x = dict(f.split('=', 1) for f in [l for l in open(os.path.join(ROOT, 'nethack', 'lib', 'xlogfile')).read().splitlines() if f'\tname={self.name}\t' in l][-1].split('\t') if '=' in f)
            if self.mode == 'local' and abs(int(x.get('turns', -1)) - (self.run.get('turns') or 0)) <= 200:  # the last screen we read can lag the death by ~50 turns
                self.run['death'] = x['death'] + (f", {x['while']}" if x.get('while') else '')
        except (OSError, IndexError, KeyError, ValueError):
            pass
        self.run['ended'] = now()
        self.runs[-1] = {k: self.run[k] for k in ('id', 'started', 'ended', 'character', 'turns', 'max_dlvl', 'death', 'score', 'engine', 'models')}
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
                    t = json.load(open(os.path.join(self.home, 'prayer.json')))['prayed_turn']
                    # messages outlive games, so an old 'welcome back' can match: a prayer from the future is another game's
                    self.run['prayed_turn'] = t if t is not None and t <= (self.snap.status.get('turn') or 0) else None
                except (OSError, ValueError, KeyError):
                    pass
                if len(self.runs) > 1 and not self.runs[-2]['ended']:  # same game, new server: one record, listing every engine that played it
                    prev = self.runs.pop(-2)
                    self.run.update(id=prev['id'], started=prev['started'], models=prev['models'] + [m for m in self.run['models'] if m not in prev['models']])
                    try:
                        os.rmdir(self.run_dir)  # nothing written there yet
                    except OSError:
                        pass
                    self.run_dir = os.path.join(self.home, prev['id'])
                    self.run['decisions'] = sum(1 for _ in open(os.path.join(self.run_dir, 'decisions.jsonl'))) if os.path.exists(os.path.join(self.run_dir, 'decisions.jsonl')) else 0
                    self.runs[-1] = {k: self.run[k] for k in ('id', 'started', 'ended', 'character', 'turns', 'max_dlvl', 'death', 'score', 'engine', 'models')}
                    self._save_runs()
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
                self.t.gap = self.delay_ms / 1000  # per action, not per decision; public servers add Term.floor on top (see REMOTE_GAP in hardfought.py)
                try:
                    self.decide()
                except RuntimeError as e:
                    self.log(str(e), 'error')
                    self.paused = True
                if self.run.pop('enhance', False):
                    self.enhance()
                if self.run['decisions'] % 25 == 0 or self.run.pop('inv_stale', False):
                    self.read_inventory()
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
                         max_dlvl=self.run['max_dlvl'], decisions=self.run['decisions'], engine=self.run['engine'], models=self.run['models']) if self.run else None,
                runs=list(self.runs), inventory=list(self.inventory),
                level=dict(dlvl=snap.status.get('dlvl', 0), explored=min(1.0, sum(1 for l in snap.lines[MAP_TOP:MAP_BOT + 1] for c in l if c != ' ') / 700),  # ponytail: ~700 drawn cells is a typical fully seen level
                           downstairs=bool(snap.find('>')), upstairs=bool(snap.find('<'))) if snap and self.run else None,
            )
