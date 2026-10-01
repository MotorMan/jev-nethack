# search_spot prefers walls facing the unmapped part of the level (T15494: 14000 turns searching the explored west half)
from types import SimpleNamespace as NS
from jev.bot import Bot
from jev.nh import Snapshot
rows = ['',
        '                                  #',
        '                           -------|-',
        '          #               #-.......|',
        '        --|--------     #*#|.......|',
        '        |..........#    #  |.......|',
        '        |.........|#    #  |.......|',
        '        -----.-----#   ##  |...<...|',
        '          ####     #       |.......|',
        '          #        #       --..-..--']
lines = [r.ljust(80) for r in rows] + [' ' * 80] * (24 - len(rows))
lines[5] = lines[5][:30] + '@' + lines[5][31:]
lines[23] = 'Dlvl:3 $:0 HP:10(10) Pw:1(1) AC:6 Xp:1/0 T:100'.ljust(80)
term = NS(lines=lambda: lines, cursor=lambda: (30, 5), cell=lambda x, y: NS(data=lines[y][x], fg='default', bold=False, reverse=False))
b = object.__new__(Bot)
b.snap = Snapshot(term)
lv = NS(searched={})
b.level = lambda: lv
dist = {(x, y): abs(x - 30) + abs(y - 5) for y in range(3, 9) for x in range(28, 35)} | {(9 + x, 5): 21 - x for x in range(9)}
p = b.search_spot(dist)
assert p[0] >= 33, p  # east wall of the right room, not the explored west room
print('search_spot ok', p)
