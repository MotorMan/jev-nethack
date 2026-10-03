"""Objective commit, stall cooldown and preemption in jev/plan.py, on a fake bot."""
from types import SimpleNamespace
from jev import plan

st = dict(hp=20, hpmax=20, dlvl=3, turn=100, hunger='Not Hungry', gold=0)
b = SimpleNamespace(run=dict(levels={}, here={}, max_dlvl=3), inventory=[], snap=SimpleNamespace(status=st, lines=[' ' * 80] * 24),
                    log=lambda *a: None, state_text=lambda m: '', jev=SimpleNamespace(ask=lambda s, q: ({'goal': {'choice': 'explore'}}, {})))
f = lambda: None
opts = {'attack_h': ('a', 'b', f), 'explore_1': ('e', 'x', f), 'descend': ('d', 'x', f)}
o = plan.step(b, opts, [], 100)
assert b.run['obj']['id'] == 'explore' and list(o)[0] == 'explore_1' and 'Serves the objective' in o['explore_1'][1]
o = plan.step(b, opts, [], 450)  # no map change in 350 turns: stall, cooldown, explore leaves the menu
assert 'explore' in b.run['obj_cool'] and 'explore_1' not in o and b.run['obj']['id'] == 'descend', b.run
st['hp'] = 5
plan.step(b, opts | {'rest': ('r', 'x', f)}, [], 460)
assert b.run['obj']['id'] == 'heal' and b.run['obj_log'][-1]['result'] == 'preempted'
assert plan.view(b)['phases'][0]['status'] == 'done' and plan.view(b)['phases'][1]['status'] == 'current'
print('test_plan OK')
