# shop notes: type from the welcome, item count by flood fill from the door, items of interest (user: plan a return with gold)
from types import SimpleNamespace as NS
from jev.bot import Bot, Level
from jev.nh import Snapshot
rows = ['',
        '          ------',
        '          |?!?.|',
        '          |?..?|',
        '          |....|  ?',
        '          ---@--',
        '             #']
lines = [r.ljust(80) for r in rows] + [' ' * 80] * (24 - len(rows))
lines[23] = 'Dlvl:2 $:0 HP:10(10) Pw:1(1) AC:6 Xp:1/0 T:100'.ljust(80)
term = NS(lines=lambda: lines, cursor=lambda: (13, 5), cell=lambda x, y: NS(data=lines[y][x], fg='default', bold=False, reverse=False))
b = object.__new__(Bot)
b.snap = Snapshot(term)
lv = Level()
b.level = lambda: lv
b.run = {'shop_kind': 'rare books', 'prices': {('scroll', 'FOO'): {300}},
         'here': {(2, (11, 2)): ['a scroll of genocide (for sale, 400 zorkmids)'], (2, (12, 2)): ['a scroll labeled FOO (for sale, 400 zorkmids)'], (2, (13, 2)): ['a scroll of light (for sale, 66 zorkmids)']}}
b.note_shops()
assert lv.notes == {'rare books (5 items, scroll labeled FOO (300zm), scroll of genocide)'}, lv.notes
print('shops ok')
b.run['here'][(2, (19, 4))] = ['a tattered cape', 'a dagger']
b.note_shops()
assert lv.notes == {'rare books (5 items, scroll labeled FOO (300zm), scroll of genocide)', 'tattered cape'}, lv.notes
b.run['here'][(2, (19, 4))] = ['a dagger']  # picked up
b.note_shops()
assert lv.notes == {'rare books (5 items, scroll labeled FOO (300zm), scroll of genocide)'}, lv.notes
print('loose ok')
