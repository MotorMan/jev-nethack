"""Objective commit, stall, cooldown and preemption in jev/plan.py, on a fake bot."""
from types import SimpleNamespace
from jev import plan

st = dict(hp=20, hpmax=20, dlvl=3, turn=100, hunger='Not Hungry', gold=0)
b = SimpleNamespace(run=dict(levels={}, here={}, max_dlvl=3), inventory=[], snap=SimpleNamespace(status=st, lines=[' ' * 80] * 24),
                    log=lambda *a: None, state_text=lambda m: '', jev=SimpleNamespace(ask=lambda s, q: ({'goal': {'choice': 'explore'}}, {})))
f = lambda: None
opts = {'attack_h': ('a', 'b', f), 'explore_1': ('e', 'x', f), 'descend': ('d', 'x', f)}
o = plan.step(b, opts, [], 100)
assert b.run['obj']['id'] == 'explore' and list(o)[0] == 'explore_1' and 'Serves the objective' in o['explore_1'][1]
o = plan.step(b, opts, [], 450)  # no map change in 350 turns: stall, but explore has no cooldown and stays in the menu
assert b.run['obj_log'][-1]['result'] == 'stalled' and 'explore' not in b.run['obj_cool'] and 'explore_1' in o, b.run
b.run['obj_cool']['shop'] = 650  # a cooled objective's options leave the menu
assert 'buy_a' not in plan.step(b, opts | {'buy_a': ('b', 'x', f)}, [], 451)
st['hp'] = 5
plan.step(b, opts | {'rest': ('r', 'x', f)}, [], 460)
assert b.run['obj']['id'] == 'heal' and b.run['obj_log'][-1]['result'] == 'preempted'
assert plan.view(b)['phases'][0]['status'] == 'done' and plan.view(b)['phases'][1]['status'] == 'current'
print('test_plan OK')
b.run['obj'] = None
st['hp'] = 20
plan.step(b, {'descend': ('d', 'x', f)}, [], 470)
for t in range(19):
    plan.step(b, {'attack_h': ('a', 'b', f)}, [], 471 + t)
assert b.run['obj']['id'] == 'descend'
plan.step(b, {'attack_h': ('a', 'b', f)}, [], 490)
assert b.run['obj'] is None
print('test_plan absent OK')
