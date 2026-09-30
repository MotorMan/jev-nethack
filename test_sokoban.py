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
