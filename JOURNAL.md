# Journal

Timestamped log of findings, decisions and progress. Newest entries at the bottom.

## 2026-09-29 10:32 PDT — Kickoff
- Goal: reproduce kenforthewin's LLM NetHack ascension (Codex on Hardfought, 3.6.7, SSH+tmux,
  screen-text observations, self-written helpers) but with **Jev** making the decisions, like
  olivier-motium/jev-doom. UI in SMUI (shadcn terminal theme). Local NetHack 5.0.0 first.
- Jev API (TypeSafe direct): `POST https://api.typesafe.ai/v1/systemone`, body
  `{state, model:"jev-latest", questions:{key:{type:"choice"|"score"|"noul", instructions, criteria}}}`.
  Returns per-question `choice` + `probabilities` + `confidence`. jev-doom caps at 12 questions and 48KB.
- Probe call: 180 ms round trip, 385 input tokens. At the published $0.042/M input tokens that is
  ~$0.00002/call, so one call per game decision is affordable (100k calls ≈ $2).
- Jev is a *chooser*, not a generator: it cannot type commands. So the design copies jev-doom:
  code enumerates legal, concrete options and executes the chosen one ("motors"); Jev picks.
  "Jev-only" here means every game decision with more than one sane option goes to Jev.
- Hardfought build lives at github.com/k21971/NetHack50 (hints file `sys/unix/hints/hardfought`,
  Linux). Built on macOS with macOS.500 hints + Hardfought's gameplay NHCFLAGS
  (DUMPLOG, DUMPHTML, DGAMELAUNCH, SCORE_ON_BOTL, EDIT_GETLIN, SELF_RECOVER, ...).
  Dropped TTY_TILES_ESCCODES: it needs tile.c, which the macOS hints do not link, and it is
  display-only. Hardfought's sysconf is copied verbatim apart from paths.
- Hardfought sysconf sets default OPTIONS incl. `number_pad:1`, `perm_invent`, `hitpointbar`,
  `boulder:0`. Our rc (jev/nethackrc) overrides the first three. Gotcha: rc files do not allow
  trailing `#` comments on OPTIONS lines.
- 5.0.0 asks "Do you want a tutorial?" at start → `OPTIONS=!tutorial`.

## 2026-09-29 11:01 PDT — First Jev-driven games
- Architecture (all stdlib Python + pyte): `jev/term.py` pty + pyte 80x24 emulator; `jev/nh.py` screen
  parsing (status lines, glyph classes, prompts/menus); `jev/bot.py` level memory, Dijkstra pathing,
  option building, motors, Jev calls; `jev/server.py` HTTP + SSE on :8770; `web/` Vite/React/shadcn
  dashboard with the SMUI theme (built by a subagent against a fixed JSON contract).
- Each decision = one Jev call with 2 questions: `action` (choice over the current legal options,
  e.g. attack_<dir>, approach, wait, retreat, elbereth, pray, eat_<letter>, pickup_<n>, wear_<letter>,
  kick_<dir>, explore_<k>, descend, rest, search_hidden) and `danger` (noul, for the UI).
  If only one option exists no call is made. Every call is logged to runs/<id>/decisions.jsonl.
- Farlook (`;`) identifies up to 6 nearby monsters every decision (free action). Pets are
  reverse video on this tty; doors are brown; Hardfought's `boulder:0` makes boulders `0`.
- **Network gotcha**: uv's standalone CPython loses outbound TCP ~10 s after process start in this
  sandbox, while curl/Homebrew Python/Apple Python keep working. Moved the venv to Homebrew
  Python 3.14. Also added a connection class that tries each resolved IP with a 2 s connect timeout
  and a bounded DNS lookup (one Cloudflare IP was intermittently unreachable).
- Headless Chrome/Firefox cannot start inside the sandbox (mach bootstrap denied), so the
  dashboard is verified through the SSE stream and code review, not screenshots.
- Results: first run reached Dlvl 2 by T158 (killed newts/rats, picked up a pick-axe).
  Second run spent ~2500 turns on Dlvl 1: the only exits were a locked door ("The door resists!")
  and a boulder-blocked corridor, and neither was offered as an option. Fixed: failed steps into
  `+` doors mark them kickable; boulders are walkable at high cost (pushing).
- Jev behaviour notes: sensible priorities (attacks adjacent weak monsters, engraves Elbereth
  when hurt, prayed at low HP at T1247, ate when Hungry). Probabilities are often split 0.4–0.6
  in fights. Latency ~150–250 ms per decision.

## 2026-09-29 11:12 PDT — Hardfought transport, stall fixes
- SSH to hardfought.org (and github.com:22) fails with "No route to host" from this network,
  even outside the sandbox. HTTPS works. Hardfought's browser terminal (hterm) is a plain
  websocket: `wss://www.hardfought.org/ws-hterm?c=80&l=24`, raw tty bytes in binary frames.
- New `jev/wsbridge.py` relays a pty to that websocket so the existing `Term` drives it
  unchanged. Gotcha: TLS can buffer several frames, so select() misses them; drain with
  `sock.pending()`.
- New `jev/hardfought.py` logs in through dgamelaunch and picks the NetHack 5.0 entry.
  Verified up to the username prompt. **Blocked:** HARDFOUGHT_USERNAME/PASSWORD in `.env` are
  empty, so the logged-in menu is untested. I did not register an account on the user's behalf.
- Local run stalled at T621: "Retreat" picked a bear-trap square, the game asked "Really step
  into that bear trap?", we answered no, and Jev picked retreat again forever. Fixes: retreat
  skips traps/boulders and reports honestly when it didn't move; generic stall guard drops any
  option picked 3x in a row without the turn counter moving.

## 2026-09-29 11:18 PDT — Long local run: Dlvl 4, T5000+, XL5
- Current game (restored from save across restarts) reached Dlvl 4 at T2248, XL 5, still alive at T5000+.
- Stuck patterns found and fixed:
  - **Floating eye paralysis bait:** a floating eye 2 squares away counted as a threat, so
    "wait" won for 200+ turns, and pathing treated its square as walkable, which would have meant
    meleeing it. Passive monsters (floating eye, molds, shrieker) no longer gate the options, and
    their squares are never stepped into.
  - **Locked doors out of reach:** a locked door was only kickable when adjacent. The new
    "go kick open the locked door" option walks there and kicks up to 6 times.
  - **Invisible hero:** without see invisible, NetHack draws the floor instead of `@`, so the
    bot spun on "cannot find the hero". It now falls back to the cursor position, which tty
    leaves on the hero, and adds a ^R redraw to recover from emulator drift.
- Added dig-down (apply pick-axe/mattock, `>`, then re-wield the weapon) as a Jev option.

## 2026-09-29 11:30 PDT — First real death: angry god
- Run 20260929-112438 died on **T8110, Dlvl 5, XL 6**: "killed by a couatl of Tyr, while praying".
- Cause:
  - Jev cured "Weak" hunger with prayer 8 times instead of eating. The food regex missed
    wolfsbane and similar items, and nothing offered eating corpses.
  - "Pray" was offered whenever in trouble, with no prayer-timeout gate.
  - My dev restarts reset the remembered prayer turn.
  - Finally it prayed 6 times in 33 turns: "Thou durst call upon me? Then die, mortal!"
- Fixes:
  - Pray is only offered after T300 and at least 1000 turns after the last prayer.
  - The prayer turn persists in `runs/prayer.json` and is reloaded when the save is restored.
  - The food list is wider.
  - New "go eat the fresh corpse" option (corpses seen less than 30 turns ago).
- Also added: monster difficulty and speed labels, taken from `monsters.h`, in Jev's state. At XL6
  it had been retreating from newts.

## 2026-09-29 11:50 PDT — Stall hunting, round 3
- Run 20260929-113929 died on T5429, Dlvl 4: "killed by an iguana, while fainted from lack of food".
  Hunger is the main killer. Fresh corpses on the hero's square can now be eaten whenever the
  hero isn't Satiated, and the strategy text tells Jev that food is scarce.
- A **statue of a fox** was drawn as `d` and treated as a hostile, so Jev "waited" 736 times.
  Statues found by farlook are now dropped from the monster list and marked impassable.
- "You can't move diagonally out of an intact doorway": the `@` hides the doorway. Doorways under
  the hero are now remembered, and that message also teaches it.
- Kicking while sharing a square with a boulder ("not enough room to kick") made Jev alternate
  kick/retreat on a frozen clock. Stall guard v2: after 4+ decisions on one turn, every option
  tried during that streak is dropped.
- "New game" never started a fresh game: SIGHUP saves, and SELF_RECOVER restores. The bot
  now deletes the level/save files after closing when the operator asks for a new game. It also
  had a waitpid race between the HTTP thread and the bot thread.
- The resumed long game reached **Dlvl 8 by T11870** before I reset it.
- Jev spend so far: about 5.6k calls, $0.28.

## 2026-09-29 12:23 PDT — The spear was a pear
- Three straight deaths "while fainted from lack of food". I analyzed decisions.jsonl: when eating
  was offered, Jev chose it about 98% of the time (1190 times in one run). The motor, though, was
  eating item `a`, "+1 dwarvish s**pear**", because the food regex matched `pear` with no
  word boundary. It tried 1,039 times and got "You don't have anything to eat" each time.
  Jev was right and my option builder was wrong.
- Fixes: a word-bounded, plural-aware food regex with an assert test, plus a per-run inedible
  blacklist when the game refuses.
- Jev loved "Search here 15 turns" at full HP (537 of 650 choices in one game). Rest is now only
  offered below 70% HP.
- Unreachable monsters (behind walls) no longer count as nearby threats, so wait/retreat
  stop dominating.
- Pace gate: descending is not offered past Dlvl XL+2. An XL1 died on Dlvl 5.
- New "kill the mold blocking the way" option: a red mold was the only exit on a Mines level,
  and molds are otherwise never walked into.
- Jev spend so far: about 10k calls, $0.53.

## 2026-09-29 12:42 PDT — Monkey, ghost, bat
- Run 20260929-123909 died to a giant bat at T7270 on Dlvl 3. It had resumed on a bones level.
- A monkey stole the +3 small shield, so AC went from 6 to 10. The ghost ("Jev's ghost touches you") is drawn as blank, so it never showed up in the monster list.
- Jev kept meleeing bats while HP drained, and the 1000-turn prayer gate hid pray at 2 HP.
- Changes:
  - The prayer gate is now 600 turns for low HP and 900 for hunger.
  - Melee options now carry a "you are at X/Y HP" warning below 1/3 HP, and Elbereth is marked as the best move then.
  - Added a quaff-potion option at low HP.
  - "It hits" and "ghost touches" messages now flag an unseen attacker and offer Elbereth.

## 2026-09-29 13:21 PDT — Doors nobody opened
- Two runs starved on Dlvl 1: one reached T10981 praying off hunger every ~900 turns, the other died at T4048. Both spent thousands of turns on search_hidden while closed `+` doors sat in plain view.
- Now that decisions log the full screen, a simulation showed the doors were reachable. Remembered level state (dead/blocked targets, and only the first two entries of the locked set) had hidden them from the option list.
- Fix: each turn, scan the screen for closed doors that have blank (unexplored) space beside them, and offer "Go through the closed door". It opens the door and kicks only if it is locked.
- Also: adjacent unseen creatures (I) can now be fought (a blinded T124 death), and a first prayer for low HP is allowed from T150.

## 2026-09-29 13:47 PDT — Doors work; spores and trap doors
- The new closed-door option is in use: across several runs the log shows "opened the door" and "kicked the door open" 7 times.
- A gas spore killed next to a shopkeeper angered him, and he zapped a wand for the kill. Gas spores are now passive, like floating eyes (avoided, thrown at, never meleed), and the threat text warns about the explosion.
- A trap door dropped an XL1 hero to Dlvl 5. The pace gate still allowed "descend" when monsters were near, so it fled to Dlvl 6 and then 7 and died to a pony.
  - Being too deep now always blocks descending and digging down.
  - At 4 or more levels past XL, a "head back upstairs" option appears.

## 2026-09-29 14:19 PDT — Memory walls
- One run waited for 7800 turns. Moves blocked by a peaceful hobbit had been recorded as blocked *floor* squares, and those walled the hero into the corner of a room.
- Another run starved on Dlvl 1 by T11133 with an open doorway and unexplored corridor ends in view. They had been marked dead or "near" earlier.
- Fixes:
  - Only non-floor squares (doors, boulders) are ever recorded as blocked.
  - When no options remain, level memory is wiped.
  - After every 300 turns of fruitless hidden-passage searching, level memory is wiped and a "Re-explore this level" option is offered.
- Spend so far: about 16.5k Jev calls, about $0.87.

## 2026-09-29 15:02 PDT — The prayer clock leak (big one)
- A fresh game believed its last prayer was on T26302, the previous game's clock. Every Weak and Fainting turn failed the prayer gate, and it fainted to death at T1932.
- Cause: the resume check looked for "welcome back" in the last 5 messages, and message history survives across games. The old game's resume message matched, so the new game loaded the old game's prayer file.
- Fixes:
  - A prayer turn later than the current turn is discarded, both on load and at the gate.
  - The resume check itself is unchanged; the future-turn check is enough to catch this.
- This likely explains several earlier "fainted" deaths after a new game started.
- The floating-eye/gas-spore corridor run starved at about T26000. Before that, Jev killed 3 gas spores with the kill-blocker option. Engraving Elbereth could not move the eyes, which were jammed against each other.
- Nearby fresh corpses (under 10 steps, under 30 turns old) are now offered whenever Jev is not satiated, with the reason spelled out: Jev had been passing up corpses while "Not hungry".

## 2026-09-29 15:34 PDT — Bats, shops, pace
- 6 runs since the prayer fix: giant bat x3 (Dlvl 4-5, T1688-1945), a sewer rat at T833, a wand at T1982, and one unknown at T149.
- Wand: a dagger thrown at a gas spore in a shop set it off next to the shopkeeper, who then zapped Jev. Gas spores with a peaceful within 2 squares are now dropped from the target list altogether.
- Bat: at 8/35 HP with no prayer available, Jev chose "approach giant bat". Approach options are now hidden below 1/3 HP.
- Pace tightened to Dlvl <= XL+1. The "go back up" option now appears at XL+3.

## 2026-09-29 15:56 PDT — Trap door standoff (spotted by the operator)
- The operator noticed a Mines run stuck at T2242. The only path west crossed a known trap door. NetHack asked "Really step onto that trap door?", the bot answered Esc (no), and the stall guard then wiped level memory, so the same move repeated.
- Fixes:
  - The step-onto-trap prompt is now answered yes for ordinary traps and no for trap doors, holes, level teleporters, portals, and polymorph and fire traps.
  - Refused squares go into a new per-level trap set that pathing never uses and memory wipes never clear.
  - If nothing else is possible and at least one memory reset has already been tried, "Take the downstairs anyway" is offered even when too deep.
- Side bug: a wear option failed silently 3 times in a row. Armor that does not end up "being worn" is now remembered and not offered again.
- Added `python -m jev.watch`, a terminal viewer (the colored game screen, Jev's option probabilities, recent decisions, and deaths), at the operator's request.
- That run then died to a rothe on Dlvl 6 at XL3. The Mines are rough when a level-3 hero is forced down.

## 2026-09-29 16:14 — Vault guard and a loop guard
A closet vault's guard asked "Hello stranger, who are you?" and Jev's movement keys kept landing in the text prompt, burning a paid call each time. top_prompt now recognizes the `?" -` prompt, and the answer is backspaces plus "Jev". A general guard also runs now: 15 Jev calls in a row without the game turn moving trigger Esc plus a redraw. At 40 the bot pauses itself (shown as PAUSED in the UI and watcher) instead of spending more. A single-option decision never calls Jev.

## 2026-09-29 16:16 — The guard escort
With the name prompt answered, the next vault visit ended with "killed by a guard". Jev never dropped the gold and kept bumping into the guard until he turned hostile. Escorts now run as a scripted routine with no Jev calls: when a "follow me" message is less than 60 turns old and an @ stands within 8 squares, drop the gold (d$), wait whenever adjacent to the guard, and otherwise step toward him. Also learned: SIGHUP only saves the game, so a restart needs TERM plus a wait for the process to exit. My earlier "restart" had left the old code running.

## 2026-09-29 16:17 — Standing on Elbereth
The rothe deaths (twice) had the same shape. At about 10/48 HP Jev engraved Elbereth, then chose "retreat" and stepped off it, over and over, while the rothe followed. Once Elbereth is under Jev, retreat is no longer offered, and the wait option says outright that it heals safely there. Elsewhere, retreat now tells a hurt Jev that most monsters simply follow.

## 2026-09-29 16:37 — A free loop is still a loop
A pet dog parked outside a doorway on Dlvl 1. Jev's only option, explore, was "blocked after 1 steps" 2,929 times on T839. It cost nothing (single-option decisions skip Jev), which is exactly why the paid-call loop guard never noticed. The guard now counts every decision on a frozen turn. At 15, 30 and 45 it presses Esc, redraws, forgets remembered walls, takes one random step and searches 3 turns, which lets a pet or peaceful move off. At 50 the bot pauses. A stubbed check lives in test_loop_guard.py.

## 2026-09-29 16:43 — Food poisoning
"Died on T1317" with no cause turned out to be food poisoning. Jev ate a corpse it had never seen die: an unknown age defaulted to 0, which read as fresh. Unknown corpses now count as rotten. FoodPois, TermIll, Stone, Slime and Strangl now count as trouble for prayer, and prayer is offered whatever the prayer clock says, since the alternative is certain death. Elsewhere, the Elbereth change works: the current game (T3600) sat on its engraving and healed.

## 2026-09-29 16:47 — Zombie meat
Another food-poisoning death on T68: Jev killed a kobold zombie and went straight to eat it. Zombie and mummy corpses are created already old, so the fresh-kill rule misfires on them. Both are now on the never-eat list. Also new: Izchak killed one run on Dlvl 6 (a shop fight to look into), and gas spores keep exploding next to Jev.

## 2026-09-29 16:48 — Point-blank spores
The latest gas spore death: Jev, at 8/23 HP on Elbereth, threw a dagger at a spore standing right next to it, because the throw option called itself "safe". The blast covers every square next to the spore. Throw and zap options now need the spore at least 2 squares away, and its description says why.

## 2026-09-29 16:49 — Izchak's door
A Dlvl 6 run died to Izchak's wand of striking. The door-kicking routine, added to open unexplored rooms, had kicked in his locked shop door. A level where Jev has farlooked a peaceful @ (shopkeeper, watchman, priest) is now marked as town, and there locked doors are never offered or kicked.

## 2026-09-29 16:59 — Strategy review against the wiki dump and the 5.0 source
Two research passes: the NetHackWiki dump (YASD, standard strategy, Valkyrie, Elbereth, prayer, corpses) and the 5.0 source and changelogs in build/NetHack50. Several things the bot "knew" were 3.6 lore, and a few of my recent fixes were wrong.

What 5.0 actually does (source file:line in the audit):
- **Prayer.** The timeout starts at 300 and falls 1 per turn; major trouble is fixed at 200 or less. So the first emergency prayer is safe from about T100, not T150/T300. Low HP means HP ≤ 5, or HP × 5 (XL 1–5; 6 at XL 6–13, 7 at 14–21) ≤ min(maxHP, 15·XL). The old 1/7 rule prayed at 5/40 instead of 8/40. Weak hunger, food poisoning, illness, stoning, sliming, strangling and lycanthropy are all major trouble with the same clock.
- **Elbereth.** Dust garbles each letter 1 time in 25, so about 28% of engravings are misspelled and useless. Attacking from it (melee, throw or zap) erases it and costs up to −5 alignment ("You feel like a hypocrite"). A Valkyrie starts at alignment 0, and negative alignment makes prayer fail. It scares everything that sees it except @ humans and elves, minotaurs, shopkeepers, guards, priests and uniques.
- **Corpses.** Rot is age / (10 + rn2(20)), so tainting is possible from age 60. Zombie and mummy corpses are 101 turns old at birth and are named after the living monster ("gnome corpse"), so my never-eat entries for "zombie" and "mummy" never matched. Jev is a *dwarven* Valkyrie, so dwarf corpses are cannibalism (−2 to −5 Luck, which breaks prayer).
- **Prompts.** The trap prompt reads "Really step **into** that hole / level teleporter / magic portal?", and the old check only matched "onto". The strangulation status is "Strngl".
- **Shops and the watch.** A broken shop door costs 400zm ("Pay?"). The watch warns once ("stop damaging that door") and then turns hostile. "Closed for inventory" is written outside locked shops.

Changes made:
- LOW_HP now copies pray.c.
- One prayer clock for all major trouble: first prayer from T110, then 600 turns apart. 600 turns still carries about an 11% chance the god isn't ready yet; that is accepted.
- Lycanthropy is tracked from "You feel feverish" and cleared by "You feel purified".
- Engravings are read back with `:` (a free action): a garbled Elbereth is not trusted, and one that has worn off ends the wait-on-Elbereth loop.
- Throwing clears the Elbereth mark.
- No melee or throw options while on Elbereth, except against @ or a minotaur. Elbereth isn't offered when every nearby hostile is an @.
- A corpse counts as fresh only if it appears within 2 squares right after a "You kill" message ("You destroy" means undead). Anything else is of unknown age and never eaten.
- Never eat: dwarf, were*, kobold, bat, ghoul, vampire, chameleon, dog, cat, kitten, pony.
- Trap prompts match "onto" and "into". Condition names are matched at every width.
- Farlook suffixes like ", asleep" are stripped.
- Say yes to "Pay?". "Closed for inventory" and the watch's warning mark the level as town, so no more kicking.
- Rest to 85% HP; take stairs only at 80% HP or more.

From the wiki, not done yet, in priority order:
- Retreat only from monsters slower than speed 12. Rothes, dwarves, ghosts and gas spores can be outrun; giant bats, soldier ants, ravens and dingos cannot.
- "Go to the upstairs" when in danger and the stairs are within about 8 steps.
- Pull groups into a corridor or doorway.
- Gnomish Mines pacing: Dlvl ≤ XL there, and no Minetown or below until about XL 8.
- Drop weight when Burdened.
- Keep the ascend option away from the Sokoban branch.
- Excalibur is technically in reach (long sword, lawful, XL 5, a 1-in-30 dip), but the failure outcomes (water moccasins, nymphs, water demons) are costly this early. Skipped for now.

## 2026-09-29 17:01 — Blind on Elbereth
Retreat is now offered only when every nearby hostile is slower than Jev's speed of 12, and a new "Run for the upstairs" appears when hurt with '<' within 8 steps. Then a rothe pack killed a run that looked like a textbook Elbereth rest: the HP went 48, 44, 41, 37, 27, 23, 8, 0 across eight "Stay on Elbereth" turns. Jev was Blind. A blind hero can't read the engraving back (the dust message needs sight), so the check passed without seeing anything, and attacks were hidden. Changes:
- Blind means Elbereth isn't trusted.
- Taking damage while waiting on it drops the flag, which brings attacks back.
- A last-chance "Pray (gamble)" appears at critically low HP with a hostile adjacent, if at least 300 turns have passed since the last prayer. That run had prayed 521 turns earlier and so got no prayer option at all.

## 2026-09-29 17:14 — Waiting that never waited
A big one, found through a rothe death. 5.0's `safe_wait` option refuses a plain `s` whenever a hostile is next to you ("You already found a monster. Use 'm' prefix to force another search.", do.c cmd_safety_prevention), and no game time passes. So every "Hold position" and "Stay on Elbereth" decision with a monster adjacent did nothing, and so did the three waits at T2416. The waits now send `ms`. Counted searches like `15s` were never affected.
The same run died with 1 HP left and a safe prayer on the menu, because Jev picked Elbereth. When the hero is at critically low HP and a safe (non-gamble) prayer is offered, the menu is now narrowed to pray plus any potion.

## 2026-09-29 17:32 — Engravings that never happened
The last rothe death: after "Engrave Elbereth", reading the square said only "You see no objects here". Engraving is an occupation in 5.0, so the rothe's attack interrupted it before anything was written. My check only rejected a *wrong* text, not a missing one. It now requires the exact 'You read: "Elbereth"'.
Another shopkeeper wand death: on Dlvl 2 Jev kicked a locked shop door before ever seeing the shopkeeper. Every kick now reads the square first (a free action). "Closed for inventory" marks the level as town and leaves the door alone.

## 2026-09-29 18:17 — The read-back that ate itself
Right after the strict read-back went in, 386 of 405 engravings were "garbled", and Jev spent whole fights re-engraving. A raw-screen trace showed 'You read: "Elbereth".' sitting on the screen while the bot saw nothing. add_msg drops a message identical to the one before it, and every read-back after the first on the same square is identical. The check now looks at the raw screen as well as the message log. Since the fix, rejects are real garbles ("Elbere[h", "Elber.th") plus the odd interrupted engraving, and "waited on Elbereth" is the most common outcome again.

## 2026-09-29 18:22 — Hallucination and a scuffed shop sign
Two deaths at Dlvl 9. (1) A horse, while hallucinating. Jev tried Elbereth nine times and every copy came out garbled. engrave.c scrambles each letter you *write* with chance 1/2 while hallucinating, 1/4 stunned and 1/7 confused, so Elbereth is no longer offered in those states. (2) "Killed by a wand": Jev kicked open a closed shop again. The dust "Closed for inventory" outside a locked shop door gets scuffed by passing monsters, so the exact-text check missed it. Now any writing outside a locked door vetoes the kick, and the raw screen is read as well as the message log.

## 2026-09-29 18:23 — Stop hauling furniture
257 decisions were made Burdened. The inventory at those times held a chest (350 wt), a lance, a pole sickle, a large box and rocks, all picked up because "Pick up X" looked like free value. Heavy junk (containers, boulders, rocks, polearms, lances, two-handers, mattocks) is now never offered for pickup, and when Burdened/Stressed each heavy non-worn, non-wielded item gets a "Drop" option.

## 2026-09-29 18:35 — Mr. Kipawa's gold
Dlvl 5, "killed by Mr" (the death parser stopped at "Mr."). The chain of events:
- Jev walked into a general store and picked up 92 gold pieces off the shop floor. That gold belongs to the shopkeeper, so it went on Jev's bill.
- Kipawa stood in the doorway. Every explore step bumped him ("You have no gold or credit"), about 130 turns of it.
- Jev ate a rotten carrot and became confused. The next confused step into Kipawa counted as an attack, and his wand of striking did the rest.
Fixes:
- No pickups at all within 7 squares of anything seen "for sale".
- While confused or stunned with nothing hostile near, the only choices are waiting (or prayer/potions).
- The death parser now keeps "Mr./Ms." names.

## 2026-09-29 18:45 — New best: Gnomish Mines level 11
Two more runs:
- **Dlvl 11 (a new record depth), Mines' End.** Jev was poisoned by an orcish arrow: poison instadeath from Thosogzai's volley while standing on Elbereth, which does nothing against missiles. Without poison resistance this is a dice roll. The parser now records "poisoned by …" instead of "game ended".
- **Dlvl 5, frozen by a floating eye, then eaten by manes.** A walk to the stairs stepped into the eye after it drifted onto the path. A plain move into a monster is an attack. Walking now uses the `m` prefix whenever the next square holds a non-pet monster ("You move right into it" costs a turn but never attacks). Pets are shown in reverse video and still get swapped.

## 2026-09-29 18:56 — Don't step off Elbereth
Two runs in a row (a rothe on Dlvl 6, an ape on Dlvl 7) ended the same way. Jev healed on Elbereth to about 35% HP, then walked off toward an item or to explore while the monsters were still 2–3 squares away. It took a big hit, and the re-engrave came out garbled. Now, while standing on a verified Elbereth below 75% HP with any non-@ hostile within 7 squares, the only choices are staying put, praying, quaffing or eating.

## 2026-09-29 19:07 — Praying every four turns
Two runs died "while praying". Each got bitten by a were-creature ("You feel feverish"), and lycanthropy was on the list of fatal conditions that skip the prayer timeout. The first prayer cured it. The next bite re-infected Jev, so Jev prayed again 3 turns later: −3 Luck and an angry Tyr ("Thou hast angered me", then "Thou durst call upon me? Then die, mortal!"). Lycanthropy now follows the normal timeout. The normal gap goes from 600 to 1000 turns: after a successful prayer the timeout is rnz(350), which has a long tail. The low-HP gamble with a monster adjacent (≥300 turns) stays.

## 2026-09-29 19:18 — ...but starving is worse
The 1000-turn gap cost a run right away: Jev prayed for HP at T1807, had no food, was Weak by T2444, and fainted to death at T2704 because the gap forbade praying. Starvation is certain, and a too-early prayer only probably fails. The gap is now 600 turns when Weak and 300 when Fainting, and stays 1000 otherwise.

## 2026-09-29 19:36 — Elbereth, third time
A rothe/bugbear death on Dlvl 5 showed 5 "garbled" engravings out of 8. The read-back tally explained it. Most rejects looked like "There is an open door here.  Something is written here in the dust.--More--": the actual "You read:" line sat on the next screen and then got deduped away. elbereth_ok now pages through every --More--. Since then, rejects are real (\"Elbe?eth\", \"ElLereth\"): 15 of 49, the ~30% the 1/25-per-letter dust rule predicts.
Also from the source: a monster scared by Elbereth with nowhere to flee (crowds, corridors) attacks anyway (`panicattk` in monmove.c). That explains "got hit while standing on Elbereth".
Other deaths this hour:
- An acid blob corpse eaten at low HP (1d15 acid damage). Acid blob and spotted jelly are now never eaten.
- A 5.0 mine shaft: a hidden trap door that dropped a 16-HP Jev several levels, with d(levels,6) fall damage. Accepted as bad luck.

## 2026-09-29 19:48 — Blind in Minetown; the naked Valkyrie
- **Killed by a watchman, Minetown.** A yellow light exploded and blinded Jev. Jev kept exploring blind and walked into an unseen peaceful watchman ("Wait! There's something there you can't see! It gets angry!"). The whole watch came. While Blind, the choices are now waiting, praying, quaffing, eating and attacking what's hitting you.
- **Giant beetle, Dlvl 7, at AC 10 with no weapon.** A monkey stole the +3 small shield at T2338. Jev picked it back up but never wore it: "Wear" was offered 194 times and lost to "Explore" every time. Later the spear went too, and there was no wield option at all. Now, with no weapon wielded, the only option is to wield the best weapon carried (one-handers only, because of the shield). With nothing hostile near, wearing carried armor is automatic. Failures are remembered so they can't loop.

## 2026-09-29 20:11 — The warhorse and the pink potion
Dlvl 8, XL6, T4598: the best-equipped Jev yet (AC 3, iron shoes, cloak, helm, shield). A warhorse (speed 24) caught it. Three Elbereth tries in a row printed "You write in the dust with your fingertip.", yet the read-back found nothing: in 5.0 engraving is an occupation, and a fast attacker interrupts it before the first letter lands. That cost 56→8 HP. The fourth try worked ("The warhorse turns to flee"), and then Jev, at 50/50, quaffed an unknown pink potion instead of waiting: sleeping, dead.
Now:
- If an attack interrupts an engraving (nothing written), Elbereth isn't offered again for 5 turns while something is adjacent.
- Unknown potions aren't offered while standing on a working Elbereth.

## 2026-09-29 20:22 — Overcorrected on blindness
The blind rule backfired within the hour. A raven blinded Jev (Dlvl 7, XL6), and Jev picked "Wait until you can see" at 83–95% over the attack options while unseen things bit it from 54 to 3 HP. A prayer refilled HP to 54, and the same thing happened again. While blind with an attack target, the wait option is now gone. Jev still won't walk blind.

## 2026-09-29 20:47 — Shop prison and faster Jev calls
- At T480 Jev ate a jackal corpse lying in Chicoutimi's general store ("You bite that, you pay for it!"). It had no gold, so the shopkeeper blocked the door for about 6000 turns while Jev tried "explore" and "door" over and over.
  - While it was stuck, a shopkeeper '@' was also mistaken for Jev because the cursor was off the hero. Fixed by redrawing with Ctrl-R and picking the '@' nearest the last known position.
- Fix:
  - No eating or pickups while standing in a shop.
  - A debt flag is set by "no gold or credit", "you pay for it" or "Pardon me, <Name>", and cleared by "You paid" and similar.
  - While in debt, the only options are selling non-worn items and paying.
  - Pay comes up as a "Pay for which items?" menu, which settle() used to Esc. act_pay now selects all.
  - Result: a towel sold for 25 gold, Jev paid 19 for the corpse and walked out at T6426.
- Jev latency: the client opened a new TLS connection for every call. With keep-alive the median went from 144 to 101 ms (p90 from 182 to 149).
  - Prompt size and option count don't affect latency.
  - Calls with a single option were already skipped.

## 2026-09-29 21:00 — Harness speed; floating eye; low-HP exploring
- I read olivier-motium/jev-doom for speed ideas.
  - Its gateway uses Node fetch, which keeps connections alive; we now do the same.
  - The engine runs in real time on its own thread and keeps executing the committed tactic while the next Jev call is in flight. That doesn't carry over to turn-based NetHack beyond our multi-turn macros (explore, search, rest).
- Measured: Jev calls were only **17% of wall time**. The harness took about 490 ms per decision.
  - Snapshot parsing is about 1 ms.
  - Almost all the rest is Term.pump waiting for 40 ms of pty silence after every keypress.
  - Local idle is now 15 ms (Hardfought stays at 300 ms). Throughput went from 13.5 to 22 game turns/s.
  - Early stops rose, but all 96 "monster came into view" stops had a real monster at the next decision, so no partial frames.
- decisions.jsonl now logs ms.build and ms.act per decision (median build 44 ms).
- Died frozen by a floating eye with a giant ant in view: kill_blocker chose the eye. The eye is now excluded while other hostiles are in view or HP is below 90%.
- Giant beetle death: Jev explored at 11/65 HP. Below half HP with nothing near, exploring and descending options are now removed so it rests.

## 2026-09-29 21:02 — Werejackal and shop-door deaths
- Died of fainting while in werejackal form. "You turn into a werejackal!" at T2074 was never flagged as lycanthropy; only "You feel feverish" was, and that message was missed. Both messages now set the flag, which triggers prayer.
- Killed by Mr. Kipawa on Dlvl 5. At T1288 Jev had kicked open a locked door, most likely a shop closed for inventory whose dust sign had been scuffed away. Once a downstairs is known, locked doors are no longer kicked.

## 2026-09-29 21:15 — Fetch visible items
- Two more deaths from fainting (homunculus, dust vortex). Jev never walked to items it could see; it only picked up what it happened to step on. Its only food was corpses from its own nearby kills.
- New 'fetch' option: go look at the nearest unvisited item square within 15 steps. Rocks, boulders, shop-like clusters (6 or more objects within 3 squares) and corpses seen appearing (goto_corpse covers those) are excluded.
- First minutes: it found a food ration at T2117 and now carries 3 food rations and a tripe ration.

## 2026-09-29 21:40 — Lessons from jev-doom; safety rubric; pace
- Re-read jev-doom (tactics.py, harness.py). Useful ideas:
  1. Rubric decomposition: independent progress, exposure, evidence and tactic picks in one call.
  2. Each option carries a prediction that is measured as met or not met and fed back into the state.
  3. Code prunes infeasible options with stated reasons and caps the menu at 7.
  4. Option labels state the payoff with numbers.
  5. Facts discovered through probes go into the question wording.
  6. Watchdog, backoff and checkpoints.
  7. "Observe" options are rationed.
- Adopted (1): a 'safest' choice question ("best chance of still being alive in 20 turns") asked in the same call. When danger ≥ 0.6 its pick overrides 'action'.
  - Before recent deaths, danger was 0.6–0.87, against a run median of 0.13–0.26.
  - Latency is unchanged (median 97 ms with 3 questions).
- Pace: Jev now descends only down to Dlvl XL+1 (it could reach XL+2 before) and is offered the way back up from XL+2. Recent deaths clustered at Dlvl 5–7 around XL 5–6.
  - The "take the stairs anyway" escape hatch no longer needs too_deep.
- The first game on the new pace survived past T10500.

## 2026-09-29 21:45 — more lycanthropy
- A wererat Jev (animal form, armor fallen off, Valkyrie pack = Overloaded, HP 5) tried to ascend 291 times without moving, then died to a werejackal at T4486.
- When Overloaded, the only options are pray or drop a non-worn item.
- In were-form (status title starts with "Were"), Jev prays after a 500-turn gap instead of 1000. Lycanthropy is major trouble, so a prayer cures it.
- In were-form, pickup/wear/fetch options are hidden. Normal pickup and wear come back after Jev reverts.

## 2026-09-29 21:46 — idle-search deadlock
- The user asked why Jev was searching in a shop. It wasn't in the shop: it was in a corridor on Dlvl 6 at XL 5. The pace cap (Dlvl ≤ XL+1) blocked the stairs and the level was fully explored, so the only option left was "Search 10 turns", repeated for 400+ turns and eating food.
- The "descend anyway" fallback needed lv.resets, which only increments when no downstairs are known. That's a deadlock. The fallback now fires whenever nothing else is on offer.

## 2026-09-29 21:52 — starvation: angry god, buy food
- Hunger is involved in 17 of 110 deaths, the biggest single cause. The Dlvl 10 run (the best yet, T10988) went like this:
  - It prayed while Weak 897 turns after its last prayer. The god was "displeased": rnz timeout tail, Luck -3, god angered via gods_upset.
  - 300 turns later it prayed again, hoping, while Fainting.
  - It died Fainting on Elbereth with 236 gold, falling down a hole.
- A "displeased" / "Thou durst call upon me" message now sets god_angry, and prayer is never offered again that game.
- Food in shops:
  - A shop_food option walks to '%' items in shop clusters when Jev has ≥5 gold and fewer than 3 food items.
  - A buy_N option picks up a for-sale food item Jev can afford, then pays.

## 2026-09-29 22:32 — Sokoban
- jev/sokoban.py holds 8 solutions for the 5.0 levels (soko1..4 × 2 variants). Four came from replaying the NetHackWiki solutions against the 5.0 maps. The other four (both bottom levels and both soko2 levels) came from a pit-by-pit DFS solver, because 5.0 changed those maps and added rolling-boulder traps. test_sokoban.py replays all 8 and checks every mirror orientation.
- In game: the bot matches the premapped walls, including 5.0's random h/v flips. Jev then gets one "push boulder X" option at a time, and nothing else unless monsters are near. Pathing in Sokoban never steps on ^ or 0 and never squeezes diagonally. If a boulder isn't where the plan expects, the bot abandons Sokoban. On the Oracle+1 level, the second up staircase is offered as "Go up into Sokoban".

## 2026-09-29 22:38 — finding the Sokoban stairs
- A run reached Dlvl 10 and walked right past Sokoban. The bot takes the downstairs as soon as it finds them, so it never saw the second '<' on the level below the Oracle. Now the Oracle level is recognized by its four fountains. On the next level down, the bot doesn't descend until a second '<' shows up or there's nothing left to explore.

## 2026-09-29 22:52 — no "hold position" when surrounded
- A werejackal's summoned pack surrounded Jev. Jev then picked "Hold position one turn (let monsters come to you)" three times and went from 42 to 0 HP. That option is now only offered when nothing hostile is adjacent.

## 2026-09-29 22:58 — first Sokoban attempt
- Jev found the Sokoban stairs below the Oracle (T6408). The bot recognized the level as a mirrored soko4-1 and made pushes 1–6 correctly. Push 7 sent a boulder onto a rolling-boulder trap. It rolled into a hole, exactly as the solver's model predicted, but the roll animation outlasted the screen read, so the bot saw Jev still standing behind a boulder and called it a failed push. It retried, then found the boulder missing and abandoned the level. Now a "rolls away" message counts as a successful push, and the bot waits for the animation before reading the screen again.

## 2026-09-29 23:10 — tins are food
- A mumak killed Jev while it was fainted from hunger, even though it had carried an unidentified "tin" for 1000 turns. FOOD only matched identified "tin of X", so eating the tin was never offered. The regex now matches any tin. act_eat clicks through the "not so easy to open" --More-- messages and answers the tin's "Eat it?" prompt, declining anything on the NEVER_EAT list.

## 2026-09-29 23:16 — nymphs
- A rothe killed Jev while it was fainted at T3433. Earlier, water nymphs had stolen the food ration, then the spear and the +3 shield, and then the slime molds. Jev also wielded an unidentified flail to replace the stolen spear, and it turned out cursed. Now, when a nymph is 2–6 squares away and in a straight line, throwing a missile at it is the only choice besides praying and eating.

## 2026-09-29 23:21 — blind vs. invisible quasits
- Three invisible attackers (a quasit pack) killed a blind Jev on Dlvl 6. Its Dex was drained from 6 to 3. The Blind filter only allowed fighting, praying, quaffing and eating, so Elbereth was never offered, even though you can engrave while blind. Elbereth is now allowed while blind. It's no longer offered while levitating (Jev had quaffed levitation and can't reach the floor then).

## 2026-09-29 23:24 — leave nymph levels
- A dust vortex killed Jev while it was fainted. One wood nymph on Dlvl 2–3 had kept teleporting back and stolen the shield, scrolls, bag, spear, part-eaten ration and egg, leaving no food. After any nymph theft, the bot now heads for a known downstairs as long as that stays within the pace limit (Dlvl ≤ XL).

## 2026-09-29 23:29 — gamble prayer at range
- A quasit zapped a wand of magic missile at Jev from range and took it from 29 HP to 0. Elbereth doesn't stop ranged attacks, and the gamble prayer (at least 300 turns since the last one) needed an adjacent monster. Now any hostile within 7 squares, or an unseen attacker, qualifies. By my estimate, a prayer about 390 turns after a successful one works roughly 70% of the time.

## 2026-09-29 23:59 — don't camp on Elbereth when healthy
- One run sat on Dlvl 4 from T724 to T6265, with about 1,400 "Stay on Elbereth" waits after T4500, at 72–77/80 HP and next to a fog cloud (speed 1). Elbereth blocked attacking, and "waiting heals you safely" appealed to Jev. Now, at 90% HP or more, the Elbereth wait isn't offered and attacking from Elbereth is allowed.

## 2026-09-30 00:05 — don't walk into packs
- Best run in a while: XL 7, 91 max HP, T7824. Jev stepped off Elbereth to "close in on" a warg, and the whole pack arrived: 69 HP to 0 in four turns. Close-in isn't offered now when three or more hostiles are near and their combined difficulty is more than twice Jev's experience level.

## 2026-09-30 00:11 — levitation boots
- Jev put on unidentified boots at T1285. They were -2 levitation boots, and for about 2,400 turns it floated over the downstairs pressing '>' ("You are floating high above the stairs"), then starved. Now any worn levitation item is taken off first whenever no monsters are near, and levitation items are never offered to wear.

## 2026-09-30 00:17 — nymph filter too strict
- The nymph-throw filter left "throw at the nymph" as the only option while a fire ant was biting Jev at 10/52 HP, and it died. The filter now applies only when nothing hostile is adjacent.

## 2026-09-30 00:23 — empty options: take the stairs
- A 9600-turn run starved after about 1,100 turns on Dlvl 6 choosing "Search 10 turns" about 200 times, with the downstairs in view. build_options came back empty, and decide() fell back to searching. I couldn't find which filter emptied it (replaying the saved screen without the level memory gives normal options), so the fallback now takes a reachable downstairs and logs a "no options" warning so the next case can be traced. Also, "orange gems" no longer count as food.

## 2026-09-30 00:53 — paused: Jev budget exhausted
- The $5.00 Jev budget cap (runs/budget.json) was reached at the start of run 20260930-002321, and play has stopped. I didn't raise the cap. That's the operator's call.
- Fixed tonight: Sokoban solutions and play (first real attempt got 6 pushes in; then fixed rolling-boulder pushes), holding descent below the Oracle to find the Sokoban stairs, hold-position when surrounded, eating tins, nymphs (throw at them, leave their level), Elbereth while blind, gamble prayer at range, no Elbereth camping when healthy, no closing in on strong packs, taking off levitation boots, and an empty-options fallback that takes the stairs.
- Best recent runs: T9602 Dlvl 7 and T7824 Dlvl 7 (XL 7). No ascension yet.

## 2026-09-30 — root cause of the "no options" searches (offline, budget paused)
Run 20260930-001801 searched ~1100 turns on Dlvl 6 with `>` in view. At XL 5 the pace gate hid `descend`; the only option left was a locked door. The "don't kick locked doors when downstairs are known" filter ran *after* the empty-options guards, so it emptied the list and decide() fell back to searching. Moved that filter above the guards, so now "Take the downstairs anyway" gets offered.

## 2026-09-30T15:32Z — resumed
The user OK'd a $25 credit. The server now runs with `JEV_BUDGET_USD=25` (total, $5 already spent).

## 2026-09-30 — invisibility blinds the bot (soldier ant, T5244, Dlvl 8)
Jev put on a +0 cloak of invisibility. In 5.0 an invisible hero with no see-invisible gets no `@` on the map. `Snapshot.find_me` then locked onto a nearby elf `@`. The bot's "monsters in view" became terrain descriptions around the elf, and Jev searched and rested while a soldier ant and a lizard chewed it from 75 to 0 HP (it prayed once in between). Fix: never wear an identified cloak of invisibility, and take it off at once if worn, even with monsters near (it shares the levitation remove path).

## 2026-09-30 — force the late gamble prayer (rothe/Woodland-elf, T5087, Dlvl 8)
Jev had AC 9 and meleed a Woodland-elf from 70 HP down to 8 (elves are `@` and ignore Elbereth). The gamble prayer was offered 702 turns after the last prayer, and Jev threw darts instead. Prayer fixes low HP when the timeout is under 200. Timeout starts at rnz(350) and drops 1 per turn, so 500+ turns later it is usually safe. A low-HP gamble at 500+ turns is now forced the way a safe prayer is.

## 2026-09-30 — stop re-engraving under attack (tengu, T3479, Dlvl 6)
With a tengu biting, Jev tried Elbereth 4 times in a row: 3 came out garbled and 1 was interrupted. Getting hit scuffs dust, so every try cost a turn and ~6 HP without a swing back. A garbled result now blocks Elbereth for 5 turns while something is adjacent, the same as an interrupted one. The death came at 12/58 HP, above the 1/7 prayer line, so praying would not have healed.

## 2026-09-30 — second Sokoban attempt (soko4, 16 of ~20 pushes)
Jev found and entered Sokoban at T2429. The rolling-boulder fix worked twice (T2455, T2464). Push 17 still desynced. At T2476/2478 a push onto a rolling-boulder trap printed its "rolls away" message only after act_soko had already read the messages. The push was scored as failed, the retry shoved a different boulder, and the plan fell apart. act_soko now always waits for the screen to settle before judging, and counts a push as done if the boulder has left its square, not only if we stepped into it.

## 2026-09-30 — no "retreat" when there is nowhere to go (two ogres, T3455, Dlvl 6)
Two ogres cornered Jev 5 turns after it prayed, so prayer was out. Jev picked "Retreat one step" 7 times and every one came back "nowhere to retreat", with no turn used each time. The stall guard only dropped the option after 3 tries per turn. Retreat is now offered only when an open square exists.

## 2026-09-30 — starving next to a corpse (bat, T3207, fainted)
With no food left, Jev turned Weak and prayed 639 turns after its last prayer. It failed ("Thou art arrogant"). Jev then fainted for 200 turns until a bat finished it. It had been standing on a floating eye corpse of unknown age, which the bot treats as rotten. Lichen and lizard corpses never rot, so they are now always offered. When Weak or Fainting with no prayer available, a corpse of unknown age is offered too, since risking food poisoning beats certain starvation.

## 2026-09-30 — stay on Elbereth when a pack surrounds (bugbears, T3443, Dlvl 6)
At XL 4 on Dlvl 6, Jev sat safely on Elbereth at 40/44 HP with two bugbears, a hobgoblin, a kobold, a goblin and a gnome around it. Above 75% HP it was free to act, so it threw shuriken and stepped off. It was at 9 HP three turns later and dead on the fourth. That is still above the 1/7 line, so prayer could not help. With a pack in view, standing on Elbereth now forces "stay" at any HP. Also seen: the "Monsters in view" text sometimes swallows top-line messages ("The bugbear hits! ... 1 step west"). Not fixed yet.

## 2026-09-30 — prayer odds from rnz(350); stale farlook names
statico/nethack-tools' prayer timer models the timeout as it is set in the source: 300 at start, then rnz(350) after each successful prayer. Simulating that, a prayer for major trouble (fixed when timeout < 200) succeeds with P = .66 at 300 turns since the last prayer, .87 at 500 and .94 at 1000. The curve is nearly flat past 500, so the "safe" prayer for low HP now fires at 500 turns instead of 1000. Waiting to 1000 only let Jev die with a probably-working prayer unused.
farlook: a reply that doesn't start with "<glyph> " is a stale top-line message. It used to become the monster's name ("The bugbear hits! ... 1 step west"). Such replies now fall back to "unidentified". Live names still parse.

## 2026-09-30 — #terrain finds stairs under objects
One game spent 260+ turns on a Minetown-style Dlvl 6 (shops, temple, rock piles everywhere), alternating explore and search, with "no unexplored edges left" and no '>' ever seen. A downstair under an object pile never shows as '>'. When nothing is left to explore and no '>' is visible, the bot now runs `#terrain` (known map without monsters, objects and traps), at most every 300 turns per level. Any '>' it finds is remembered in `Level.stairs`, which feeds `downs`. Also turned off 5.0's `tips`, whose farlook tutorial popped up over the terrain view.

## 2026-09-30 — don't chase unicorns (gray unicorn, T6045, Minetown)
A cross-aligned gray unicorn (speed 24, butt d12 + kick d6) hovered 2 squares off Jev's Elbereth. When the engraving wore off, Jev chose "Close in on gray unicorn" at 38/55 HP and lost 24 HP in one turn. Its prayer was 53 turns old. Unicorns keep out of line and outrun you, so closing in only gives free hits. There's no approach option for unicorns now.

## 2026-09-30 — any low-HP prayer is forced (human zombie, T4535, Dlvl 6)
At 1/58 HP, Jev was offered the gamble prayer 478 turns after its last prayer and tried Elbereth instead. It was interrupted and Jev died. The "force at 500" cutoff from earlier today missed this by 22 turns. The gamble is only offered at 300+ turns (P ≥ .66), which beats anything else at LOW_HP, so any offered prayer is now forced at LOW_HP. Also: #terrain fired live once and found a hidden '>' at (15,12).

## 2026-09-30 — no eating mid-fight (giant rat, T2344, Dlvl 2)
While Hungry (not yet Weak), Jev ate corpses twice with a gecko, a giant rat and a jackal next to it, and dropped from 25 to 1 HP. The forced prayer then failed; it came 867 turns after the last one, so it should have worked about 90% of the time. Eating options are now removed while a non-passive hostile is within 2 squares, unless Jev is Weak or Fainting.

## 2026-09-30 — prayer results are now logged (ape, T8587, Dlvl 7)
This was the best game this session: T8587 and Dlvl 7, with 8 prayers roughly 400–1300 turns apart. The last one failed 770 turns after the previous one. An ape, a rothe, a rock mole and a lizard took Jev from 49 to 4 HP in 3 turns. I found no luck penalties in the messages, and rnz(350)'s long tail makes about 1 prayer in 8 fail. The pray outcome now includes the game's messages, so failures ("displeased", "smiting") can be told apart from bad luck.

## 2026-09-30 — no resting beside unseen attackers (hill orc, T3212, Dlvl 6)
A yellow light blinded Jev. It then rested twice at 21/52 HP while "You feel an unseen monster!" and "It misses!" scrolled past, and the orcs killed it. unseen_attacker() now also matches "misses" and "feel an unseen monster", and rest is not offered while it fires. That leaves attacking the I or Elbereth.

## 2026-09-30 — Sokoban gives up when stuck (T4518, Soko level 1)
The waits added after each push worked: 20 pushes in a row succeeded. After T1995's "The boulder suddenly rolls away from you! ... Thump!", the next push square became unreachable. The plan's boulder was still there, so the "level no longer matches" exit never fired, and Jev spent 2400 turns on search_hidden. Now, if a push stays unreachable for 200 turns, Jev marks Sokoban done and moves on. Replanning with sokoban.Solver is the upgrade if this becomes common.

## 2026-09-30 — only the kill's own square counts as a fresh corpse (food poisoning, T4779, Soko 1)
While Weak, Jev ate an ape corpse: "Ulch - that meat was tainted! You feel deathly sick." It prayed next, but Tyr was "displeased" (the new prayer log shows this), so the food poisoning killed it. The corpse had been marked fresh because it was first seen within 2 squares of a "You kill" message. The server restart had wiped the corpse memory, and an old corpse next to a new kill looks the same. A corpse now counts as fresh only if the previous screen showed a monster on that square.

## 2026-09-30 — Sokoban re-plans from the screen (starved at T34423 in Sokoban)
The worst game this session. On the first Sokoban level (soko4-1), push 29 of the stored solution became unreachable. The 200-turn give-up then left Jev in a pocket sealed by its own pushed boulders, with no way down to '>'. It searched for hidden passages for 31,000 turns, praying for food when it could, and starved.

Now, when the next push is unreachable for 30 turns or its boulder is missing, `sokoban.replan()` solves the level from the current screen. It takes the '0' squares as boulders, the level's own pits that still show '^' as holes, and the rollers from the level file, then follows that plan. It tries at most 3 times per level before giving up. sokoban.json now also stores pits and rollers. The existing solver solves every level from a 90%-solved state (test_sokoban.py). From a fresh start it can't do soko1-1, soko1-2, soko2-1 or soko3-2, which is why the stored wiki solutions remain the first choice.

## 2026-09-30 — Sokoban rollers are walkable (root cause of the push-29 stalls)
The re-plan fired but produced the same first push, (34,16) north, and gave up after 3 tries. The square behind that boulder is only reachable across (39,16), a '^' that is a rolling boulder trap and not a hole. In Sokoban, trap.c makes these harmless ("the Sokoban rolling boulder traps are not dangerous"), and the solver treats them as floor. The bot's pathfinding refused every '^' in Sokoban, though. That single square caused both soko4-1 stalls (the Thump game and the 31,000-turn starvation). The level's rollers (`sokoban.rollers(m)`) are now walkable, and holes still aren't.

## 2026-09-30 — Sokoban holds; no leaving mid-puzzle
Live check of the roller fix: Jev stepped on the roller ("Click! You trigger a rolling boulder trap! No boulder was released."), re-planned (60 pushes, then 41 after a restart) and got through 33 of 41. Two small fixes along the way:
- When the push fails with "You hear a monster behind the boulder", Jev now searches one turn instead of retrying in the same turn.
- Fixed a KeyError when a re-plan ran before any stuck timer existed.

Then a peaceful gnome king counted as `near`, which lifts the push-only filter, and Jev fetched gloves and took the '>' out with 8 pushes left. 'descend' is now removed while a Sokoban level is unsolved.

## 2026-09-30 — enforce the pace rule (death analysis)
Last 60 deaths: median T4134, Dlvl 7, XL 5. 13 were hunger, 4 were failed prayers, and 43 were fights against about 40 different monsters, none dominant. In 25 of the 60, the deepest level was 2+ below XL. Level changes that landed Jev 2+ levels past its XL came from the "Take the downstairs anyway" fallback 165 times and from "Head for the downstairs" 19 times. That fallback fires when a level has nothing left to do.
- The fallback now waits first. Past XL+1, Jev rests and searches up to 400 turns on the cleared level (monsters come to it and HP recovers), unless it is Hungry or worse.
- 'ascend' (offered at Dlvl ≥ XL+2) is now forced whenever no hostile is adjacent. Before, it was only an option and Jev rarely picked it.

## 2026-09-30 — pace check; no re-engraving after a hit on Elbereth
First game with the pace fix: never more than 2 levels deeper than its XL (Dlvl 6 at XL 4). It rested 76 times and was sent back upstairs 105 times. It died on Dlvl 5, T5315 (magic missile), cornered by a gnome mummy, rothes and garter snakes. Monsters that can't get away attack even through Elbereth. Jev kept engraving, getting hit and engraving again. A hit on Elbereth now blocks engraving for 5 turns while a monster is adjacent, which leaves fighting or retreating.

## 2026-09-30 — stay up after fleeing upstairs
Died to a wolf, Dlvl 6, T5172. A warg and wolf pack hit Jev while it stood on Elbereth, and it fled up the stairs. On the very next decision it took the stairs back down into the pack and was eaten. Fleeing upstairs now blocks descending for 50 turns.

## 2026-09-30 — Sokoban: replan when a push fails "in vain"
On soko3-1, push 142 of 175 (a replanned route), Jev tried the same push for 200+ turns. Every try gave "You try to move the boulder, but in vain": something unseen was behind the boulder. A failed push never counted as stuck, so the replanner never ran. An "in vain" failure now forces an immediate replan. After 3 replans, Jev leaves the level.

## 2026-09-30 — melee adjacent monsters; honest threat labels
Killed by an owlbear on Dlvl 7, T6785, at XL 7 with 70/76 HP. After one Elbereth attempt was interrupted, Jev threw darts at the adjacent owlbear 4 turns running instead of meleeing with its spear, and dropped 60 → 49 → 35 → 18 → dead. The prompt also called the owlbear "weaker than you": the label was difficulty − XL − 1, which counts difficulty = XL as weaker.
- Missiles are now offered only at range 2+. Passive monsters (floating eyes, molds) are still the exception.
- Threat labels now use difficulty − XL, so difficulty = XL is "about your level".

## 2026-09-30 — stall guard for blocked walks
On Dlvl 6 Jev spent about 3500 turns (T4000–T7486) picking "Search for hidden passages". Each try ended "blocked after 1 steps" against the shopkeeper in a doorway, with a floating eye next to it. Every bump costs a game turn, and the stall guard only fired when the clock stood still. Now an option that comes back "blocked" 5 decisions in a row is dropped for the next decision.

## 2026-09-30 — blind in a shop: don't swing at the unseen shopkeeper
Killed by Ms. Tipor the shopkeeper, Dlvl 7, T5068. Jev was blind in her shop ("You feel no objects here") and picked "Attack an unseen creature". That creature was the shopkeeper: "You miss it. It gets angry! Halt! You're under arrest!" Her wand of striking took it from 51 HP to dead in 5 turns. The game before ("killed by a wand" beside "for sale" items, attacking unseen creatures) looks like the same thing. While blind, Jev keeps attack options on purpose, because unseen biters had drained it while it rested. Now, when it is blind in a shop and nothing unseen is hitting it, the attacks are dropped.
(81bb732 shipped with a syntax error; fixed in the next commit.)

## 2026-09-30 — a blocked walk with a monster adjacent isn't retried
Killed by a hill orc on Dlvl 8, T6782, XL 6. A prayer restored Jev to 80/80. It then picked "Head back upstairs" 5 times (the pace rule offers it at Dlvl ≥ XL+2), and each try was "blocked after 1 steps" by the orc pack in the way. HP went 75 → 62 → 47 → … → dead, and it never swung at the "weaker" hill orcs. Now a move that just came back blocked, with a hostile adjacent, isn't offered on the next decision.

## 2026-09-30 — no potion gambling while a prayer is ready
Killed by a pony "while frozen by a potion", Dlvl 5, T3917. At 15/50 HP (not yet low enough for prayer to count it as trouble: HP ≤ 1/5 max at XL 4) Jev drank an unknown swirly potion. It was sleeping. The last prayer was 1460 turns earlier, so a prayer at 10 HP would almost surely have worked. While a prayer is ready (800+ turns since the last, or never prayed and past turn 300), unknown potions are no longer offered; known healing potions still are.

## 2026-09-30 — no exploring with a hostile adjacent
Killed by a sewer rat on Dlvl 4, T1354, XL 3. A wererat summoned a rat pack. At 21/29 HP with 5 rats adjacent, one Elbereth came out garbled, and then Jev picked "explore" twice. It walked while they bit, 21 → 7 → dead, and prayer wasn't available (HP 7 > 5). Now, while a non-passive hostile is adjacent and an attack is possible, explore and search options are dropped.

## 2026-09-30 — a Sokoban replan no longer walks Jev out
Seen at T6354–6414 on soko4-1 (3 boulders left): each time Jev entered, the plan was stale ("push 48 off-plan") and the replan found a 41-push solution. But the decision that replans has no push option yet, so the only option left was "Take the downstairs anyway". Jev walked out, came back, replanned again, and after 3 rounds hit the replan cap and gave up the level. The "anyway" fallback is now off on an unsolved Sokoban level: Jev waits one turn, and the next decision pushes from the new plan. (Offline, the replan on the saved screen is correct: its first push is on a real boulder.)

## 2026-09-30 — never drink known-bad potions
Killed by a carnivorous ape "while sleeping", Dlvl 9, T9512 (the longest game in a while). Held by the ape at 12/66, with the prayer only 284 turns old, Jev was offered and drank "a potion of sleeping", already identified. The emergency-quaff option now skips potions identified as sleeping, blindness, hallucination, confusion, booze, sickness, paralysis, water or oil.

## 2026-09-30 — bumping a shopkeeper no longer walls off the shop door
Killed by a coyote "while fainted from lack of food", Dlvl 3, T5853. From T3100 Jev was inside a shop and never left. It prayed off hunger three times, spent 2700 turns on "Search for hidden passages", and fainted. The bot never saw a way out. A walk that bumped the shopkeeper ("Pardon me, Upernavik") marked the square as blocked once the shopkeeper had stepped off it. That square was the doorway, and a door glyph isn't '.' or '#', so the shop's only exit was blocked for the rest of the level. The downstairs became unreachable, and with no frontier left Jev searched walls. (Probably also the 3500-turn floating-eye shop stall earlier today.) A step where a monster stood before the move, or where the game said "Pardon me", is no longer marked blocked.

## 2026-09-30 — no "anyway" descent into the forced-ascend zone
Killed by Green-elves on Dlvl 9, T5351, XL 7. The forced ascend (Dlvl ≥ XL+2) took Jev up to 8. Two turns later "Take the downstairs anyway" took it back down to 9, because that level had already used its 400 searched turns. On 9 it met the elves at the stairs. Now the 400-turn cap is ignored when the next level would be XL+2 or deeper: Jev keeps resting unless Hungry.

## 2026-09-30 — emergency prayer gamble from 100 turns
Killed by an elven arrow, Dlvl 4, T5218. Ants and a Woodland-elf wore Jev down to 3/54, 243 turns after its last prayer. The low-HP "gamble" prayer was gated at 300 turns, so it wasn't offered, and Jev died retreating. pray.c: in major trouble a prayer works if the prayer timeout is ≤ 200. The timeout was set to rnz(350) and drops by 1 a turn, so t turns later the chance is P(rnz(350) ≤ 200+t), roughly even at t=100. Failure isn't free (Luck −3, gods_upset → angrygods), but at LOW_HP with a monster attacking, death is nearly certain otherwise. Gate lowered to 100 turns.

## 2026-09-30 — low HP: prayer beats unknown potions
Killed by a rothe, Dlvl 5, T3559. At 8/43 HP, 346 turns after its last prayer, Jev had two options, pray and quaff an unknown black potion, and it drank the potion. The low-HP filter kept every quaff next to prayer. It now keeps only known healing potions.

## 2026-09-30 — put on carried armor
Checked armor at death for the last 19 runs. Several died at AC 6–10 wearing 0–1 pieces. The rothe death (T3559) had an orcish helm in the pack and no helm on. "Wear X" was offered but lost to exploring every time. With no hostile near, wear options now come first (alongside prayer and eating). act_wear marks anything that fails as unwearable, so this can't loop. Not done yet: swapping body armor for better body armor (banded mail carried over worn ring mail).

## 2026-09-30 — hungry Jev isn't forced back upstairs
Killed by a gecko "while fainted from lack of food", Dlvl 7, T3603. When Hungry, the pace rule lets Jev descend to find food. But the forced ascend at Dlvl ≥ XL+2 sent it straight back up, so its last 150 decisions included 33 ascends and 14 descends, burning food on stairs. The forced ascend now doesn't apply while Hungry, Weak or Fainting. It is still offered as an option.

## 2026-09-30 — eat the fresh corpse underfoot
Last 30 runs: "Eat the X here" was offered 98 times and taken 15. Explore, pickup and fetch won the rest. "Go eat the fresh corpse" was taken 489 of 772 times. The eat option is only offered for a fresh corpse (seen appearing within 40 turns, or a lichen or lizard) and while Jev isn't Satiated, and hunger is still the top single killer. With nothing hostile near, it is now forced.

## 2026-09-30 12:58 — clear potions are water
Run 20260930-125222 died blind to a housecat pack on Dlvl 5 (T2814) after spending its low-HP turns quaffing a "clear potion" (plain water) four times. Unidentified clear potions are now excluded from the quaff options.

## 2026-09-30 13:05 — no ranged attacks in shops
Run 20260930-125818 threw a dagger and then zapped an unknown wand at a brown mold inside Sipaliwini's general store. She turned hostile and killed Jev with her wand (T1314, Dlvl 4). Throw and zap options are now dropped near shops.

## 2026-09-30 13:20 — no throwing past an adjacent attacker
Run 20260930-130259 (Dlvl 8, XL 6) spent three turns throwing daggers at a distant orc-captain while a giant spider stood next to it, dropping from 19 to 8 HP before a failed gamble prayer. Throw options are now dropped whenever an adjacent hostile can be meleed.

## 2026-09-30 13:35 — digging obeys the pace
The giant-spider run reached Dlvl 8 at XL 6 by digging: the pick-axe option only checked `too_deep` (Dlvl >= XL+2), so it dug from XL+1 straight to XL+2 twice. Digging down now uses the same gate as the stairs (Dlvl < XL+1).

## 2026-09-30 13:50 — Elbereth only when hurt
Run 20260930-131713 (XL 7, Dlvl 7, T9749) engraved Elbereth at 56/64 HP instead of closing on a large kobold; the kobold stood off and zapped a wand of lightning until Jev died. Elbereth is now offered against visible monsters only below 70% HP (still offered when boxed in or hit by something unseen).

## 2026-09-30 14:00 — no looting mid-fight
Run 20260930-132022 (XL 7, Dlvl 8, T6490) died to a Woodland-elf pack after spending three turns picking up an elven helm, dagger and broadsword while elves were hitting it (61 -> 17 HP). Pickup and fetch options are now dropped while an adjacent hostile can be meleed.

## 2026-09-30 14:15 — no diagonal squeezes
NetHack refuses a diagonal step between two walls/rock when the pack weighs over 600 ("You are carrying too much to get through"). The pathfinder planned such squeezes anyway, and the walker kept retrying: 10 of the day's runs logged it, up to 2171 times in one game. Run 20260930-132513 (fell to Dlvl 7 at XL 5, T4501) spent its time bumping these and never found the upstairs before a wolf, a plains centaur and a rothe caught it. The pathfinder now never plans a squeeze (generated corridors are 4-connected, so no real route is lost).

## 2026-09-30 14:25 — retreat only when hurt; squeeze fix confirmed
The first run after the squeeze fix logged 0 "carrying too much" bumps (was up to 2171). It died anyway (raven/hill orcs, Dlvl 6, T2966): at 49-50/53 HP Jev chose "Retreat one step" six turns running while a hill orc pack followed and hit it, then an unknown potion blinded it and a prayer 797 turns after the last one failed. Retreat is now offered only below 70% HP, like Elbereth.

## 2026-09-30 14:40 — catch Tyr's anger
Run 20260930-133759 was "killed by the wrath of Tyr" (T5998, Dlvl 6). The T5378 prayer was answered "The voice of Tyr booms:" and the angry quote itself was never captured, so `god_angry` stayed False; Jev prayed again at T5687 ("rings out") and T5998 and was smitten. Any "voice of <god> booms / rings out" now marks the god angry.

## 2026-09-30 14:55 — mind what stands behind the target
Run 20260930-134227 died to the Minetown watch (T3629, Dlvl 6) right after throwing a dagger at an 'i': a missile that misses flies on, and the watchman beyond it turned hostile. Throws and zaps now also require no '@' within 9 squares past the target (up to the first wall).

## 2026-09-30 15:10 — refresh inventory after quaffing
Twice now Jev "quaffed" the same potion 3-4 times on one turn mid-fight (T2801, and T5616 in run 20260930-135011, killed by a killer bee in the Sokoban zoo): the inventory is only re-read every 25 decisions, so the drunk potion stayed on offer. Quaffing now re-reads the inventory.

## 2026-09-30 15:20 — cure lycanthropy after the fight
Run 20260930-135441 (XL 5, Dlvl 6, T3790) prayed at 18/46 with the wererat still biting: Tyr cured the lycanthropy ("You feel purified"), not the HP, and the prayer was spent when Jev hit 7 HP five turns later. Lycanthropy now counts as prayer trouble only with no hostile within 2 squares.
Checked afterwards (wiki + 5.0 source): lycanthropy is a major trouble, but pray.c's in_trouble() ranks TROUBLE_HIT (low HP) above TROUBLE_LYCANTHROPE, so a later low-HP prayer heals first and still cures the disease when Luck allows fixing several troubles. The shape change comes at 1/80 per turn by day and 1/60 by night (wiki, allmain.c), so waiting out a fight costs little. The deferral stands.

## 2026-09-30 15:45 — fight from corridors, Elbereth for emergencies
Operator note: "the bot gets stuck on elbereth too much. a better strategy might be to flee to a hallway to fight monsters one by one." Measured: in the last 15 games, waiting on Elbereth took up to 44% of a game's decisions.
- Wiki (Corridor / "Fighting in corridors"; orc and soldier pages): in the open a group surrounds you on up to 8 sides, while in a corridor only one or two can reach you. "Against multiple foes, retreat into a corridor so they have to come at you one at a time." Elbereth is breathing room, not a fighting position; @ (humans, elves) and minotaurs ignore it.
- 5.0 source: monmove.c onscary() matches the wiki's exceptions. The 3.6 rule "each flee erodes a letter" is gone; a dust Elbereth erodes on your attacks (uhitm.c u_wipe_engr(3)), when you are hit, and at random about 1/(40+3·Dex) per turn (allmain.c). Engraving typos: 1/25 per letter, so about 28% of dust Elbereths come out garbled.
- Change: a new "Fight from a corridor" option. With 2+ hostiles within 5 and Jev on an open square, it walks up to 8 steps to the nearest corridor or doorway square (2 or fewer open neighbours) that is no closer to the pack. When that option exists and HP is at least 40%, Elbereth is not offered. Waiting on Elbereth now stops at 70% HP (was 90%).

## 2026-09-30 16:05 — held: fight or Elbereth, don't walk
Run 20260930-140029 (Dlvl 7, T5125) closed on a rope golem, got grabbed and choked, then spent its last three turns on "Retreat one step" ("You cannot escape from the rope golem!"). 5.0 hack.c: a held hero's move escapes only on rn2(40), 7.5% (37.5% if the holder is helpless). Wiki (Rope golem): engrave Elbereth, which works while grabbed, or pick it off at range. Now a grab/choke message marks Jev held for that turn and the next, and only attack, Elbereth, pray and quaff are offered. (The game recorded the death as "wrath of Tyr", but both of its prayers were well-received; the choking did the damage.)

## 2026-09-30 16:20 — no waiting on Elbereth next to elves
Run 20260930-140639 (XL 6, Dlvl 7, T4259) killed a Woodland-elf, engraved Elbereth, then waited on it for 9 turns while another Woodland-elf readied its bow, and died to that elf. Wiki and monmove.c onscary(): @ (humans and elves) and minotaurs ignore Elbereth. The engrave option already skipped all-@ threats, but "Stay on Elbereth" did not; it is no longer offered while an @ or a minotaur is near.

## 2026-09-30 16:35 — starving: food over Elbereth
Run 20260930-140948 (Dlvl 5, T2958) prayed for HP at T2660, turned Weak 20 turns later (so no second prayer), then spent 69 turns waiting on Elbereth, Weak and then Fainting, while "Go look at the item (food?)" was on offer. A kitten killed it while fainted. Wiki: Weak is major trouble, so eat or pray; Fainting is next. Now, when Weak or Fainting with nothing adjacent, only eat, go-to-corpse, fetch-food and pray are offered (if any exist). Fetch prefers '%' when starving and is offered even with monsters near.

## 2026-09-30 16:55 — Don't camp on Elbereth while starving
Run 20260930-141404 died at T4709 to a kitten while fainted. It had no food, and with an ape and a floating eye in view it was forced to "Stay on Elbereth" for 23+ turns while Weak. Per the wiki and eat.c (5.0), Weak lasts only nutrition 1–50 before Fainting. So the forced Elbereth wait is now skipped when Weak or Fainting, and the starving filter (eat, fetch food, pray) takes over.

## 2026-09-30 17:10 — Corridor retreat only before the pack closes in
Run 20260930-142011 died at T2116 to apes. At 14/42 HP with two apes adjacent, Jev picked "Fight from a corridor" and walked away, and each step gave them free attacks. The corridor option is now offered only when the nearest pack member is at least 2 squares away. Once the pack is adjacent, Jev fights, engraves or prays instead.

## 2026-09-30 17:25 — No tripe or mid-fight snacks while merely Hungry
Run 20260930-142133 died at T4650 to a black unicorn in Sokoban. Jev was only Hungry, but it ate a tripe ration while the unicorn was adjacent. The 5.0 source (eat.c:2148) gives tripe a rn2(2) chance to cause vomiting for anyone who isn't a caveman or orc, which means confusion and stun for about 15 turns. Jev lost 55 HP while stunned. Now, while only Hungry, Jev won't eat tripe and won't eat anything while a hostile is adjacent. When Weak or Fainting, anything goes.

## 2026-09-30 17:50 — Offer Elbereth while blind and hurt
Run 20260930-143412 died to apes at T6987 on Dlvl 8. A potion blinded Jev at 8/76 HP. The blind branch then only offered "Wait until you can see" (5 turns of searching). The unseen apes' "It hits!" messages got lost inside those rests, so the unseen-attacker check never fired and Elbereth was never offered. Jev now gets the Elbereth option whenever it is blind and below 70% HP. Engraving still works blind, and the blind branch already keeps elbereth in its option set.

## 2026-09-30 18:05 — Wait out a walling floating eye before meleeing it
Run 20260930-144207 died at T7290, killed by an imp while frozen by a floating eye's gaze. In Minetown, peaceful gnomes and a floating eye boxed Jev in, so the "walled" rule immediately offered "Kill the blocker" and Jev meleed the eye. Floating eyes move at speed 1 and peacefuls wander, so now a walled Jev gets "Search 10 turns" first. Meleeing an eye is offered only after more than 200 turns of being walled in.

## 2026-09-30 18:20 — Pray sooner when starving
Run 20260930-144612 died at T5771 on Dlvl 9. It had no food and turned Weak 524 turns after its last prayer. The prayer gate for Weak was 600 turns, so Jev explored instead of praying, fainted, and died beside a pony and a human mummy. Per the 5.0 source, a prayer after a successful one works once rnz(350) minus the elapsed turns is 200 or less, which is about 0.87 likely at 500 turns and 0.66 at 300. Starving with no food is certain death, so the gates are now 400 turns for Weak (down from 600) and 150 for Fainting (down from 300).

## 2026-09-30 18:40 — Fight when engulfed
Run 20260930-145336 died at T8226 on Dlvl 6, in a brawl with a vortex, a winter wolf cub and a fire breather. When the vortex engulfed Jev, the status showed Blind, so the blind branch offered only "Wait until you can see". Jev waited twice inside the vortex and went from 51 to 13 HP. Now, if the latest engulf/expel message in recent messages is "engulfs you", the options are just "Attack the monster engulfing you" (F k: from inside, any direction hits the engulfer) plus pray and quaff.

## 2026-09-30 19:00 — Take the fresh corpse
Run 20260930-150259 died at T7754, frozen by a potion vapour and killed by a pony after about 500 turns of Fainting. This Jev prayed for food 6 times in 7700 turns, and the 6th prayer failed ("Tyr is displeased"). Across the last 6 runs, "go eat the fresh corpse" was passed up for explore, rest or search about 60% of the time. Per 5.0 eat.c:1892, an uncursed corpse is safe for about 40 turns and the offer's window is 30, so those were safe meals. The offer is now forced when no hostile is near, the same way eating a corpse underfoot already was. A corpse that turns out to be inedible (a bat) is now forgotten, so it isn't offered again.

## 2026-09-30 19:40 — Retreat only if it gains distance
Run 20260930-151841 died at T4388 on Dlvl 7 to a Woodland-elf archer. At 22/59 HP Jev chose "Retreat one step" four times in a row: west, east, west, east. retreat_dir picked the best neighbouring square even when it was no farther from hostiles than Jev's current square, so Jev swapped squares while taking volleys of 3–4 elven arrows. retreat_dir now returns a direction only if the step strictly increases the distance to the nearest hostile.

## 2026-09-30 20:00 — Hungry is no reason to break the depth pace
Run 20260930-152500 died at T5817 to an ogre and a giant spider on Dlvl 8 at XL6. It got there with "Take the downstairs anyway" from Dlvl 7, even though the pace limit is Dlvl ≤ XL+1. The "rest here instead" alternative was suppressed because Jev was Hungry. Hungry is about 100 turns from Weak, and Weak brings the prayer option, which here was about 1550 turns old and safe. The rest alternative is now suppressed only when Weak or Fainting.

## 2026-09-30 20:25 — Blind in a shop: only swing back at real attacks
Run 20260930-153923 died at T3012 to the shopkeeper Aklavik. A level teleport dropped Jev into her general store, and an exploding yellow light blinded it there. The shop guard allowed blind attacks whenever unseen_attacker() was true, and that also matches "You feel an unseen monster!", which is only sensing. That was the shopkeeper walking by. Jev swung at her, and she zapped it dead. In a shop, blind attacks now require a real "It hits/bites/..." message in the last two turns.
Still unexplained: the shopkeeper blocked the door for about 300 turns even though Jev owed nothing.

## 2026-09-30 20:55 — Don't close in on yellow lights
6 of the last 30 runs died blind, and 5 of those involved a yellow light explosion (most recently 20260930-154458, apes at T4272). Per 5.0 monsters.h the yellow light is speed 15 with AT_EXPL AD_BLND 10d20. The wiki's advice without a blindfold is to kill it from range. The bot offered "Close in on yellow light", so Jev walked into the blast. That approach option is gone now. Throw options still cover it at 2–6 squares, and melee is still offered when it's adjacent, since killing it first stops the explosion.

## 2026-09-30 21:10 — "(no charge)" marks a shop too
Run 20260930-155030 died at T1676 on Dlvl 2, zapped by an angry shopkeeper. Jev ate a rotten jackal corpse inside a shop and was blinded, then swung at the unseen shopkeeper. The blind-in-shop guard never engaged because shop detection only looked for "for sale" in the items seen nearby, and the only record here was "jackal corpse (no charge)". Detection now accepts "no charge" too.

## 2026-09-30 21:20 — death ray from a leprechaun (variance)
Run 155444 died on T3099 at Dlvl 5. A leprechaun picked up a wand of death and zapped it: the first ray whizzed by and the second killed Jev. Monsters zap only when lined up (muse.c m_lined_up), so stepping off the line would help. But a monster with a wand of death is too rare to be worth new code yet. Logged as variance; revisit if it happens again.

## 2026-09-30 21:35 — flee upstairs from much-stronger monsters
Run 155753 (XL 8, Dlvl 9, T8069) stepped off the upstairs and met a jabberwock (difficulty 18). It went 85 → 47 → 33 HP in two turns. The '<' was 2 steps away, but "Run for the upstairs" was offered only below 1/3 HP, so Jev engraved (garbled), meleed, prayed and died. The wiki advises fleeing a jabberwock. In 5.0, `levl_follower` (mondata.c) lets only M2_STALK monsters follow you up the stairs, and the jabberwock isn't a stalker. Now, when a "much stronger" monster (difficulty ≥ XL+5) is near and the upstairs is within 8 steps, flee_up/upstairs are offered and the attack/approach/explore options are dropped.

## 2026-09-30 21:50 — retry armor after a theft
Run 160545 (XL 5, Dlvl 6, T4388) died at AC 10 to a giant bat and a pony, with a studded leather armor in the pack. At T3033 it tried that spare while already wearing body armor. The failure ("already wearing some armor") marked the spare unwearable for the whole game. Wood nymphs then stole the +3 small shield (T3408) and the worn armor (T3504). A failed wear now records the AC at the time, and the item is offered again once AC gets worse.

## 2026-09-30 22:05 — no forced Elbereth wait with an @ approaching
Run 161255 (XL 6, AC 6, Dlvl 6, T7182) spent 684 of its 1936 decisions waiting on Elbereth. At the end it sat on the square while a Woodland-elf walked up from 5 steps to adjacent and hit, together with a wolf and a bat. @-humans/elves and minotaurs ignore Elbereth (monmove.c onscary). The regular wait option already excluded them, but the forced "stay on Elbereth" override only required some other hostile in view. The override now also requires no hostile @ or minotaur within 7 steps, so the fight, retreat and corridor options stay open.

## 2026-09-30 22:20 — Weak: don't force food runs past nearby monsters
Run 162212 (XL 4, Dlvl 6, T4576) was Weak with a rothe and an elf zombie 2 steps away. The Weak rule (only eat, pray or fetch food) kicked in whenever nothing was adjacent. So Jev walked off its Elbereth toward an item twice, lost 35 → 24 HP, then fought a gray ooze and died. The rule now waits until no non-passive hostile is within 3 steps. Weak costs no HP and fainting only starts at nutrition ≤ 0 (eat.c), so a few turns of fighting first is cheaper.

## 2026-09-30 22:35 — burden prompt pickup loop
Run 162720 (XL 6, Dlvl 7) re-picked "2 yellow gems" every turn for 100+ turns. The pickup raised "You have a little trouble lifting 2 yellow gems. Continue? [ynq]" (pickup.c lift_object), which was escaped, so the gems stayed on the floor and were offered again. act_pickup now answers 'n' to that prompt and never offers the item again this game.

## 2026-09-30 22:50 — trust "It's a wall."
Run 163615 (Dlvl 8, T7444) re-tried the same explore step dozens of times in a dark, irregular room. The move answered "It's a wall.", but the remembered map showed '.' there, so the square was never marked blocked. Bumping a wall takes no game time, so the turn counter didn't advance. In 5.0, hack.c test_move prints "It's <a wall/solid stone>." only for IS_ROCK squares when mention_walls is on, so that message now marks the square blocked regardless of the remembered glyph.

## 2026-09-30 23:10 — find the hero with getpos '@'
Run 163841 (Dlvl 8 Minetown, T8716) spent its last ~1000 turns with the wrong idea of where Jev was. With several white @ on the map and the cursor off the hero even after ^R, `find_me` took the @ nearest the old position, which was a Minetown human. Every move then went the wrong way ("It's a wall."), farlook described floor squares as monsters, and a rope golem killed Jev while it was hallucinating. Now, if the position is still ambiguous after the redraw, the bot sends `;@` (getpos.c NHKF_GETPOS_SELF moves the cursor onto the hero), reads the cursor, and escapes. The earlier "It's a wall." loop in run 163615 was probably the same bug.

## 2026-09-30 23:25 — no forced Elbereth wait under missile fire
Run 164839 (XL 5, Dlvl 5, T2350) walked into a dwarf queen (36 → 13 HP) and engraved Elbereth. The forced "stay on Elbereth" rule then made it wait five turns while a bugbear threw orcish daggers at it. Elbereth only scares monsters out of melee (monmove.c onscary / m_move), and throwing, shooting, zapping and breath still reach you. Per the wiki it is not protection against ranged attackers. The forced wait is now skipped if any of the last 3 messages say something throws, shoots, zaps, breathes or spits, which leaves attack, retreat, quaff and pray on the table.

## 2026-09-30 23:40 — nymph-stripped, then blind (logged, no fix)
Run 165106 (XL 6, Dlvl 7, T3840) had its armor stolen by a water nymph at T3195, while it was engraving, and a conical hat stolen at T3601. At AC 10 a raven blinded it, and unseen biters took it from 58 to 0 HP. The existing "leave the level after a theft" rule needs a known downstairs, and none had been found. This is the second nymph-stripped death this evening. Idea for later: when armor is stolen, hunt the nymph (wiki: she teleports nearby, and killing her drops everything), or wear a spare from the stash first.

## 2026-09-30 23:50 — trapdoor to Dlvl 6 at XL 2 (variance)
Run 165317 fell from Dlvl 3 to Dlvl 6 at T1832 (a trapdoor/hole) while still XL 2. It climbed back up to Dlvl 5 as the pace rule intends. There a crowd (hill orc with a wand of fire, giant rat, jackal, gecko, rock mole) caught it at 23 max HP, and the fire bolt finished it. No fix: the ascend-when-too-deep rule did its job, just not fast enough.

## 2026-10-01 00:00 — don't close in while hallucinating and hurt
Run 165457 (XL 7, Dlvl 8, T7654) was hallucinating at 39/73 HP and chose "Close in on nickelpede". The monster was really a mumak (4d12 butt), which took it to 10 HP. It then died praying. While hallucinating, every name and threat estimate shown to Jev is random (wiki: Hallucination), so approach options are now dropped when hallucinating below 80% HP. Monsters can still come to Jev, and adjacent ones can still be fought.

## 2026-10-01 00:15 — never close in on nymphs
Run 170105 (XL 7, Dlvl 6, T6402) was the third nymph-stripped death tonight. Both thefts in it (a +3 small shield at T4335 and an orcish helm at T6326) came right after Jev picked "Close in on mountain nymph". At AC 10 an Elvenqueen and a hill orc killed it. Nymphs steal on contact and teleport away (wiki: deal with them at range or not at all). Nymphs now join unicorns and yellow lights in the "no approach" list: Jev throws at them or lets them come, and still fights one that is adjacent.

## 2026-10-01 00:35 — pray for Fainting just before starvation, not 150 turns after the last prayer
Run 171315 (Dlvl 6, T2527) prayed successfully for low HP at T2209, became Weak at 2235 and Fainting at 2282. The Fainting gate (150 turns since the last prayer) prayed again at T2380, while the timeout was still high. Result: "You feel that Tyr is displeased" (pray.c p_type 0: +rnz(250) timeout, Luck −3, god anger), so no more prayers, and it fainted repeatedly until an orc zombie killed it. Source (eat.c): Fainting begins at nutrition 0 and starvation comes below −(100 + 10·Con), i.e. 100+10·Con turns later. The bot now records when Fainting began and prays once 60 + 10·Con turns have passed (≈40 turns of margin). Otherwise it waits for the normal 500-turn gate, which gives the timeout as long as possible to run down.

## 2026-10-01 00:50 — no swinging while stunned next to a peaceful
Run 171700 (Dlvl 5, T2680) was stunned in Izchak's lighting store, with a small mimic on one side and Izchak on the other. The stun/confusion lockout applied only when no hostile was near, so Jev kept attacking the mimic. In hack.c, a Stunned move or attack always goes through confdir() (Confusion does 1 time in 5), and one swing hit Izchak. He and the watch killed it with a wand of striking. The lockout (wait, pray or quaff only) now also applies whenever a peaceful is adjacent.

## 2026-10-01 01:00 — chameleon as yeti (variance)
Run 171932 (Dlvl 6, T5752): a chameleon turned into a yeti and took Jev from 41 to 14 HP in three turns. Its Elbereth came out garbled. Not yet low enough to pray (14·7 > 65), Jev drank an unknown black potion. It was sleeping, so the chameleon (now a hell hound pup) killed it while frozen. No fix: the unknown-quaff gamble at ~20% HP is still positive on average.

## 2026-10-01 01:10 — no forced Sokoban push while hurt with hostiles in view
Run 172609 (Sokoban, T5149) was resting on Elbereth at 25/64 HP. The hill orc and snake had "turned to flee", so they fell outside `near` and the Sokoban rule forced the next push. That step took Jev off Elbereth: 26 → 14 HP the next turn, then the orc read a scroll of earth and the boulder killed it. The push is no longer forced while any hostile is in view and HP is below 60%.

## 2026-10-01 01:25 — Weak waits for the starvation clock
Run 173208 (T8071, max Dlvl 5) lived on prayer: it prayed for Weak at T1894, 2747 and 3600, and the fourth, at T4451 (851 turns later), drew "Thou art arrogant, mortal" (p_type 0, timeout still > 200 because rnz(350) has a long tail). With the god angry it eventually fainted to death under a hobgoblin. Weak costs nothing by itself, and the new Fainting rule prays about 40 turns before starvation. So the Weak gate goes from 400 to 1000 turns, letting the timeout run as long as possible. The real issue is that this Jev found almost no food in 8000 turns; still open.

## 2026-10-01 01:35 — Woodland-elf group (variance) and plateau note
Run 173342 (XL 8, Dlvl 5, T9272): a Woodland-elf group took Jev from 54 to 7 HP in four turns (elves ignore Elbereth), and it died to a jaguar while gambling on a prayer. No fix. Plateau check: the last 40 runs died on Dlvl 5–9 (median 7), between T1700 and T9300. Most of tonight's fixes removed specific blunders (theft, position mixup, prayer timing). The next big lever is probably food (several runs barely eat) and faster XL gain.

## 2026-10-01 01:50 — cap the pace rest
Turn-share analysis of recent runs: run 173208 spent 91% of its 8000 turns on "Rest and search 20 turns". It was XL 2 on a cleared Dlvl 3, and the pace rule (next level too deep) has no limit once Dlvl+1 ≥ XL+2. Wandering monsters arrive about 1 per 50 turns (5.0 makemon rate on ordinary levels), too slow to level a Valkyrie, while food and prayers ran out. The rest is now capped at 1500 searched turns per level, after which "Take the downstairs anyway" opens up. The ascend option on the deeper level is only an option, not forced, so this shouldn't ping-pong.

## 2026-10-01 02:05 — two death fixes
- **Run 174306** (XL6, Dlvl 7): hallucinating at 21/71, a retreat went diagonally between two walls and didn't move ("You are carrying too much to get through", hack.c test_move, weight > 600). A giant beetle took 17 HP, and the gamble prayer came 207 turns after the last one. The pathfinder already skipped such squeezes; `retreat_dir` now does too.
- **Run 174744** (XL4, Dlvl 5): at 9/49 Jev wrote Elbereth twice beside a Woodland-elf because a rock mole in view made the "all near are @" check false. monmove.c `onscary`: magical scares never work on S_HUMAN. Elbereth is no longer offered while an @ is adjacent.

## 2026-10-01 02:20 — run 174939, variance
XL6, Dlvl 6, AC6: a jaguar (3 attacks) and a killer bee together took 36 → 0 HP in 3 turns, 100 turns after a prayer. No stairs were near and the Elbereth came out garbled. No fix; AC6 at XL6 is weak, so armour is a lever to look at if this repeats.

## 2026-10-01 02:30 — run 175322, variance
XL3 at full 39 HP, walking to a food item on Dlvl 3: it fell asleep mid-walk (most likely an unseen sleeping gas trap, rnd(25) turns) and a hostile kitten bit it to death. No fix.

## 2026-10-01 02:45 — run 175441: shot to death on Elbereth
XL5, Dlvl 6, AC12: Uruk-hai behind an obstacle (no path, so not "near") shot poisoned arrows at Jev for 10 turns while it waited on Elbereth and then rested 15 turns. HP went 33 → 5, and the prayer was 140 turns too early. Wiki and monmove.c agree that Elbereth only stops melee. Now a "throws/shoots/zaps/breathes/spits" message in the last 3 makes every visible hostile within 6 count as near: no rest, no Elbereth wait and no "hold position"; the retreat and choke options take their place. This is the user's corridor point: under fire, move rather than camp.

## 2026-10-01 03:05 — run 180048 and an armour audit
A jaguar (3 attacks) killed an XL4 Jev at AC6 on Dlvl 5, the second jaguar death in a row. Of the last 40 deaths, 13 were still at AC 6, the starting AC. Wear outcomes across those runs show wearing itself works (82 tries, most succeed). The failures were "already wearing" refusals, including a splint mail refused over a worn leather armor. New: a **body-armour swap** option. When a carried suit beats the worn one's base AC (taken from 5.0 objects.h, e.g. plate 7, splint 6, leather 2), Jev takes the old suit off, wears the new one and drops the old. A cursed old suit marks the swap as impossible, and a worn cloak blocks it.

## 2026-10-01 03:20 — run 180354: the polymorph wand loop
Jev starved, fainted and was killed by a gargoyle on Dlvl 3. The gargoyle was Jev's own doing. From T3141 it zapped an unidentified copper wand at molds 379 times. The zap printed nothing, so the passive-monster zap option came back every turn. The wand was polymorph, and one of the molds became a gargoyle (difficulty 8, far above anything Dlvl 3 makes: monst.h caps generation at (depth + XL)/2 = 4). Jev then spent ~1000 turns on Elbereth beside it while its food ran out. Fix: the zap option now allows at most 4 zaps per wand per level, and never offers polymorph, make invisible or speed monster (wiki: all three make a monster worse).

## 2026-10-01 03:35 — run 180910: werewolf pack beside the stairs
XL6, Dlvl 7, AC2: a werewolf summoned wolves ("A wolf suddenly appears next to you!"), and five attackers took 34 → 6 HP in a turn. The up staircase was one step away. Wiki: stairs are the classic escape from a pack. 5.0 mondata.c levl_follower: only M2_STALK monsters follow, and wolves and werewolves lack it. "Run for the upstairs" was only offered at low HP or against "much stronger" monsters; now a pack (3+ near, whose summed levels exceed 2×XL) also triggers it. When it's available, attack, approach and explore options are dropped.

## 2026-10-01 03:50 — run 181112, werejackal swarm at AC10
XL6, Dlvl 7. A mountain nymph stole the banded mail, shield and helm at T6486 (AC 0 → 10). 600 turns later a werejackal's summoned jackals finished Jev, 44 turns after a prayer. Nymph theft is already handled where it can be (no approaching nymphs; throw instead), and these woke up mid-fight with an imp. Logged as variance. If AC-10 deaths keep coming, the next idea is to slow the pace (treat a bare AC as lower XL).

## 2026-10-01 04:10 — run 182404: 10,000 turns in a Minetown closet
Jev died to a wolf at T16506, XL5, Dlvl 7. Two bugs:
1. **Pace ping-pong**: at XL3, Dlvl 4 ran out its 1500-turn rest cap and took "downstairs anyway". Dlvl 5 (XL+2) offered "Head back upstairs", which Jev took, and it bounced 4 ↔ 5 about 25 times in 100 turns. Now the too-deep ascend isn't offered when the level above has already used up its rest cap.
2. **Locked in town**: on Minetown (Dlvl 7) Jev ended up in a closet whose door was locked. A town level never offered kicking, so it searched 685 times (~10,000 turns). 5.0 dokick.c only angers the watch if a peaceful watchman `couldsee` you, and the first broken door draws only "Hey, stop damaging that door!". Kicking is now allowed in town when no peaceful @ is in view, and stops for the level after that warning.

## 2026-10-01 04:25 — run 183028: killer bee swarm
XL7, Dlvl 7, AC-3: nine killer bees, with the upstairs one step away, poisoned Jev to death at 25/72 (logged as "game ended": the tombstone says "Poisoned by", capitalised, which the parser now matches). The pack rule summed monster levels against 2×XL, and nine level-1 bees came to 9 < 14, so no stair escape was offered. Wiki: killer bees come in hives and their poison drains Str or kills outright. Five or more near monsters now count as a pack whatever their level, which offers (and prefers) "Run for the upstairs".

## 2026-10-01 04:45 — run 183512, prayer tail
XL5, Dlvl 5: Jev lived on hunger prayers (T1444, 2585, 3658, all well-pleased). The 4th, at Weak 1110 turns after the 3rd, got "Thou art arrogant" (p_type 0: timeout still over 200) and a lost level. The god was then angry, there was no food, and Jev fainted to death to a giant rat 400 turns later. 5.0 source: success resets the timeout to rnz(350), counting down 1/turn (allmain.c). Simulating rnz gives P(timeout ≤ 200 after 1110 turns) ≈ 95%, so this was the 5% tail. The real problem is relying on prayer for food: corpse eating is already forced when offered (~60% of offers taken). Variance; no change.

## 2026-10-01 05:00 — run 183739: unknown potion in melee
XL7, Dlvl 4, AC1: at 25/90 HP beside a Woodland-elf, with the last prayer 14 turns old, Jev quaffed an unknown potion. It was sleeping, and the elf killed the sleeper. Wiki (Potion): of the unidentified potions a few heal and several disable (sleeping, blindness, hallucination, confusion), and disabling next to a melee attacker is fatal. Unknown potions are now offered with an adjacent hostile only at prayer-level low HP (pray.c critically_low_hp), where nothing better is left. Known healing potions are unaffected.

## 2026-10-01 05:25 — run 184521: Sokoban stair ping-pong
20,758 turns, slimed on Sokoban's first level. A centaur fight wrecked soko3-1 (boulders off-plan, 3 replans, then "no solution, leaving", which sets `soko_done`). The solved first level still offered "Sokoban: climb to the next puzzle level", and that option didn't check `soko_done`. On top, Jev took "Head for the downstairs", and it bounced 1427 + 1283 times across ~13,000 turns. Fix: no `soko_up` once Sokoban is abandoned. The death message "Turned to slime" is now parsed too (it was logged as "game ended").

## 2026-10-01 05:40 — run 190332: Weak inside a gang
XL5, Dlvl 5, AC0: Weak, 950 turns after a prayer, fighting a kobold/hobgoblin/bugbear gang with gnome archers behind. Twice Jev chose "Go eat the fresh corpse" with enemies adjacent (blocked, free hits), and the prayer wasn't offered because Weak waits 1000 turns. pray.c: Weak (`uhs >= WEAK`) is TROUBLE_STARVING, major trouble, fixable when the timeout is ≤ 200. Simulated rnz(350) gives ≈ 92% at 950 turns. Changes: with a hostile adjacent the Weak threshold drops to 500 turns (≈ 88%), and `goto_corpse` is never offered with a hostile adjacent.

## 2026-10-01 05:55 — run 191443, variance
XL6, Dlvl 6: a rope golem grabbed and choked Jev, 46 → 9 HP in 5 turns of trading blows, while "You can't reach the floor" (levitating, so no Elbereth). The gamble prayer at 129 turns after the last one failed ("Thou art arrogant"). No fix.

## 2026-10-01 06:20 — Excalibur (checklist goal #4)
statico's checklist ranks an artifact weapon 4th, after MR, reflection and poison resistance, none of which Jev can reliably get yet. A lawful Valkyrie gets Excalibur almost for free. Per the wiki and fountain.c:413 in 5.0, each dip of a lone, unnamed long sword at XL≥5 has a 1/30 chance; success blesses the sword, makes it rustproof and *clears existing rust*. New `dip` option: XL≥7 (water demons appear on roughly 1 in 41 dips), HP≥90%, no hostiles in view, not in Minetown (guards get angry), at most 90 dips per game. Success is detected by "a hand reaches up".

## 2026-10-01 06:35 — Ranged fire lasted longer than the 3-message window
Run 20260930-191717 died at T7290 on Mines 6, "killed by an orcish arrow". It had 4 HP and was waiting on Elbereth while an Uruk-hai shot poisoned arrows. The ranged-fire guard looked only at the last 3 messages, and a single volley ("shoots 2 arrows", "1st hits", "2nd misses", poison) pushes "shoots" out of that window. The forced Elbereth wait then made "wait" the only option. Fix: record the turn of the latest ranged message, including "<missile> hits/misses you". For 3 turns after it, `shot` holds, and both Elbereth-wait paths respect it. Note: the earlier summary blamed a magic missile; the real cause is in the record file.

## 2026-10-01 07:10 — Altars, sacrifice, darts, BUC-gated cloaks (checklist + user tips)
- **Excalibur dipping dropped** at the user's request. 5.0 nerfed it to 1/30 for non-Knights (fountain.c:413).
- **Mjollnir isn't available to Jev.** It's neutral (artilist.h:111), and `mk_artifact` only considers role artifacts whose alignment matches the altar. A lawful dwarf would get a random lawful gift such as Grayswandir or Sunsword instead.
- **Sacrifice (pray.c `offer_corpse`/`bestow_artifact`):**
  - Corpses must be at most 50 turns old; value = difficulty + 1.
  - On a co-aligned altar, each offering reduces prayer timeout by value×300/24. At timeout 0 there's a 1/(6 + 2·gifts·artifacts) gift chance (XL > 2, Luck ≥ 0); otherwise Luck goes up.
  - Jev records altar alignment from ':' ("altar to X (lawful)"). It carries a fresh corpse it saw die to a lawful altar on the same level, then runs #offer.
  - Never offered: dwarves (own race), pet species, white unicorns, cockatrices (touching one bare-handed stones you).
  - "Feeling of reconciliation" marks prayer as safe. A gift resets the prayer clock, and the artifact is picked up and wielded.
- **BUC testing:** standing on any altar, Jev drops every item with unknown BUC and picks it back up. `!implicit_uncursed` makes "uncursed" always visible.
- **Cloaks and mithril** (including `mantelet`, which the wear regex was missing) are only worn once known uncursed or blessed (user tip).
- **Darts and daggers:** `AUTOPICKUP_EXCEPTION="<(^| )(dart|dagger)( |$)"`. In pickup.c an exception overrides pickup_types, and pickup_thrown brings thrown ones back. Existing throw logic already targets floating eyes and spheres (user tip).

## 2026-10-01 07:25 — Don't start a corpse meal mid-fight
Run 20260930-193441 (T8225, Dlvl 5): Jev killed one Woodland-elf and went to eat a corpse while the rest of the group was hidden in a dark room. The meal rolled "Rotten food! The world spins and goes dark." The elves took Jev from 46 HP to 1, and the gamble prayer failed. In 5.0 eat.c:1953 every corpse has a 1/7 rotten roll and about 1/37 meals cause unconsciousness for up to 10 turns; an elf corpse also takes ~15 turns to eat. Corpse meals (eat_corpse/goto_corpse) are now blocked unless Weak or worse, whenever a hostile is within 6 squares or something hit Jev in the last 5 turns. That may cost fresh corpses after fights, but hunger is still covered by prayer and packed food.

## 2026-10-01 07:40 — Engulfed state is now a flag
Run 20260930-194011 (T5756, Dlvl 6, "killed by a bugbear, while sleeping off a magical draught"). A fog cloud engulfed Jev at T5735. "You are laden with moisture" repeats every turn and pushed "engulfs you" out of the 3-message window the engulf check reads. Jev then chose "Search for hidden passages" inside the cloud for 20 turns ("What are you looking for? The exit?"). It came out at low HP next to a rothe and a bugbear. Engulfment is now a persistent `run['engulfed']` flag:
- Set by: engulfs/swallows you, "The exit?", "laden with moisture", "cloud of steam".
- Cleared by: expelled/regurgitated, killing it, "dissipates", "thin air".
- When one message contains both kinds of event, the last one wins.

## 2026-10-01 07:55 — Never eat a destroyed zombie's corpse
Run 20260930-194550 (T2797, Mines 5) was "Poisoned by a rotted elf corpse". Jev was Weak, and its last prayer was 920 turns ago, under the 1000-turn threshold. That allowed the starving fallback ("eat an unknown-age corpse"), and the corpse was the one left by an elf zombie Jev had just destroyed. Zombie and mummy corpses are created pre-aged and are always tainted. The prayer for FoodPois then failed. Fix: a corpse that appears next to Jev right after "You destroy" is recorded as undead (-10**9), and the Weak fallback never eats it.

## 2026-10-01 08:10 — Leave dead-end levels
Run 20260930-194723 ("killed by a werejackal, while fainted", T11246) never got below Dlvl 4. From T5000 on, Jev sat on one Mines level whose '>' it never found: about 1,300 decisions, mostly "Search for hidden passages". It lived on 7 prayers and finally fainted. The east part of the map was never reached; boulders in narrow passages are the likely blocker.
- **Fix:** when there's no frontier, no usable '>', and searches on the level total 1,000+ turns, Jev is forced to "give up on this level". It climbs '<', forgets the level's memory, and blacklists the '>' it lands on for 3,000 turns, so it explores the level above for another way down.
- **Latent issue noticed:** level memory is keyed by Dlvl only, so Mines N and Dungeons N share memory. 5.0 `#overview` marks "<- You are here" under the branch header (dungeon.c:3586, `interest_mapseen` always includes the current level), so it could key levels by branch. Not done yet; forgetting the dead-end level covers the case that actually happened.

## 2026-10-01 08:20 — Variance: low-HP prayer 748 turns after the last
Run 20260930-195647 (T3866, Dlvl 5, "hallucinogen-distorted kobold lord, while praying"). Jev was hallucinating on a bones level (with "Jev's ghost") and fighting a crowd at 10/50 HP. It prayed 748 turns after its T3118 prayer, a clock correctly carried across the save/restore through prayer.json. The prayer failed. In pray.c, a major-trouble prayer needs timeout < 200; after rnz(350), P(timeout − 748 < 200) ≈ 0.9, so this falls in the ~10% tail. A slightly earlier Elbereth or retreat might have helped, but I don't see a rule change worth making.

## 08:45 — Boxed in by a dug hole
Run 195747 starved at T9952 on Dlvl 5. At T4163 a large kobold dug a hole in the only doorway out of a dead-end stub. The bot answers 'n' to "Really step into that hole?" and never paths through known traps, so Jev was stuck for 5,000 turns, kept alive by prayer until it starved. dead_end needs a reachable '<', and there wasn't one.

In trap.c, hole_destination sends a hole or trap door 1+ levels down in the same dungeon branch, so it is just a way to descend. Refused holes and trap doors are now remembered separately from level teleporters. When there's no frontier and no reachable '>' or '<', Jev walks next to a known hole (orthogonally, since you can't step diagonally into a doorway) and answers 'y'. Level teleporters stay avoided.

## 08:55 — Lost a gamble
Run 200913 died at T2331 on Mines 5. A giant ant and a giant bat cornered Jev, and an Elbereth engraving came out garbled. Jev made the low-HP gamble prayer (100+ turns since the last one) and was killed mid-prayer. The gamble was the right call there; this one is variance.

## 09:05 — Dead-end cascade
Run 201020 fainted from hunger on Dlvl 1 at T7223 and was killed by a werejackal. Dlvl 3's '>' was never found, so `dead_end` sent Jev up after 2,000 turns and marked Dlvl 2's '>' as bad. Dlvl 2 had no other '>', so it counted as a dead end too, and Jev climbed to Dlvl 1. A bad '>' is now skipped only when there's another way down; otherwise Jev goes back down to re-explore the level, whose memory was wiped.

## 09:15 — Shrieker distraction
Run 201420 died at T1402 (XL3, Dlvl 4). A werejackal, an iguana and a jackal were all adjacent, and Jev spent 3 turns hitting a shrieker, which has no attacks. Shrieker attack options are now hidden while anything else hostile is adjacent.

## 09:25 — Werejackal pack again
Run 201512 died at T1847 on Mines 5 (XL4). A werejackal kept summoning jackals, and Jev attacked the werejackal, which was the right target. HP went 45 → 30 → 23 → 22 → dead. '<' was about 9 steps away, outside the 8-step flee range, and jackals are as fast as Jev, so running offered little. No code change; it was variance plus a Str 14 roll.

## 09:40 — Welded to a cursed dagger
Run 201602 was killed by an ogre at T4539 on Dlvl 7 (XL6). Water nymphs stole the +3 small shield (AC 6 → 10) and later the +1 dwarvish spear. The bare-handed wield fallback then took "a cursed orcish dagger" over "an uncursed +0 dagger": both rank as daggers and the cursed one came first. A cursed weapon welds to your hands, and with d3 damage at AC 10 Jev lost to the ogre even after a successful prayer. The wield fallback now skips known-cursed weapons and prefers known uncursed/blessed ones at equal rank.

Still open: Jev wore no armor for 900 turns after losing the shield (nothing to wear was found), and it never used the expensive camera or the two unknown wands in a losing fight.
Unknown wands can now also be zapped at a monster that isn't weaker than Jev once HP is below half, not only at passive monsters. Same limit as before: 4 zaps per wand per level.

## 09:55 — Lycanthropy mid-fight
Run 202106 was killed by a werejackal at T2711. A bite at T2642 left Jev "feverish", meaning lycanthropy. Prayer had never been used, but the lycanthropy cure was held back whenever a hostile was within 2 squares (a wererat death at 18/46 HP once followed curing it mid-fight). Jev waited on Elbereth at 26-31/41 HP beside the werejackal, which ignores Elbereth, and turned into a jackal at T2676. That dropped the +3 shield and the +1 spear, and the werejackal picked them up and killed Jev with them. The cure (pray.c: TROUBLE_LYCANTHROPE is major trouble) is now also allowed mid-fight at 60% HP or more.

## 10:05 — Arrows for floating eyes
Run 202259 was boxed in by a floating eye on Dlvl 4. Its only ranged items were 7 orcish arrows, which the missile list ignored, so "kill the blocker" was the only option. Jev meleed the eye, was paralysed, and starved by T2426. uhitm.c: hand-thrown ammo does rnd(2) damage, which is poor but safe against a passive monster, and pickup_thrown brings the arrows back. Arrows and bolts are now thrown at passive monsters when nothing better is carried, and the melee option is hidden for a floating eye while any throw or zap option exists.

## 10:20 — Reverted the mid-fight lycanthropy cure
Run 202612 was killed by a hobgoblin at T1231. Under the 09:55 rule Jev prayed away its lycanthropy at 24/32 HP with the wererat adjacent. The wererat kept hitting, a hobgoblin joined, and with the prayer spent Jev died at 7/32 HP. That's the same failure the original "not mid-fight" rule came from (T3790), so I reverted it. Turning into a were mid-fight and losing your gear is the lesser risk.

Run 202445 (raven at T4464, while fainted) was a hunger death. Few corpses were available, and the Weak prayer came 848 turns after the last one and failed ("Tyr is displeased"). Hunger is still the top killer: 5 of the last ~12 runs.

## 10:35 — Jabberwock: Elbereth before a much stronger monster arrives
Run 202732 fell through an unseen trap door from Dlvl 7 to Mines 9 at XL6. A jabberwock (difficulty 18) came into view 3 squares away. Jev was offered "Close in on jabberwock" and no Elbereth (that needed HP < 70%), and went 67 → 0 in two turns at T4199. Now, when a much stronger monster that respects Elbereth (not @ or a minotaur) is within 5 squares, Jev gets Elbereth and waiting on it, and loses approach and explore.

Death reasons now come from `nethack/lib/xlogfile` (death, plus the `while` field) when the turn count matches. The screen scrape had reported this run as "orc zombie, while fainted" by reading another game's line in the high-score list.

## 10:45 — Pony, while fainted
Run 203259 (confirmed by the xlogfile) was killed by a pony at T4381 while fainted. Jev was still XL4 at T4300, so the pace cap kept it waiting on Dlvl 6 (Minetown) for ~900 turns, mostly explore/wait/rest. It bought the store's only affordable food, an 11-zorkmid apple, with 27 gold. The Fainting prayer came 946 turns after a good one and drew "Thou art arrogant" (prayer timeout still above 200, about a 6% chance at that gap). No code change. The pattern to watch is slow levelling plus the pace cap turning into hunger.

## 10:55 — Lycanthropy, the slow way
Run 203601 (XL7, Dlvl 6) was killed by a killer bee at T8224. A werejackal infected Jev about 400 turns after a prayer, so the cure had to wait for the timer. Jev spent ~550 of the next 700 turns as a 7-HP jackal (T7529-7811, T7844-8214). The T7895 prayer didn't cure it, and the T8019 one was a 124-turn low-HP gamble. The last prayer restored dwarf form at 31/77, and a killer bee finished it from 14 HP. The only cures are prayer, wolfsbane and holy water. Holy water would need the altar/BUC work to go further (bless water at a co-aligned altar). No change for now.

## 11:05 — Plugged by molds
Run 204125 starved at T5244 (xlogfile: "died of starvation, while fainted") on Dlvl 3 at XL2. A yellow mold and a red mold blocked the two corridors out of the start area, with rats behind them. Molds are avoided squares, but unexplored areas still showed as reachable, so the blocker logic (which needs "nothing left to explore") never fired. Jev looped explore → "monster came into view" → wait → approach for ~4,000 turns: 289 waits, 289 explores, 7 attacks. Now, if no experience has been gained in 500 turns and a reachable mold is around (HP ≥ 60%, no mobile hostile within 3), Jev is made to kill it. Molds can't move or attack; the passive damage is small, and act_kill_blocker stops at half HP.

The xlogfile turn match was widened from 5 to 200 turns: this death's last screen read T5200 against the xlogfile's 5244, so the override hadn't applied.

## 11:15 — Hit an unknown '@' in a shop
Run 204556 was killed by shopkeeper Sarnen at T5361. In her liquor emporium Jev fought a large mimic, then took "Attack unknown '@' (south)": the farlook had failed, and the @ was Sarnen. She got angry and used a wand of striking. Attack options are no longer offered for an unidentified '@'.

## 11:25 — Pace-cap resting is the starvation engine
Run 204704 was killed by a dog at T3853 while fainted, XL5 on Dlvl 6. About 95 of its "rest and search" choices were pace-cap rests ("Dlvl+1 is too deep for your XL, wait here for wandering monsters"): roughly 1,900 of 3,200 turns spent waiting for XP that rarely came. Run 203259 had 47 such rests and run 204125 had 30. Waiting burns 1 nutrition a turn, and early on wandering monsters spawn about once per 70 turns, so it trades food for very little XP. Pace-cap resting is now off once Hungry, and the per-level allowance at XL+1 is cut from 1,500 to 800 searched turns.

## 11:50 — Run 204909: don't back away from weaker monsters
This was Jev's longest run so far: a dwarven Valkyrie that reached XL8 and survived to T13611 on Dlvl 5. It had been at AC 9 since a nymph theft around T8000. Rolling boulders took it from 45 to 27 HP, and then it rested. A rothe arrived, and at 20/74 HP Jev engraved Elbereth (garbled) and retreated twice. A rothe has speed 9 against Jev's 12 and three attacks (1d3/1d3/1d8, monsters.h), so each retreat just gave it another full round, with Jev gaining only one step every four turns. A prayer at 6/74 HP did nothing (the previous prayer was at T12218), and the rothe finished Jev. The wiki says rothes respect Elbereth and are slow. The fix: when everything adjacent is weaker and HP is at least 25%, retreat is no longer offered, so Jev fights.

## 12:05 — Run 205713: hit the owlbear, not the pudding
Jev died on Dlvl 8 at XL ~8, T5320. An owlbear grabbed it ("You are being crushed") while a brown pudding was also adjacent, and Jev attacked the pudding four times. Hitting a brown pudding with an iron weapon splits it (uhitm.c, the PM_BROWN_PUDDING check), so a second pudding appeared, and meanwhile the owlbear took Jev from 53 to 8 HP. It had last prayed 84 turns earlier, so it drank an unknown potion, which was sickness and killed it. Brown and black puddings now join shriekers as targets that are skipped whenever another adjacent hostile is something else.

## 12:15 — Run 210255: hallucinated threat labels
Jev was hallucinating from T3188 and died to a pony at T3336, XL6 on Dlvl 7. Every turn the threat labels came from a random name: an "Archon (much stronger)" got Retreat and Go-through-door options, an "acid blob (much weaker)" got hit. Jev spent turns retreating, climbing stairs and walking off, and lost 60 HP to the pony. Elbereth was correctly not offered: while hallucinating, each character is scrambled with a 1-in-2 chance (engrave.c:1249). `species()` now returns a neutral placeholder name while hallucinating, so there is no threat or speed label to mislead the choice.

## 12:40 — Run 210625: blind and weaponless meant waiting to die
Jev died at XL5 on Dlvl 5, T4631. A yellow light exploded and blinded it, and it had no weapon in hand (the daggers had been thrown; a scimitar sat in the pack). With no wielded weapon, the option list collapses to "Wield a scimitar". The blind filter keeps only pray/elbereth/quaff/attack/eat, so it dropped the wield and put "Wait until you can see" in its place. Jev waited 16 times while an unseen dog bit it from 37 to 0. I reproduced this offline by building the options from the logged screen, and confirmed it. The blind filter now keeps `wield_` options.

## 12:45 — Run 210857: no 50-step stair walk while surrounded
Jev died at XL5 on Dlvl 8, T3746: killed by a Mordor orc while praying. The '<' was 50 steps away, and with two Mordor orcs and a snake adjacent, Jev chose "Head back upstairs" seven times. Each try stopped after one or two steps ("took damage"), and every step gave free hits: 44 HP to 9, then a gamble prayer 146 turns after the previous one. "Head back upstairs" is now only offered with nothing adjacent, or when '<' is within 2 steps. Its "level above already waited out its pace cap" check now uses the new 800-turn cap instead of 1500.

## 12:55 — Run 211251: no door-walking mid-melee
Jev died at XL6 on Dlvl 7, T5245, to a sewer rat. A wererat kept summoning sewer, giant and rabid rats; this was a bones level, and Jev's own ghost was there too. Jev chose "Go through the locked door" three times while surrounded, and every step was free bites. The adjacent-melee filter already dropped explore, search, throw, pickup and fetch; now it drops `door_` too.

## 13:10 — Yellow lights count as dread
Two deaths in a row started with a yellow light. Run 212916 died to a rabid rat at T2307, Dlvl 6: Jev was blinded at T2246 and four unseen rats killed it through a prayer. Run 210625 was the blind-and-weaponless dog death. A yellow light's only attack is AT_EXPL AD_BLND 10d20 (monsters.h), and at speed 15 Jev cannot outrun it. The wiki's answers are a blindfold or killing it at range. Elbereth also holds it off, since the explosion is a melee attack and lights are not @ or minotaurs. Yellow lights within 5 squares now join the `dread` list, so Elbereth is offered, approaches are dropped, and Jev waits on the engraving.

## 13:20 — Run 213120: don't step back from a wand
Jev died at XL6 on Dlvl 6, T4400: "killed by a wand". A hill orc with a wand of striking took Jev from 24 to 5 HP. Its last prayer had been 86 turns earlier. Jev then retreated three times: a step back doesn't stop a zap, and one retreat landed on an Elbereth square, where melee is suppressed, so "retreat" was the only option left. Two changes: retreat is no longer offered while being shot or zapped (`shot`: within 3 turns of a throws/shoots/zaps message), and while being shot, standing on Elbereth no longer suppresses attacks.

## 13:35 — Run 213506: corpse windows from eat.c
Jev fainted at Dlvl 7, T4698, and a gold golem killed it. It made a pile of edible kills from T3055 on (monkeys, giant ants, rothes, hobgoblins, hill orcs) but ate none of them in 1650 turns, and three walks to a corpse ended "no edible corpse there". The windows were inconsistent: a hungry Jev would walk 25 steps to a corpse up to 30 turns old, and on arrival refuse to eat it if it was 40 or more. The source (eat.c:1892) sets rotted = age/(10+rn2(20)), plus 2 if cursed. Tainting needs rotted > 5, which an uncursed corpse can't reach before age 60; rotted > 3 only costs rnd(8) HP. New windows: eat here under age 50; walk to a corpse under age 35 within 15 steps, and 10 steps when not hungry.

## 13:50 — Run 213943: go back for armor shed as a werejackal
Jev died at XL6 on Dlvl 6, T4835: killed by a hill orc pack mid-gamble-prayer. A werejackal bite at T3575 led to two transformations (T3618, T3904), and each one dropped the armor and weapon on the floor (polyself.c break_armor/drop_weapon). AC went 7 → 10, and Jev ended at AC 9 with only gloves. Prayer cured the lycanthropy at T4138, but the dropped pile was never fetched, because `fetch` skips squares Jev has already stood on. The bot now remembers where it transformed and lets `fetch` go back there after returning to dwarven form; the pickup and wear options take it from there.

## 14:00 — Lycanthropy: kill weres at range
The user flagged lycanthropy as a big problem. Across all runs, 44 of 509 caught it (9%). Each infection means a transformation about every 80 turns (allmain.c: 1 in 80, 1 in 60 at night), and every transformation drops armor and weapon (see 13:50). The cure is usually a prayer, which then isn't available for HP or hunger. Of the last 15 infected runs, 5 died still infected. Only an animal-form were's bite infects: 1 in 4 per hit, minus MC (uhitm.c mhitm_ad_were). The wiki's prevention advice is to kill them before they reach melee range. Now, when an animal-form were (name has "were", glyph isn't @) is 2–6 squares away in a straight line and Jev has missiles, the options narrow to throw, zap, Elbereth, pray and quaff. Approaching it is no longer an option.
Not done: cloaks for MC1 still need a known BUC (user rule); holy water and wolfsbane aren't handled.

## 14:10 — Unknown-BUC armor when the risk is small
The user said: in an emergency, wear the armor; think smart. The rule is now about the cost of a cursed item, not a blanket BUC requirement:
- Plain-looking cloaks (dwarvish/hooded, orcish/coarse mantelet, leather, elven/faded pall) are worn even with unknown BUC, as long as no better body armor waits in the pack. Cursed, the cloak only blocks body-armor swaps; worn, it gives MC1 (about 30% of were bites and other special melee negated) plus 1 AC.
- Unknown-appearance cloaks (tattered cape, opera cloak, ornamental cope, piece of cloth) still need a known BUC. One of them can be invisibility, and a cursed one stuck on breaks the bot's hero tracking.
- Mithril with unknown BUC is worn whenever AC is 7 or worse: even cursed at -3, it beats nothing.

## 14:25 — Run 214717: farlook read a stale message
Jev died at XL7 on Dlvl 6 (Minetown-like, with peaceful gnomes), T7343, killed by a Woodland-elf. At T7332 the top line still read "The 2nd elven arrow misses it." The farlook wait loop broke as soon as the top line no longer said "Pick a", which also matches a line that hasn't been redrawn yet, so it read the stale message. The adjacent elves became "unknown '@'", which is never attacked (shopkeeper safety). Jev explored into them twice, 19 → 7 HP, then prayed, which worked, but the elves finished it. Farlook now waits until the top line looks like a farlook answer ("<glyph> <desc>"), shows --More--, or has changed to something other than the prompt.

## 14:40 — Run 214905: pyrolisk gaze vs Elbereth
Killed by a pyrolisk on Dlvl 9 at T7302. Jev's last prayer was 80 turns earlier, and it sat on Elbereth 2–4 squares from the pyrolisk while the fire gaze (2d6, works at any range in line of sight) took it from 16 to 0 HP. Elbereth only stops melee. The wiki says the pyrolisk is slow (speed 6) with weak defenses; 5.0 monsters.h adds a 1d6 bite. Fixes:
- "gaze!" counts as being shot, so the bot no longer camps on Elbereth.
- No new Elbereth when the only threats near are pyrolisks.
- Close in on a pyrolisk even at low HP.

## 14:50 — Run 215901: gamble prayer instead of a fresh Elbereth
Killed by an Uruk-hai in Minetown at T4295, XL5, AC6. Jev's previous prayer was at T4116. It had just engraved Elbereth at 10/54 HP. Because HP was low, the forced filter left only the "gamble" prayer, 176 turns after the last one. Tyr was displeased, and the next hit killed Jev. With pray.c's rnz(350) timeout, the odds were about even. A fresh Elbereth against an orc is better. The gamble is now skipped while standing on Elbereth when HP > 5, nothing is shooting, and no @ or minotaur is within 7 squares.

## 15:00 — Run 220125: rested while a yellow light approached
Killed by a ghoul at T3521 in Minetown, while blind and paralysed. Jev was at full HP, so it chose the 20-turn pace rest with a yellow light 9 squares away. A search is only interrupted when a monster *appears*, and this one was already visible. The light (speed 15) arrived and exploded, blinding Jev, and a ghoul's paralysing claw finished it. Changes:
- A yellow light anywhere in view now counts as dread, which offers Elbereth and drops approach/explore. Before, this only applied within 5 squares.
- No rest option while a yellow light is in view.

## 15:15 — Run 220406: starved on Dlvl 1 with '>' in view
Died of starvation on Dlvl 1 at T12215, XL6. The downstairs showed on the map inside a room whose only door was closed. The door option needed a blank, unexplored square behind the door, but this room was already explored. So no option ever led to '>', and Jev spent about 760 decisions on search_hidden and dead_end. On Dlvl 1, dead_end meant climbing '<' to "Dlvl 0", which would leave the dungeon. Changes:
- If a '>' is on screen but unreachable, any closed door with an unreachable side qualifies. Doors are ranked by distance to the stairs.
- No dead_end option on Dlvl 1.

## 15:30 — Run 221211: gold golem at AC 7, two mummy wrappings unworn
Killed by a gold golem on Dlvl 7 at T7127. Jev had prayed at T7069 because it was Weak with hunger. It then traded blows with the golem (two 2d3 claws) at AC 7, re-engaging after an Elbereth. At 11 HP, an unknown potion turned out to be hallucination. The pack held two mummy wrappings that were never worn: the armor regex had no "wrapping". In 5.0 objects.h, a mummy wrapping is a cloak with AC 0 and MC1. Changes:
- Mummy wrappings are wearable and count as plain cloaks.
- Putting on body armor now takes a worn cloak off first and puts it back on afterwards. Before, a worn cloak permanently blocked body armor.

## 15:50 — Shops: buy armor, price-identify scrolls and potions
User: "i'd buy mithril if you can afford it, also price-ID scrolls and potions and rings"; "a big goal for 5.0.0 is to get the AC as low as possible". Before this, shops sold Jev food only. Changes:
- **shop_look**: with 20+ gold, walk onto unseen '[', '?' and '!' items in a shop to read their price.
- **Price-ID**: shk.c get_cost is base × (4/3 if `o_id % 4 == 0` and unidentified) × the charisma factor, rounded. `price_bases()` inverts that. Each quote narrows `run['prices'][appearance]`. Rings are recorded but not used yet, since Jev has no ring logic.
- **Buying** (when affordable and with no debt):
  - mithril, or any body armor at least 2 AC better than what's worn;
  - a helmet or boots of a fixed appearance for an empty slot. Random-appearance helmets and boots can be opposite alignment or levitation, so they're skipped;
  - scrolls priced at base 20 (identify, unique) or 80 (enchant armor or remove curse);
  - potions priced at base 20 (healing, unique in 5.0 objects.h).
- **Use**: price-identified items get " (priced as …)" added to their inventory text, so the existing 'healing' quaff logic picks them up. New read_ option for identify, remove curse and enchant armor (EA only while wearing armor), never while blind, confused, stunned, hallucinating or in a shop. act_read picks the first entry in identify's menu.
- `test_price_id.py` checks the price inversion.

## 2026-10-01 16:10 — Local-Jev adapter
- `JEV_ENDPOINT` / `JEV_MODEL` (env or .env) point the bot at any server speaking `/v1/systemone`; plain http is fine for localhost. Local endpoints skip the budget check and keep their own ledger (`runs/budget-local.json`).
- The three question texts now live in `bot.QUESTIONS` so tools can reuse them verbatim.
- `scripts/compare_jev.py` replays logged multi-option decisions against the endpoint: latency p50/p90 versus hosted, top-1 action agreement, safest agreement, danger delta and 0.6-trigger agreement. Smoke-tested against a stub server.

## 2026-10-01 16:30 — Floating eye: blindfold first (death 221529)
- Death: starved on Mines 7. A floating eye blocked the only corridor; Jev waited 200 turns, got Hungry, meleed it (`kill_blocker`), was frozen, and starved. A blindfold sat in the pack the whole time.
- Wiki: blind yourself and melee. 5.0 source `uhitm.c` passive AD_PLYS only freezes the hero `if canseemon(mon)`. Telepathy breaks this, so "strange mental acuity" sets `run.telepathic`.
- Fix: `act_kill_blocker` on a blue `e` puts on a non-cursed blindfold or towel, fights until exp changes (up to 12 swings or half HP), then removes it. With a blindfold the option appears at once instead of after 200 turns of waiting.

## 2026-10-01 16:50 — Blind/low-HP: zap known attack wands (death 222641)
- Death: a yellow light exploded next to Jev on Elbereth. In 5.0, a scared monster that can't move away still panic-attacks (monmove.c MMOVE_NOMOVES → panicattk). Jev went blind, and a giant beetle took it from 62 to 8 HP while the Blind filter left only "swing". At 8 HP the low-HP filter left only a gamble prayer, 257 turns after the last one: about 62% by an rnz(350) simulation. It failed.
- Jev had a wand of cold the whole time, but the zap option used the first wand in the pack (an unknown spiked wand).
- Fix: known attack wands (sleep, cold, fire, striking, magic missile, lightning) come first. Zaps survive the Blind filter (except in shops), and known attack-wand zaps survive the low-HP filter when the prayer is a gamble.

## 2026-10-01 17:10 — Several engines side by side; runs tagged with engine + version
- At the user's request, the comparison script is gone. Local models play real games instead.
- `scripts/play.sh NAME PORT [ENDPOINT MODEL]` (re)starts one instance. NAME is the NetHack player name, so each engine has its own save. Non-`Jev` names keep runs.json, prayer clock and local ledger under `runs/NAME/`. Hosted spend stays one shared budget. Death lookup in xlogfile now filters by player name.
- "Use X" means `scripts/play.sh Jev 8770 <endpoint> <model>`, which resumes Jev's saved game on X.
- Each run records `engine` (`jev` or the local model name) and `models`, the version strings the engine reported. A game continued on another engine lists both. Backfilled all 292 past runs (all `jev-1.13.0`). The dashboard runs table has an engine column.

## 2026-10-01 17:30 — Switching to Jeff Gemma; watch shows the engine
- `jev.watch` titles with "<name> plays NetHack on <model>" and labels the stats line with the model. Dollar cost shows only for hosted Jev.
- `ONLY=<name> scripts/serve_local_models.sh` starts a single model and downloads only its checkpoint (disk is about 98% full). The research agent fixed a bash 3.2 empty-array bug and the `hf --exclude` syntax.
- Local engines get a 120 s timeout (cold load; Gemma runs on MPS via PyTorch, since Jeff's MLX path is Qwen-only).
- The models need Metal and write access to ~/dev, which the nono sandbox lacks, so they must be started from a normal terminal.

## 2026-10-01 17:50 — Kev-0.8B is the main engine; label + header timing
- Gemma (PyTorch/MPS) took about 3.6 s per decision; Kev-0.8B (MLX) takes about 230 ms. The main game now runs on Kev: `scripts/play.sh Jev 8770 http://127.0.0.1:8785/v1/systemone jev-latest kev-0.8b`.
- Kev echoes the requested model name (`jev-latest`), so play.sh takes a LABEL (`JEV_LABEL`). The label names the engine in runs.json, the dashboard and watch.
- watch header: "on kev-0.8b 229ms" is the mean latency of the last 10 engine calls.
- First Kev death: a yeti on Dlvl 10 during a prayer, T7919, about 60 decisions after the switch.

## 2026-09-30 18:10 — djev via LunaRoute
djev (the Gemma diffusion Jev) is hosted on LunaRoute: `https://gw.lunaroute.com/v1/systemone`, model `djev`.
- Jev now sends `LUNAROUTE_API_KEY` from .env for that host.
- No budget is tracked because the pricing is unknown.
- Latency is about 250–360 ms per decision, close to Kev-0.8B.
- Switched with `scripts/play.sh Jev 8770 https://gw.lunaroute.com/v1/systemone djev djev`.
- Also added a local OpenJev (DiffusionGemma 26B, MLX) entry to serve_local_models.sh. It is unused: it needs about 16 GB of disk, and port 8080 is taken.
- The Kev run before the switch was killed by a werewolf on T3395.

## 2026-09-30 18:40 — one run record per game across engine switches
- **Bug:** switching engines restarts the server, and the restart opened a new run record. The previous record was still at 0 turns, so it was dropped when runs.json was loaded. djev's game (T1–5547) vanished and its death was credited to kev-4b.
- **Fix:** an unended last record is now kept. When the save is restored, the new record merges into it: same id and run dir, decision counter continued, models list = every engine that played the game.
- **Death, kev-4b (T5557, Dlvl 7):**
  - A bugbear zapped a wand of striking four turns running while Jev meleed it and missed.
  - In 5.0 (muse.c) striking hits if `rnd(20) < 10 + u.uac`, so at AC 9 each zap had a 90% chance.
  - Jev had prayed 7 turns earlier, so prayer wasn't available.
  - Root cause: still AC 9 at T5557.

## 2026-09-30 19:10 — model report; AC 10 deaths: shed gear and unworn mithril
**Report:** "Jev-protocol models for the NetHack bot" (Claude Docs).
- I replayed 200 logged Jev decisions to each engine and compared the chosen action with Jev's:

  | Engine | Same action as Jev |
  |---|---|
  | Jev itself | 95% |
  | kev-4b | 54% |
  | djev | 50% |
  | Jeff-Gemma | 48% |
  | kev-0.8b | 37% |
  | Random pick | 26% |

- kev-4b ranks danger like Jev (r 0.89) but scores it low: at the 0.6 cutoff it raises 13 alarms where Jev raises 42.

**kev-4b deaths:**
- **Rothe, T6437, at AC 10:**
  - At T5650 Jev turned into a wererat and dropped its +3 small shield, helm and spear. Prayer cured it at T5946.
  - The `dropped` marker only fed `fetch`, which looks 15 steps out, so the gear was never picked up again.
  - **Fix:** a `fetch_gear` option with no distance limit, forced when no monster is near.
- **Orc zombie, T5871, at AC 6:**
  - An elven mithril-coat sat in the pack. Mithril with unknown BUC was only worn at AC ≥ 7.
  - **Fix:** wear it whenever no body armor is on. Even a cursed one is AC 5, and it rarely blocks anything better.
- **Sewer rat, T304:** a forced gamble prayer 172 turns after the last one (about 50% odds); the alternatives weren't better.

## 2026-09-30 19:40 — fainted to a giant ant (kev-4b, T2773)
The T2530 prayer at 9/49 HP was real trouble after all: pray.c's critically_low_hp uses divisor 5 at XL 1-5, so 45 ≤ 49 and it healed fully. LOW_HP now carries pray.c's full divisor table (8 at XL 22-29, 9 at 30). The actual death: Weak with no food in the pack, prayer on timeout, and a food item 20 steps away, past fetch's 15-step radius. 'rest' was the only reasonable option, kev-4b took it 9 times until it fainted. Now, while Weak/Fainting, fetch looks for food across the whole visible map, and 'rest' is dropped when there is no food option.

## 2026-09-30 19:55 — fainted beside an Uruk-hai (kev-4b, T3278)
Prayed for HP at T3039 (fine), Hungry 40 turns later with no packed food; the only meal was an imp corpse (10 nutrition), Weak at 3180, Fainting at ~3240, then it closed in on an Uruk-hai and fainted in melee. Fainting with a hostile within 3 now gets the gamble prayer (100+ turns since the last), and approach_* options are dropped while Fainting.

## 2026-09-30 20:10 — the Minetown watch (kev-4b, T6313, Dlvl 8, AC 2, XL 7)
Blind in Minetown, "You feel an unseen monster!" put an 'I' next to Jev and the only option was to swing at it: a peaceful watchman. "Halt! You're under arrest!", two watchmen killed, then the captain. The blind no-swing-unless-hit rule only covered shops; it now covers any town level.

## 2026-09-30 20:30 — giant bat, praying (kev-4b, T4860, Dlvl 4, XL 5)
No single bug. A slow game: XL 5 with 179 exp at T4800, four prayers spent on HP (1756/2677/3710/4607), ~100 turns camped on Elbereth healing beside a sleeping leprechaun. A swarm of weak spawns (fox, manes, giant rat, newt, giant bat) took 31 -> 8 in three turns once it fought off the square; the re-engrave garbled and the 250-turn gamble prayer failed. Left as is; watching whether kev-4b games are generally this slow compared with hosted Jev's.

## 2026-09-30 20:45 — fainted to a snake in the Mines (kev-4b, T3298, Dlvl 8)
Dwarven Valkyrie in the Gnomish Mines: gnomes, dwarves and hobbits are peaceful, so almost no corpses; 7 gold, no shops for food. Prayed for HP at 2796 while Hungry, Weak by 2820 (a bugbear corpse fixed it), Fainting by 3121 and fainting for 177 turns with no prayer offered (325 turns since the last; the bar was 500, and 'starving' waits 230 turns of fainting). A snake killed it mid-faint. Fainting now offers prayer 300 turns after the last one.

## 2026-09-30 21:10 — jaguar (kev-4b, T3976, Dlvl 7)
Camped on Elbereth at 23/54 while a jaguar fled; once it was out of view the camp rule (hostile within 7) let go, and the rest-before-exploring rule only fires below 50% — 27/54 is exactly 50%. Explored two steps into the jaguar in the dark: three attacks a turn, 28 -> 0. Rest-before-exploring now holds to 75% when Jev was hit in the last 50 turns. (It also carried an unworn polished silver shield — maybe reflection — next to its +3 small shield.)
Also: a polished silver shield (always the shield of reflection, objects.h) next to a worn shield is now swapped in (take off, wear, drop the old one; a cursed worn shield marks it unwearable). Checked on that run's T1775 screen: forced 'wear_e'.

## 2026-09-30 21:35 — housecat, blind and Weak (kev-4b, T5933, Dlvl 7)
Weak with no food, a swarm appearing ("suddenly appears close by"), then a yellow light exploded: blind at 22/60 with a housecat biting. Weak prays at 500 turns since the last prayer with a monster adjacent, 1000 otherwise; blind, the housecat was no longer "adjacent", so at 962 turns the prayer was withdrawn and the only option was to wait. Being hit in the last 2 turns now counts as adjacent. (It also wore a cursed -1 helm of opposite alignment; 5.0 attrib.c wipes the alignment record to 0, so prayer still works.)

## 2026-09-30 21:50 — panther in Sokoban (kev-4b, T4119)
No fix. Pushing boulders at 65/65, AC 2, XL 6: a panther (two d6 claws and a d10 bite) took it 65 -> 43 -> 19 -> 9 in three turns. The prayer at 9/65, 764 turns after a good one (both earlier prayers "well-pleased", no luck penalties seen), was the right bet (~90%) and lost to rnz's tail.

## 2026-09-30 22:10 — nymph level, then a wolf (kev-4b, T4895, Dlvl 5)
Dlvl 5 kept making nymphs (wood, water, mountain): five thefts in 1000 turns — +3 small shield, elven mithril-coat, elven shield, orcish helm, daggers — AC 6 -> 10 and an empty pack; seven prayers (three gambles) kept it alive until a wolf and hill orcs finished it. The leave-a-nymph-level rule needs a known downstairs, and this level's was never found. With the downstairs unknown, a nymph level now offers only exploring (and eat/pray) while nothing is near, so it finds the way out.

## 2026-09-30 22:40 — giant ant + werejackal, praying (kev-4b, T4446, Dlvl 6)
Elbereth wore off at 18/47; kev-4b chose 'Close in' on a speed-18 giant ant with a werejackal beside it: 18 -> 6 in three turns, and the prayer 538 turns after the last failed. Approach options now need half HP, not a third (the ant comes to you anyway). XL at T4000 is 4-6 for both kev-4b and hosted Jev (checked runs.json), so kev-4b is not levelling slower; the slow pace is the bot's.

## 2026-10-01 00:00 — ravens, blind (kev-4b, T4164, Dlvl 6)
No fix. Ravens (speed 20, blinding claw) blinded it at 32/79; it swung back at the unseen attackers (the blind rule allows that when hit), two Elbereth tries were interrupted by attacks, 32 -> 7 over 12 turns, and the gamble prayer 300 turns after the last failed.

## 2026-10-01 00:20 — Woodland-elves in the dark Mines (kev-4b, T3567, Dlvl 8)
Elves in a dark Mines level: farlook failed on several, so they were "unknown '@'", which is never attacked (could be a shopkeeper). Worse, a pack beside it offers 'Run for the upstairs' and drops attack/explore options, but explore options are added again later in build_options, so kev-4b explored four times with elves adjacent: 67 -> 0. Two fixes:
- An adjacent unknown '@' can be attacked if Jev was hit last turn, outside towns, with no peaceful '@' in view.
- The "monster adjacent: no exploring" filter now also fires when flee_up/upstairs/retreat are on offer, not just attacks. Replayed T3563: options are now flee_up and retreat.

## 2026-10-01 — Elvenqueen with an unused wand of wishing (kev-4b, T6359)
Nymphs and a monkey stripped Jev to AC 10, and an Elvenqueen killed it. Its pack held an identified wand of wishing it never zapped. At T2871 it had zapped the wand (unidentified) at a red mold, and the "For what do you wish?" prompt got Escape, so that wish was wasted.
- Any zap that brings up the wish prompt now answers it. Wishes, in order: blessed greased +2 GDSM, blessed amulet of life saving, blessed fixed +2 speed boots, blessed fixed +2 gauntlets of power, blessed +2 SDSM.
- An identified wand of wishing with charges left forces a wish. An unworn life-saving amulet gets put on.
- Dragon scale mail ranks first among suits (AC 9).
- Live-tested in a wizard-mode game: the zap brought up the wish prompt and GDSM landed in the pack.

## 2026-10-01 — Uruk-hai archer while waiting on Elbereth (kev-4b, T4338, Dlvl 7)
An Uruk-hai 5 squares away shot arrows at Jev on and off. The "you're being shot" flag only lasts 3 turns after a volley. Between volleys it lapsed, so Jev waited on Elbereth at 16/58 and then 11/58 until a poisoned arrow killed it.
- Jev now remembers who shot it. Being shot stays in effect for 20 turns while that monster is within 8 squares, so Jev won't wait on Elbereth in its line of fire.

## 2026-10-01 — lynx, bare-handed at AC 10 (kev-4b, T4777, Dlvl 5)
A mountain nymph stole Jev's spear at T3216, and later its shield. Jev tried to wield its spare dagger, but the dagger was in the quiver, so NetHack asked "You have that readied. Wield it instead?". Jev didn't answer yes, so the wield failed and the dagger was marked unwieldable. For 1500 turns it fought bare-handed. It closed on a lynx at 43/54 HP and two rounds took it to 7. Its last prayer had been 50 turns earlier.
- act_wield now answers 'y' to "Wield ... instead?" (wield.c ready_weapon).

## 2026-10-01 — wolf pack in Minetown (kev-4b, T4527, Dlvl 7)
Three wolves surrounded Jev at 70/74 HP, AC 2. Jev attacked nine times in a row and went down to 13 HP. Elbereth was on offer every turn, but kev-4b rated it last, and the 'safest' head also picked attack. Danger was 0.42, under the 0.6 override. Jev prayed at 6 HP, 398 turns after its last prayer, and died praying.
- Two or more adjacent hostiles that respect Elbereth (not '@' or minotaurs) at under half HP: options are cut to Elbereth, pray and quaff. Replaying T4524 (34/74) leaves only 'elbereth'.

## 2026-10-01 — Woodland-elf after nymph and monkey thefts (kev-4b, T4896, Dlvl 6)
A monkey took two shields and a key. Then a wood nymph next to Izchak's shop froze Jev and took its spear, scale mail, potion and gems in one go. Jev was left with 5 gold and AC 10 and wandered Minetown hurt. It spent 10 turns bouncing between 'go to the locked door' and 'retreat' with an orc mummy nearby. A Woodland-elf finished it from 24/60 HP; its last prayer was 320 turns earlier. This is the fourth death caused by nymph thefts.
- A hostile nymph within 3 squares, with no '@' near and no missiles flying, forces Elbereth. If Elbereth is already under Jev, it waits on it. Nymphs respect Elbereth, and stealing is a melee attack. Replaying T4491 (the turn before the theft) leaves only 'elbereth'.

## 2026-10-01 — little dog, blind and asleep (kev-4b, T1664, Mines 4) — journal only
A magic trap's flash and roar blinded and deafened Jev at 38/38 HP. Two unseen dogs bit it while it tried Elbereth (interrupted) and attacked. Then it fell asleep and went from 15 HP to dead within one decision. It had never prayed, but at 15/38 HP it wasn't low enough to pray. Bad luck.

## 2026-10-01 — rolling boulder (kev-4b, T692, Dlvl 2) — journal only
Jev had prayed at T606 and was resting at 8/18 HP. Its kitten triggered a rolling boulder trap, and the boulder hit Jev. Bad luck.

## 2026-10-01 — fainted from hunger at Mines 9 (kev-4b, T5348) — journal only
In 2700 turns Jev found one food ration and two edible fresh corpses. Two prayers fixed its hunger (T2636 and T4333), and the third prayer, at T5181, was spent on other trouble. At Mines 9 its pack had no food and only zombies were around, whose corpses are never safe to eat. It went Weak at T5239 and Fainting at T5314, and was too close to its last prayer to pray. A gnome zombie killed it while it fainted.
No code change. The lever would be a branch policy: stop at Minetown until a higher XL, then do the main dungeon and Sokoban, which have more food. Mines deaths so far: wolf at 7, Woodland-elves at 8, this one at 9, and a yeti at 10. But as a dwarf, Jev finds most of the Mines peaceful, so this is a strategy bet, not a fix. Implementation note: `#overview` (5.0 dungeon.c:3586) marks the current level with "<- You are here." under its branch heading, so branch detection is one menu read per new level.

## 2026-10-01 — rothe while fainted (kev-4b, T3180, Dlvl 6)
Two bugs.
1. look_here read the tty "Things that are here" overlay as whole screen lines, so map rows became item names ("|..--  ...  a mummy wrapping"). Jev spent 15 decisions at T2997 'picking up' map rows. look_here now slices each line from the overlay's column and stops at --More--. Checked with a mock screen.
2. Weak, with an unseen attacker one step away. The no-rest food filter only fires when no hostile is within 3, so 'rest' stayed on offer next to 'pray' (859 turns after the last prayer). kev-4b rested, Jev fainted, and a rothe killed it. When Weak or Fainting with 'pray' on offer, 'rest' is now dropped.

## 2026-10-01 — rothe while frozen by a floating eye (kev-4b, T5195, Dlvl 3)
Three floating eyes plugged a corridor. Jev waited 190 turns ('wait_eye') for them to drift off. Then 'kill_blocker' meleed one at 48/48 HP, the eye survived, and its gaze froze Jev. A rothe wandered in and killed it. Jev had no missiles, so no throw option existed and the melee 'last resort' was the only way through.
- With no missiles or arrows and no active hostile in view, a floating eye within 3 squares can now be hit by throwing the wielded dagger, spear or javelin. A thrown weapon can't trigger the passive freeze. Any throw option already removes kill_blocker for eyes. The existing 'bare-handed: wield' and fetch logic recover the weapon. Replaying T5194 shows throw_j and throw_l.

## 2026-10-01 — hobbit, after a nymph took the armor anyway (kev-4b, T1554, Dlvl 5, XL 4)
The new nymph rule worked for 18 turns: Jev sat on Elbereth at 48/48 while two nymphs, an ape and a pony fled from it. Then a hobbit threw an elven dagger. That set `shot`, which switched off the nymph rule. kev-4b attacked a nymph from the square, erasing Elbereth, and the nymph took its armor (AC 6 to 10). A dust vortex then engulfed and blinded it, and the crowd killed it through a prayer.
- The nymph rule now holds while being shot as long as HP is above half. A d5 dagger costs far less than the armor a nymph steals.

## 2026-10-01 — pony + ape on arrival (kev-4b, T3767, Dlvl 5)
Jev stepped down at 41/41 HP into a giant bat, an ape and a pony. Three trades took it to 14 HP, and kev-4b kept swinging with Elbereth on offer. The pack rule didn't fire because only the pony was adjacent at the end, and 14/41 isn't low enough to pray, so it died next turn.
- History entries now record HP. If HP lost over the last two decisions is at least the HP left, with any Elbereth-respecting hostile adjacent, options are cut to Elbereth, pray and quaff. Replaying T3767 (34 to 14) leaves only 'elbereth'.

## 2026-10-01 — beehive on arrival (kev-4b, T2700, Dlvl 5, XL 4)
Jev walked down into a beehive at 37/37 HP: six killer bees adjacent, and it died within one decision. Only attacks were offered. `pack` was true, but the Elbereth offer only looked at HP below 70%, `dread`, `walled`, unseen attackers and blindness.
- `pack` now offers Elbereth, and a pack with three or more adjacent forces it (Elbereth, pray, quaff). Killer bees respect Elbereth. Replaying the arrival screen leaves only 'elbereth'.

## 2026-10-01 — invisible chameleon as a minotaur (kev-4b, T7302, Dlvl 8)
Jev was hallucinating while resting at 57/77 HP. An invisible chameleon took minotaur form and hit it down to 6 in one turn. Jev prayed for the first time this game and died praying. The minotaur part is bad luck, but Jev was also bare-handed for its last 170 turns, and that was my doing. The new 'throw the wielded weapon at a floating eye' option (10580ad) fired at T6013 (at a yellow mold) and at T7132. The second time the spear flew past the eye and landed out of reach.
- The wielded-weapon throw is now a real last resort. It needs 5 or more 'wait_eye' choices in the last 20 decisions, and it only targets floating eyes.

## Wolf pack after garbled Elbereths (T2624, Dlvl 5)
A nymph took Jev's armor (AC 6 → 10) while a wolf was biting. Jev prayed at 8 HP, and the wolves hesitated while it prayed. After that, two dust Elbereths came out garbled, and the bot then stopped offering Elbereth for 5 turns. Jev meleed three wolves, 29 → 0.
The 5.0 source shows that monster hits don't scuff the hero's square. Only a monster's movement wipes dust, and only on the square it stands on (monmove.c:734). The garbling is engrave.c's 1/25 per-letter typo for dust, so each retry has about a 72% chance of working.
Fix: a garbled result no longer blocks the next Elbereth.

## Rothes on Mines 7 (T2767)
Jev was XL 5 on Dlvl 7, too deep, so the forced 'ascend' rule fired. Two rothes were 2 steps away, and walking toward '<' gave them free hits (46 → 37). Elbereth then garbled, and the old garble block took Elbereth off the menu. Jev meleed down to 10 HP and prayed 349 turns after its last prayer, which was too soon, and died.
Fix: 'ascend' is only forced when no active hostile is within 3 steps. The garble fix (d5cea06) covers the rest.

## Killer bees: a goblin's dagger pulled Jev off Elbereth (T2693, Dlvl 5)
Jev waited about 60 turns on Elbereth beside a beehive. It threw once and meleed once, which cost 37 → 8 HP and max HP 37 → 29 from poison, then re-engraved. While it waited, a goblin down the corridor threw an orcish dagger. The shooter memory from 56531d8 marked Jev as "shot" for 20 turns, so 'wait' wasn't offered, and Jev explored off Elbereth into the bees.
Fix: when the shooter is weaker than Jev and a stronger monster is within 3 squares, Jev stays on Elbereth: the bees are a far bigger risk than a goblin's d3 dagger. A replay of T2691 showed only 'explore' before the change and offers 'wait' after it.

## Rope golem + snake on Dlvl 8 at XL 4 (T2908)
A hole dropped Jev from Dlvl 5 to Dlvl 8, and it was still exploring there to find '<'. A rope golem (stronger) and a snake reached it. At 22/43, with Elbereth on offer, kev-4b chose to swing: 22 → 10. The late Elbereth was then interrupted by the fast snake, and that blocks re-engraving for 5 turns. Jev went back to swinging and died.
Fix: when Elbereth is on offer, HP is below 60% and an adjacent hostile is stronger than Jev, Elbereth (or pray/quaff) is forced. A replay of T2907 offered attack or Elbereth before the change and forces Elbereth after it.

## Uruk-hai arrows: reading the screen mid-animation (T3349, Dlvl 5)
After each Uruk-hai volley, every monster in view came back as "unknown", and Jev once attacked thin air where a stale 'G' had been drawn. In 5.0, tty_delay_output sleeps 50 ms per missile frame (termcap.c, flags.nap). The local terminal reader treats 15 ms of silence as "the game is waiting for input", so it parsed the map and sent farlook keys mid-animation. With every name unknown, the shooter-in-view check failed, and Jev was choosing blind under fire. It left Elbereth, threw, then fell 24 → 9 HP, and the last Elbereth was interrupted.
Fix: `!timed_delay` in jev/nethackrc makes animations instant. The Hardfought rc needs the same line when it is pasted there.
