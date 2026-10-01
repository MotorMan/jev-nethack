# corpse freshness: a '%' that shows before 'You kill' is parsed must still count as fresh
from types import SimpleNamespace as NS
from jev.bot import Bot, Level
screens = []
def screen(rows, turn):
    lines = [' ' * 80] * 24
    lines[23] = f'Dlvl:1 $:0 HP:10(10) Pw:1(1) AC:6 Xp:1/0 T:{turn}'.ljust(80)
    for y, r in rows.items():
        lines[y] = r.ljust(80)
    return lines
b = object.__new__(Bot)
b.settle = lambda: None; b.touch = lambda: None; b.soko = lambda: False
b.run = {'levels': {}, 'recent': [], 'max_dlvl': 1, 'turns': 0}
b.snap = None
cur = {}
b.t = NS(lines=lambda: cur['l'], cursor=lambda: cur['c'], cell=lambda x, y: NS(data=cur['l'][y][x], fg='default', bold=False, reverse=False))
def step(rows, turn, msg=None):
    cur['l'], cur['c'] = screen(rows, turn), (10, 5)
    if msg: b.run['recent'].append(msg)
    b.observe()
step({5: ' ' * 10 + '@d'}, 100)                  # jackal east
step({5: ' ' * 10 + '@%'}, 101)                  # corpse drawn, message not parsed yet
step({5: ' ' * 10 + '@%'}, 101, 'You kill the jackal!')
assert b.level().corpses[(11, 5)] == 101, b.level().corpses
step({5: ' ' * 10 + '@%' + ' ' * 5 + '%'}, 110)  # an old '%' far off stays stale
assert b.level().corpses[(17, 5)] < 0
step({5: ' ' * 10 + '@%' + ' ' * 5 + 'h'}, 120)  # a hobbit crosses the old corpse
step({5: ' ' * 10 + '@%' + ' ' * 4 + 'h%'}, 121)
step({5: ' ' * 10 + '@%' + ' ' * 4 + '%%'}, 122, 'You kill the hobbit!')
assert b.level().corpses[(17, 5)] < 0, b.level().corpses  # still old (T2090)
print('ok')

# 5.0 corpse rules: poisonous only when desperate, bad-effect corpses never
from jev.bot import Bot
class _F: pass
for desperate, corpse, banned in [(False, 'giant beetle corpse', True), (True, 'giant beetle corpse', False), (True, 'giant mimic corpse', True),
                                  (True, 'acid blob corpse', False), (True, 'yellow mold corpse', True), (False, 'floating eye corpse', False)]:
    _f = _F(); _f.run = {'desperate': desperate}
    assert any(n in corpse for n in Bot.never_eat(_f)) == banned, (desperate, corpse)
