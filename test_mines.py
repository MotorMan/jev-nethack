# ^O overview parsing: the heading above '<- You are here' marks a Gnomish Mines level
from types import SimpleNamespace as NS
from jev.bot import Bot
def run(lines, dl, prev):
    b = object.__new__(Bot)
    b.settle = lambda: None; b.log = lambda *a: None; b.observe = lambda: None
    b.run = {'prev': prev}
    b.snap = NS(status={'dlvl': dl})
    b.t = NS(send=lambda k: None, pump=lambda s: None, lines=lambda: lines)
    b.overview()
    return b.run
ov = ['  The Dungeons of Doom: levels 1 to 3', '     Level 1:', '     Level 3:', '  The Gnomish Mines: level 4', '     Level 4: <- You are here.', '(end)']
r = run(ov, 4, (3, (40, 10)))
assert r['mines_dls'] == {4} and r['mines_stair'] == (3, (40, 10)), r
ov2 = ['  The Dungeons of Doom: levels 1 to 4', '     Level 4: <- You are here.', '  The Gnomish Mines: level 4', '     Level 4:']
assert 'mines_dls' not in run(ov2, 4, (3, (1, 1)))
print('ok')
