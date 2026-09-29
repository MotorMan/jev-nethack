from types import SimpleNamespace as NS
from jev.bot import Bot
b = object.__new__(Bot)
b.frozen, b.frozen_turn, sent, logs = 0, None, [], []
b.snap = NS(status={'turn': 839})
b.t = NS(send=sent.append); b.settle = lambda: None; b.log = lambda *a: logs.append(a)
lv = NS(blocked={1}, dead={2}, near={3}); b.level = lambda: lv
b.follow_guard = lambda: True  # stand-in for the normal decision
for i in range(50):
    b.decide()
assert sum('3s' in s for s in sent) == 3 and not lv.blocked, (sent, lv)
try:
    b.decide(); assert False
except RuntimeError as e:
    assert 'paused' in str(e)
b.snap.status['turn'] = 840; b.decide(); assert b.frozen == 0
print('ok', sent)
