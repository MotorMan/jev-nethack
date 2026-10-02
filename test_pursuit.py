# pursuit_cost: walking away from a faster monster costs HP, from a slower one nothing (T6730 panther)
from jev.bot import pursuit_cost, MONSTERS
panther = MONSTERS['panther']
c = pursuit_cost(27, [(panther[1], 2, panther[4])])
assert c >= 0.5 * 21, c  # 27 steps for '<' at 21/73 with a panther 2 steps off: the walk must be dropped
assert pursuit_cost(27, [(MONSTERS['dwarf'][1], 1, MONSTERS['dwarf'][4])]) == 0  # speed 6: we outrun it
assert pursuit_cost(1, [(panther[1], 3, panther[4])]) == 0  # one step: no time to catch up
print('pursuit ok', round(c))
