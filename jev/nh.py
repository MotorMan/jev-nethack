"""Reading the NetHack tty screen: status, map glyphs, prompts, menus."""
import re

MAP_TOP, MAP_BOT = 1, 21          # map rows on an 80x24 tty
DIRS = {'h': (-1, 0), 'l': (1, 0), 'k': (0, -1), 'j': (0, 1), 'y': (-1, -1), 'u': (1, -1), 'b': (-1, 1), 'n': (1, 1)}
DIR_OF = {v: k for k, v in DIRS.items()}
DIR_NAME = {'h': 'west', 'l': 'east', 'k': 'north', 'j': 'south', 'y': 'north-west', 'u': 'north-east', 'b': 'south-west', 'n': 'south-east'}
OBJECT_CHARS = set(')[%?/=!("*$`')
MONSTER_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ@&;:\'~')
DOOR_COLORS = ('brown', 'yellow')

STATUS1 = re.compile(r'^\[?(?P<name>.+?) the (?P<title>.+?)\s*\]?\s+St:(?P<st>\S+) Dx:(?P<dx>\d+) Co:(?P<co>\d+) In:(?P<in>\d+) Wi:(?P<wi>\d+) Ch:(?P<ch>\d+)\s+(?P<align>\w+)')
STATUS2 = re.compile(r'Dlvl:(?P<dlvl>\d+).*?\$:(?P<gold>\d+)\s+HP:(?P<hp>-?\d+)\((?P<hpmax>\d+)\)\s+Pw:(?P<pw>\d+)\((?P<pwmax>\d+)\)\s+AC:(?P<ac>-?\d+)\s+(?:Xp|HD):(?P<xl>\d+)(?:/(?P<exp>\d+))?(?:\s+T:(?P<turn>\d+))?(?P<rest>.*)$')
HUNGER = ('Satiated', 'Hungry', 'Weak', 'Fainting', 'Fainted', 'Starved')
MENU_END = re.compile(r'\((end|\d+ of \d+)\)\s*$')
YN = re.compile(r'\[([ynaq#]+)\](?: \(([ynaq])\))?\s*$')


def parse_status(lines):
    s = {'conditions': []}
    m = STATUS1.match(lines[22].strip())
    if m:
        s.update(name=m['name'], title=m['title'], st=m['st'], align=m['align'],
                 **{k: int(m[k]) for k in ('dx', 'co', 'in', 'wi', 'ch')})
    m = STATUS2.search(lines[23])
    if m:
        s.update({k: int(m[k]) for k in ('dlvl', 'gold', 'hp', 'hpmax', 'pw', 'pwmax', 'ac', 'xl') if m[k] is not None})
        s['exp'] = int(m['exp']) if m['exp'] else None
        s['turn'] = int(m['turn']) if m['turn'] else None
        words = m['rest'].split()
        s['hunger'] = next((w for w in words if w in HUNGER), 'Not hungry')
        s['conditions'] = [w for w in words if w not in HUNGER and not w.startswith('S:')]
    return s


class Glyph:
    __slots__ = ('ch', 'fg', 'bold', 'reverse')

    def __init__(self, cell):
        self.ch, self.fg, self.bold, self.reverse = cell.data, cell.fg, cell.bold, cell.reverse

    def __repr__(self):
        return f'{self.ch}/{self.fg}{"/rev" if self.reverse else ""}'


class Snapshot:
    """One clean (no overlay) screen, with the map classified."""

    def __init__(self, term, hint=None):
        self.lines = list(term.lines())
        self.cursor = term.cursor()
        self.status = parse_status(self.lines)
        self.grid = [[Glyph(term.cell(x, y)) for x in range(80)] for y in range(24)]
        x, y = self.cursor
        on_map = MAP_TOP <= y <= MAP_BOT
        # invisible without see invisible: no @ is drawn, but the cursor still rests on the hero
        self.me = (x, y) if on_map and self.lines[y][x] == '@' else self.find_me(hint) or ((x, y) if on_map else None)

    def find_me(self, hint=None):
        # a human shopkeeper is a white @ too: with the cursor off the map, take the @ nearest where we just were
        mes = [(x, y) for y in range(MAP_TOP, MAP_BOT + 1) for x in range(80)
               if self.grid[y][x].ch == '@' and self.grid[y][x].fg in ('brightwhite', 'white', 'default') and not self.grid[y][x].reverse]
        return min(mes, key=lambda p: max(abs(p[0] - hint[0]), abs(p[1] - hint[1])) if hint else 0, default=None)

    def at(self, x, y):
        return self.grid[y][x] if 0 <= x < 80 and MAP_TOP <= y <= MAP_BOT else None

    def is_door(self, x, y):
        g = self.at(x, y)
        return g is not None and g.ch in '|-+' and g.fg in DOOR_COLORS

    def is_monster(self, x, y):
        g = self.at(x, y)
        return g is not None and (x, y) != self.me and g.ch in MONSTER_CHARS

    def walkable(self, x, y):
        """Can a path step onto this square? Closed doors count (autoopen), boulders do not."""
        g = self.at(x, y)
        if g is None:
            return False
        c = g.ch
        if c in '.<>_{' or c in OBJECT_CHARS or self.is_monster(x, y) or (x, y) == self.me:
            return True
        if c == '#':
            return g.fg not in ('green', 'cyan')  # trees, iron bars
        if c in '|-+':
            return self.is_door(x, y)
        if c in '^0"':  # '"' is a web (or an amulet): unwalkable, it sealed the only door to '>' on Dlvl 7 and Jev waited 2000 turns (T11000)
            return True  # traps and boulders (pushable): allowed but expensive (see cost())
        return False

    def cost(self, x, y):
        g = self.at(x, y)
        if g.ch in '^"':
            return 20
        if g.ch == '0':
            return 8
        if self.is_monster(x, y):
            return 5
        return 1

    def diag_ok(self, a, b):
        """No diagonal moves into or out of a doorway that has a door."""
        return not (self.is_door(*a) or self.is_door(*b))

    def find(self, ch):
        return [(x, y) for y in range(MAP_TOP, MAP_BOT + 1) for x in range(80) if self.grid[y][x].ch == ch and not self.is_monster(x, y)]

    def crop(self, r=7, ry=4):
        """ASCII map window around the hero, for Jev's state text."""
        if not self.me:
            return ''
        mx, my = self.me
        rows = []
        for y in range(max(MAP_TOP, my - ry), min(MAP_BOT, my + ry) + 1):
            rows.append(self.lines[y][max(0, mx - r):mx + r + 1].rstrip())
        return '\n'.join(rows)


def top_prompt(lines):
    """Return (kind, text) for whatever the game is waiting on, or (None, None) for a normal command prompt."""
    text = '\n'.join(lines)
    if '--More--' in text:
        return 'more', text
    for y, line in enumerate(lines):
        if MENU_END.search(line):
            return 'menu', text
    top = lines[0].rstrip()
    if YN.search(top):
        return 'yn', top
    # getlin prompts; the vault guard's reads '"Hello stranger, who are you?" - ' and may already hold typed junk
    if top.endswith('?') or re.search(r'\[[^\]]*\]\s*$', top) or top.endswith(':') or re.search(r'\?" -( |$)', top):
        return 'ask', top
    return None, None


def messages_from(text):
    """The text shown before a --More--: top message lines, or the overlay window it ends."""
    lines = text.split('\n')
    row = next(i for i, l in enumerate(lines) if '--More--' in l)
    col = 0 if row <= 2 else lines[row].index('--More--')
    out = [l[col:].replace('--More--', '').strip() for l in lines[:row + 1]]
    return ' '.join(x for x in out if x)
