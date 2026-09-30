"""Replay every stored Sokoban solution on the 5.0 level files: each push must be legal and all pits end up filled."""
import json
from jev.sokoban import DIRS, from_lua

for name, sol in json.load(open('jev/sokoban.json')).items():
    lv, me = from_lua(f'build/NetHack50/dat/{name}.lua')
    bs, ps = lv.boulders, lv.pits
    for x, y, k in sol['pushes']:
        b, (dx, dy) = (x, y), DIRS[k]
        assert b in bs and (x - dx, y - dy) in lv.reach(me, bs, ps), (name, b, k)
        land = lv._land(b, dx, dy, bs, ps)
        assert land is not False, (name, b, k)
        nb = bs - {b} | ({land} if land else set())
        ps = ps if land else ps - {lv._pit_hit(b, dx, dy, bs, ps)}
        bs, me = nb, b
    assert not ps, (name, len(ps))
    print(name, 'ok')

# screen matching: every level, every mirror, found and oriented right (pushes map onto boulders)
from jev.sokoban import solutions, match, step, flip
for name, sol in solutions().items():
    lv, _ = from_lua(f'build/NetHack50/dat/{name}.lua')
    for f in range(4):
        m = match({(x + 3, y + 2) for x, y in (flip(p, f, sol['w'], sol['h']) for p in sol['walls'])})
        assert m and m[:2] == (name, f), (name, f, m)
        b, k = step(m, 0)
        assert (b[0] - 3, b[1] - 2) == flip(tuple(sol['pushes'][0][:2]), f, sol['w'], sol['h']), (name, f)
print('match ok')

# replanning from a mid-solution screen state (a boulder rolled off-plan): the new plan must solve the level
import time
from jev.sokoban import replan
for name, sol in solutions().items():
    lv, me = from_lua(f'build/NetHack50/dat/{name}.lua')
    f, ox, oy = 3, 3, 2
    sc = lambda p: (lambda q: (q[0] + ox, q[1] + oy))(flip(p, f, sol['w'], sol['h']))
    bs, ps = lv.boulders, lv.pits
    for x, y, k in sol['pushes'][:len(sol['pushes']) * 9 // 10]:  # play 90% of the stored solution in level terms
        dx, dy = DIRS[k]
        land = lv._land((x, y), dx, dy, bs, ps)
        nb = bs - {(x, y)} | ({land} if land else set())
        ps = ps if land else ps - {lv._pit_hit((x, y), dx, dy, bs, ps)}
        bs, me = nb, (x, y)
    t0 = time.time()
    plan = replan((name, f, ox, oy), sc(me), {sc(b) for b in bs}, {sc(p) for p in ps} | {sc(p) for p in lv.rollers})
    assert plan, name
    inv = {sc(p): p for p in lv.floor}
    for b, k in plan:  # replay in level terms: mirror both axes flips h<->l and k<->j
        b, k = inv[b], {'h': 'l', 'l': 'h', 'k': 'j', 'j': 'k'}[k]
        dx, dy = DIRS[k]
        assert (b[0] - dx, b[1] - dy) in lv.reach(me, bs, ps), (name, b, k)
        land = lv._land(b, dx, dy, bs, ps)
        assert land is not False, (name, b, k)
        nb = bs - {b} | ({land} if land else set())
        ps = ps if land else ps - {lv._pit_hit(b, dx, dy, bs, ps)}
        bs, me = nb, b
    assert not ps, (name, len(ps))
    print(name, 'replan ok', len(plan), f'{time.time() - t0:.1f}s')
