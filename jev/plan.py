"""Game plan and committed objectives, after jev-doom's goal phase.

The plan is a fixed list of phases. A phase is done when an observable test on bot.run is true;
the current phase is the first one that is not done. An objective is a short goal that Jev commits to.
It holds until it is done, until no option serves it, or until it makes no progress within its budget
(a stall). A stalled objective goes on a cooldown and its options leave the menu while other options remain.
"""
from .nh import MAP_TOP, MAP_BOT

HUNGRY = ('Hungry', 'Weak', 'Fainting')
mines = lambda b: b.run.get('mines_dls') or set()
md = lambda b: b.run.get('max_dlvl', 1)
hp = lambda b: (b.snap.status.get('hp') or 0) / max(1, b.snap.status.get('hpmax') or 1)

# (chapter, id, title, hint for Jev, done test)
PLAN = [
    ('early', 'start', 'Leave the first levels', 'Explore Dlvl 1-2, pick up armor and food, then go down.', lambda b: md(b) >= 3),
    ('early', 'mines', 'Find the Gnomish Mines', 'A second downstairs on Dlvl 2-4 leads into the Mines.', lambda b: bool(mines(b))),
    ('early', 'minetown', 'Reach Minetown', 'Minetown is 3-4 levels into the Mines: temple, altar, shops.',
     lambda b: any(isinstance(k, tuple) and k[0] == 'mines' and v.town for k, v in b.run['levels'].items())),
    ('early', 'protection', 'Buy protection', 'A temple priest sells 1 AC for 400 x XL gold.',
     lambda b: bool(b.run.get('protection')) or md(b) >= 10),
    ('early', 'sokoban', 'Solve Sokoban', 'Sokoban is up from the level below the Oracle. The prize is a bag of holding or an amulet of reflection.',
     lambda b: bool(b.run.get('soko_done'))),
    ('middle', 'oracle', 'Pass the Oracle', 'The Oracle is on Dlvl 5-9. Keep AC low before you go deeper.', lambda b: md(b) >= 10),
    ('middle', 'minesend', "Clear Mines' End", 'The bottom of the Mines often holds a luckstone.', lambda b: len(mines(b)) >= 8),
    ('middle', 'quest', 'Find the Quest portal', 'The portal is on Dlvl 11-16. Return at XL 14.', lambda b: md(b) >= 17),
    ('middle', 'medusa', 'Pass Medusa', 'Medusa needs reflection or a blindfold, and a way over water.', lambda b: md(b) >= 25),
    ('middle', 'castle', 'Take the Castle wand', 'The Castle holds a wand of wishing.', lambda b: md(b) >= 27 or b.run.get('wishes', 0) > 0),
    ('late', 'gehennom', 'Enter Gehennom', 'The trapdoors in the Castle lead to the Valley.', lambda b: md(b) >= 30),
    ('late', 'wizard', 'Get the Amulet', 'Kill the Wizard of Yendor, then dig to the vibrating square.', lambda b: False),
    ('late', 'ascend', 'Ascend', 'Carry the Amulet up through the Planes to the Astral altar.', lambda b: False),
]


def drawn(b):
    return sum(c != ' ' for l in b.snap.lines[MAP_TOP:MAP_BOT + 1] for c in l)


# id -> (title, option key prefixes, progress, budget in turns, available, done, suppressible)
OBJECTIVES = {
    'heal': ('Recover HP', ('rest', 'pray', 'quaff_', 'elbereth', 'retreat', 'flee_up', 'teleport'),
             lambda b: b.snap.status.get('hp'), 100, lambda b: hp(b) < 0.5, lambda b: hp(b) >= 0.8, False),
    'food': ('Eat', ('eat_', 'pickup_food', 'buy_ration', 'shop_food', 'pray', 'goto_corpse'),
             lambda b: b.snap.status.get('hunger'), 150, lambda b: b.snap.status.get('hunger') in HUNGRY,
             lambda b: b.snap.status.get('hunger') not in HUNGRY, False),
    'explore': ('Explore this level', ('explore', 'door_', 'search_hidden', 'dead_end', 'kick_', 'find_unseen'),
                lambda b: (b.snap.status.get('dlvl'), drawn(b)), 300, lambda b: True, lambda b: False, False),  # a cooldown on explore left only search: 18 stalls in 3 games, ~3600 turns
    'loot': ('Collect and use items', ('fetch', 'pickup_', 'loot', 'stash_fetch', 'recover_gear', 'wear_', 'buc', 'altar', 'carry', 'offer', 'holy_water'),
             lambda b: (len(b.run['here']), len(b.inventory)), 150, lambda b: True, lambda b: False, False),  # a cooldown on loot also hid food pickups
    'shop': ('Buy and sell', ('buy_', 'sell_', 'quote_', 'shop_look', 'donate'),
             lambda b: (b.snap.status.get('gold'), len(b.inventory)), 200, lambda b: True, lambda b: False, True),
    'sokoban': ('Solve Sokoban', ('soko_', 'enter_sokoban'),
                lambda b: (b.snap.status.get('dlvl'), sum((b.run.get('soko_step') or {}).values())), 300, lambda b: True,
                lambda b: bool(b.run.get('soko_done')), True),
    'descend': ('Go down', ('descend', 'downstairs', 'dig_down'),
                lambda b: b.snap.status.get('dlvl'), 200, lambda b: True, lambda b: False, False),
}


def phase(b):
    return next((p for p in PLAN if not p[4](b)), PLAN[-1])


def serves(oid, key):
    return key.startswith(OBJECTIVES[oid][1])


def step(b, opts, mons, turn):
    """Update the committed objective for this decision. Returns the options, the objective's own first."""
    r = b.run
    log, cool = r.setdefault('obj_log', []), r.setdefault('obj_cool', {})
    o = r.get('obj')

    def end(result):
        log.append(dict(id=o['id'], start=o['since'], end=turn, result=result))
        del log[:-30]
        b.log(f"T{turn} objective {o['id']} {result}")
        r['obj'] = None

    if o:
        title, _, prog, budget, _, done, supp = OBJECTIVES[o['id']]
        p = prog(b)
        if p != o['prog']:
            o.update(prog=p, moved=turn)
        if done(b) or (o['id'] == 'descend' and (b.snap.status.get('dlvl') or 0) > o['dlvl']):
            end('done')
        elif turn - o['moved'] > budget:
            if supp:
                cool[o['id']] = turn + 200
            end('stalled')
        elif any(serves(o['id'], k) for k in opts):
            o['absent'] = 0
        else:  # a monster in view hides explore options for a few turns: that is not the end of the objective
            o['absent'] = o.get('absent', 0) + 1
            if o['absent'] >= 20:
                end('no options')
    for k in [k for k, t in cool.items() if t <= turn]:
        del cool[k]
    # urgent objectives preempt the rest
    o = r.get('obj')
    urgent = [i for i in ('heal', 'food') if OBJECTIVES[i][4](b) and any(serves(i, k) for k in opts)]
    if urgent and (not o or o['id'] not in urgent):
        if o:
            end('preempted')
        commit(b, urgent[0], turn)
    if not r.get('obj'):
        cands = [i for i, v in OBJECTIVES.items() if i not in cool and v[4](b) and any(serves(i, k) for k in opts)]
        if len(cands) == 1:
            commit(b, cands[0], turn)
        elif cands:
            commit(b, choose(b, cands, mons), turn)
    # a stalled objective's options leave the menu while anything else remains
    drop = [k for k in opts if any(serves(i, k) for i in cool)]
    if drop and len(drop) < len(opts):
        opts = {k: v for k, v in opts.items() if k not in drop}
    o = r.get('obj')
    if not o:
        return opts
    mine = {k: (v[0], f"Serves the objective ({OBJECTIVES[o['id']][0]}). {v[1]}", v[2]) for k, v in opts.items() if serves(o['id'], k)}
    return {**mine, **{k: v for k, v in opts.items() if k not in mine}}


def commit(b, oid, turn):
    b.run['obj'] = dict(id=oid, since=turn, moved=turn, prog=OBJECTIVES[oid][2](b), dlvl=b.snap.status.get('dlvl') or 0)
    b.log(f"T{turn} objective -> {oid}")


def choose(b, cands, mons):
    ph = phase(b)
    criteria = {i: f"{OBJECTIVES[i][0]}." for i in cands}
    q = {'goal': dict(type='choice', criteria=criteria,
                      instructions=f"Choose the objective the Valkyrie commits to for the next few hundred turns. "
                                   f"The game plan is at the phase '{ph[2]}': {ph[3]}")}
    try:
        answers, _ = b.jev.ask(b.state_text(mons), q)
        return answers['goal']['choice']
    except Exception as e:  # a failed goal call must not stop play: take the first candidate
        b.log(f'goal choice failed: {e!r}', 'warn')
        return cands[0]


def text(b):
    ph, o = phase(b), b.run.get('obj')
    s = f"Game plan: phase '{ph[2]}' ({ph[3]})\n"
    if o:
        s += f"Committed objective: {OBJECTIVES[o['id']][0]} since turn {o['since']}, last progress turn {o['moved']} (budget {OBJECTIVES[o['id']][3]} turns).\n"
    return s


def view(b):
    cur, o, turn = phase(b), b.run.get('obj'), b.snap.status.get('turn') or 0
    return dict(
        phases=[dict(chapter=c, id=i, title=t, hint=h, status='done' if d(b) else 'current' if i == cur[1] else 'todo') for c, i, t, h, d in PLAN],
        objective=dict(id=o['id'], title=OBJECTIVES[o['id']][0], since=o['since'], idle=turn - o['moved'], budget=OBJECTIVES[o['id']][3]) if o else None,
        history=list(reversed(b.run.get('obj_log', [])))[:12],
        cooldown=[[k, t - turn] for k, t in b.run.get('obj_cool', {}).items()],
        titles={k: v[0] for k, v in OBJECTIVES.items()},
    )
