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

## Rothe after a newt's hit blocked Elbereth (T2568, Dlvl 4)
At AC 10 and 20/50, a cornered newt hit Jev on Elbereth. That started the 5-turn "Elbereth isn't protecting you" block. Jev killed the newt, and then a rothe stepped in. Elbereth was still blocked, so Jev meleed 19 → 5, then prayed too soon (712 turns after the last prayer) and died.
Fix: the block is keyed to the monsters that were adjacent when it was set (`e_blockers`). A new arrival gets a fresh Elbereth.

## Killer bees while Weak (T3493, Dlvl 6)
Jev was Weak from hunger with low HP and no food. 'pray' was offered at T3458 onward, 844 turns after the last prayer, so very likely safe. kev-4b kept choosing attack, descend and throw instead. It went down to Dlvl 6 into killer bees and fainted there.
Fix: when Jev is Weak or Fainting, 'pray' is on offer and no eat option exists, 'pray' is forced.

## Giant ant on Dlvl 8 (T5591)
Jev was XL 6, Weak, and had prayed 50 turns earlier, so it couldn't pray again. With Elbereth on offer, kev-4b meleed a speed-18 giant ant from 28 down to 14. The late Elbereth then came out garbled, the retry was interrupted, and Jev died.
Fix: below 40% HP with a non-@ hostile adjacent, Elbereth (or pray/quaff) is forced.
Still open: food. This run reached Weak twice with nothing to eat.

## Werejackal's wand of lightning (T2912, Mines 5): !timed_delay wasn't enough
Monster names came back "unknown" again mid-zap. With timed_delay off, tty_delay_output still sends a "$<50>" pad through tputs when the `null` option is on (the default), and that is still a real delay. I tested it in wizard mode by zapping a wand of lightning and checking whether the screen changed after the reader's quiet period ended. It changed in 3 of 3 trials with only !timed_delay, and in 0 of 3 with !timed_delay,!null.
Fix: `!null` in jev/nethackrc. The Hardfought rc needs it too.
The death itself: a werejackal in @ form ignores Elbereth and zapped lightning twice at AC 10, 24/46.

## Tainted horse corpse (T6692, Dlvl 8)
Jev was Weak and had prayed 219 turns earlier, so 'pray' wasn't offered. The Weak exception let it eat any corpse whose age was known, and this horse was 234 turns old. eat.c makes a corpse tainted when age/(10+rn2(20)) > 5, so at 234 turns that is near-certain. Jev got deadly food poisoning, prayed too soon, was smitten (it lost a level and was slowed), and died.
Fix: the Weak exception now requires age < 60. Below that age, an uncursed corpse can't be tainted.

## Fire ant while Weak, then frozen by a potion (T4193, Dlvl 6)
At 21/54, Weak and standing on a fresh Elbereth, the food filter (which only checks for hostiles within 3) offered only goto_corpse/fetch. A speed-18 fire ant was 5 steps away, and walking toward food took Jev from 21 to 12. Elbereth garbled. A gamble prayer at 4 HP worked but fixed only the hunger (starvation ranks above low HP in fix_worst_trouble). At 4 HP, kev-4b then drank an unknown potion over Elbereth: sleeping, and the ant killed Jev while it was frozen.
Fixes: while on Elbereth below half HP, the Weak food filter looks out to 7 squares, so 'wait' survives. When Elbereth is on offer, unidentified potions are dropped; only known healing stays.

## Woodland-elf after nymph stripping (T6265, Dlvl 7)
An invisible water nymph took the +3 small shield (AC 10), and later a nymph took the daggers. Jev spent its last ~550 turns with no weapon and no armor, kept descending to Dlvl 7, and lost a bare-handed fight to a Woodland-elf and a dog. Prayer worked once (6 → 45), but the elf ignores Elbereth.
Fix: no voluntary descent below Dlvl 4 at AC 9 or worse. The 'anyway' fallback is unchanged.
Still open: repeated theft. The nymph rule can't see an invisible nymph.

## Giant spider while polymorphed (T5835, Dlvl 8)
Jev was polymorphed into a weak form (10 HP) and standing on Elbereth with a giant spider (much stronger) 2 steps off. At full form-HP, 'wait' isn't forced, and kev-4b chose 'approach' toward a giant ant rated stronger. Jev stepped off Elbereth, the spider broke the form, and Jev died at 13/74.
Fix: no 'approach' option toward monsters rated stronger than Jev. Waiting gives Jev the first hit anyway.

### Run 20261001-020036: fire ant while fainting, T5305 (Dlvl 7)
- Jev prayed for low HP at T5169, then went Weak at T5227. With no prayer available, it sat on Elbereth about 60 turns at 25-32/65 HP, Weak and then Fainting, while a weak orc shaman (a fresh corpse) hovered nearby. Its gamble prayer at T5302 came too soon, and Tyr smote it.
- **Fix:** when Weak or Fainting with no prayer offered and HP above 1/3, drop wait and rest so Jev has to fight or forage. The range-7 food exception on Elbereth now applies only while Weak.

### Run 20261001-020734: iguana while fainting, T1898 (Dlvl 3)
- A prayer at T1494 cured wererat lycanthropy. A werejackal bit Jev at T1565, it turned into a jackal and dropped its dagger, and it had no packed food. It searched for a hidden downstair while going Weak and then Fainting. The 300-turn Fainting prayer bet at T1799 (305 turns after the last prayer) lost: "Thou must relearn thy lessons".
- This was mostly the rnz gamble, so no code change. Food supply is still the open problem.

### Run 20261001-020841: rothe, T7388 (Dlvl 9)
- A wood nymph reached Jev, and its dust Elbereth came out garbled. The nymph stripped Jev from AC 2 to 10 (chain mail, shield, boots). A wererat then infected Jev, and at T7379 it turned into a wererat.
- Engraving in rat form used no time. act_elbereth logged that as "the attack interrupted the engraving" and blamed the adjacent rothe. Back in dwarf form, that blocker held Elbereth off for 5 turns, and the rothe took Jev from 30 to 0.
- **Fix:** if nothing got written and the turn didn't advance, the result is "could not engrave in this form", with no interruption and no blocker.
- Still open: nymph theft (garbled Elbereth with the nymph adjacent).

### Run 20261001-021239: werejackal while fainting, T2566 (Dlvl 5)
- Jev prayed for Weak at T1604 and went Weak again at T2454 with no food. The pace gate (Dlvl 5 with XL 4) blocked the stairs, which were 2 steps away, so it searched for about 60 turns until it was Fainting. Its 909-turn prayer then failed ("Thou art arrogant"), and it lost a level.
- A bear trap also held it for a few turns. Searching never frees you; per hack.c, each diagonal move attempt loosens the trap.
- **Fix 1:** when Weak or Fainting with no prayer offered, the pace gate no longer blocks descending, since a new level means fresh corpses.
- **Fix 2:** when caught in a bear trap with nothing adjacent, Jev is offered 'escape_trap', which repeats diagonal moves up to 8 times.

### Run 20261001-021550: elven arrow, T5006 (Dlvl 7)
- A water nymph on Dlvl 7 made five thefts over about 1000 turns: shield, wrapping, spear, shield, scroll. The downstairs was never found, so leave_nymph never fired, and Jev ended at AC 10.
- A werewolf gave Jev lycanthropy. The gamble prayer at T4859 came 192 turns after a good one and was too soon. Per pray.c p_type 0, that means +rnz(250) timeout, Luck -3 and ugangr++, so god_angry was set correctly.
- At T4983 the gamble prayer was offered again: that elif branch never checked god_angry. Tyr cursed Jev's items ("black glow"), and a Woodland-elf's arrows finished it.
- **Fix:** the gamble prayer now requires `not god_angry`.
- Still open: nymph theft on a level with no known downstairs.

### Run 20261001-022116: werejackal while praying, T2936 (Dlvl 3)
- At 17/42 a werejackal and its summoned jackals attacked. Jev's attack from Elbereth erased the engraving, and the fight took it to 7/42. It took the gamble prayer 361 turns after a good one (roughly 70% odds by rnz(350)) and lost.
- This was the dice, so no code change.

### Run 20261001-022240: hobgoblin while fainting, T2801 (Dlvl 5)
- Jev went Weak at T2429 with no food. Blind, with an unseen jackal and gecko biting, it had only 'pray' and 'rest' to choose from, and it rested 12 times (44 -> 21 HP). The prayer it finally made, 532 turns after the last one, got "Tyr is displeased", so the god was unhelpful but not angry. It then fainted repeatedly and died to a hobgoblin.
- **Fix 1:** when blind with an unseen attacker and no attack option, Elbereth replaces rest, since engraving works blind.
- **Fix 2:** when Hungry with nothing near, if any food option exists (eat, a corpse, food to fetch, buy, or shop food), only food options and pray are offered. Food was being passed up for exploring until Jev was Weak; 4 of the last 6 deaths were fainting deaths.

### Run 20261001-022548: starved, T17559 (Dlvl 7 max)
- Jev solved soko4. soko3's push counter reached 167 against a 166-push plan, but the level wasn't solved: '<' was unreachable. With st=None and no reachable ups, soko3 offered only the '>', while soko4 always offered soko_up. Jev ping-ponged between the two levels from about T6000 to T17559. It was Fainting the whole time and starved.
- **Fix:** when a plan is finished on a level other than soko1 and no '<' is reachable, Jev replans from the screen (up to 3 tries) and otherwise sets soko_done. On this screen the replan returns [], so soko_done is set and normal play resumes.

## 20261001-023613: cave spider, fainting, T9027, Dlvl 5
- A nymph on Dlvl 4 triggered `leave_nymph` down into a weak pack on Dlvl 5, where the pack filter left only `upstairs`. That loop ran 14 times.
- Then, polymorphed at 3/3 HP, Jev made a gamble prayer 179 turns after the last one and Tyr was displeased. With no prayer left, it later starved.
- Fixes:
  - A stair hop guard: 4 or more upstairs/flee_up/leave_nymph in the last 6 decisions disables the pack filter and leave_nymph.
  - No gamble prayer while polymorphed (exp shows None). At 0 HP Jev only reverts to its normal form.
- Also seen: the 5.0 hypocrite penalty (attacking from Elbereth, -5 alignment). It happened 4 times this game. Not fixed yet.

## 20261001-024802: human zombie, T3534, Dlvl 6, XL 5
- A water nymph stood still 2 squares away (asleep) from T2613 on. The nymph rule left only "wait on Elbereth", and Jev waited about 850 turns.
- When the nymph finally moved, she stole the +3 shield anyway. Jev went Weak, and its prayer 846 turns after the last one got "displeased" (bad luck in the rnz timeout).
- A yellow light then blinded Jev, and it fainted and died under zombies.
- Fix: if the nymph has not moved for 30 turns, treat her as asleep and drop the nymph lock. Valkyries have intrinsic stealth.

## 20261001-025211: rope golem while "taking off clothes", T5445, Dlvl 7, XL 5, AC 0
- Jev was in Minetown, Hungry, on a 37-step explore. Izchak and a watchman left view just as a rope golem and a wood nymph came into view.
- The walk's "monster came into view" check compares counts, so it never fired. Jev bumped into the golem and was grabbed. Then it prayed for being Weak while the nymph charmed off its armor, and the golem choked it.
- Fix: a walk also stops when a monster glyph not seen at the start of the walk appears within 7 squares.

## 20261001-025953: giant ant while praying, T6466, Dlvl 7, XL 5
- Elbereth wore off with a yellow light adjacent. Jev's melee swing missed, the light exploded and blinded Jev, and an unseen giant ant bit it from 23 HP down to 10.
- The low-HP prayer came 707 turns after the last one and failed: the rnz(350) timeout has a long tail.
- No code change. The yellow-light handling was right (killing it in melee stops the explosion), and the failure was dice.

## 20261001-030736: coyote while fainting, T3843, Dlvl 6
- Hunger forced 4 prayers in 3800 turns. The last two were gambles that angered Tyr and drained levels: XL 5 to 3, max HP 53 to 33.
- Fresh corpses were offered 22 times and eaten only twice. The "always eat corpses" filter ran before the explore and descend options were added, so it never had any effect.
- Fix: run the corpse forcing again after all options are built, whenever no hostile monster is near.

## 20261001-031312: giant ants while fainting, T3625, Dlvl 5 (Mines), XL 5
- The corpse fix helped: 6 of 12 corpse offers were taken. But Jev ate only about 4 corpses from roughly 40 kills.
- Corpse freshness was only recorded within 2 squares of Jev, so kills with thrown daggers never counted.
- Prayers: T2146 (for HP), T2475, T3460 (for HP), then a gamble at T3582 while Fainting. HP prayers keep using up the safety net that hunger needs.
- Fix: corpses from a kill this turn are dated as fresh up to 7 squares away, as long as the monster stood on that square.

## 20261001-031936: fire ant, T3848, Dlvl 5, XL 5, AC 10
- A nymph had stripped Jev down to a spear and a poleaxe.
- At 6/51 HP with nothing in view, the nymph-level filter (downstairs unknown) allowed only explore, door, search and eat, so "rest" was dropped. Jev walked to locked doors, was hit, wrote Elbereth, walked again, and died to a fire ant.
- Fix: the nymph-level filter keeps "rest" below half HP.

## 20261001-032742: pony, T7921, Dlvl 7 (Mines), XL 5, AC 10
- A nymph stripped Jev to AC 10. At 12/63 HP on Elbereth, with 8 monsters near, "wait" wasn't offered.
- The cause: an '@' 5 squares away, too far to be farlooked (probably a peaceful watchman), triggered the rule that "@ ignores Elbereth". With no wait, Jev's only options were walks, and three of them took damage.
- Fixes:
  - The @/minotaur exclusion only applies within 2 squares.
  - On Elbereth below half HP with monsters near, the walk options (explore, door, sell, approach, fetch) are dropped.

## 20261001-034458: raven while praying, T4960, Dlvl 7, XL 6, AC 10
- At T4530, lycanthropy took Jev into were form, which shed its chain mail, shield, helm and spear. A prayer cured it at T4639, but Jev never went back for the gear. It wielded a cursed orcish dagger instead.
- A raven blinded it in melee at AC 10. A gamble prayer 318 turns after the last one failed.
- Fix: messages about gear falling off record where it fell. Back in normal form with nothing near, a forced `recover_gear` walks back there; the pickup and wear options then handle the rest.

## 20261001-035030: giant spider while fainting, T5312, Dlvl 7, XL 6
- Corpse eating now works: 21 of 21 offers were taken. The HP prayer at T5220 worked, but it used up the prayer timeout while Jev was Hungry.
- The run then lost about 16 turns to "nothing got written: the attack interrupted the engraving" from unseen biters. The interrupt block keys on adjacent monster names, which are empty for unseen attackers. Jev went from Weak to Fainting and died.
- Fix: no Elbereth offer after 2 interrupted engravings in the last 4 decisions.

## 20261001-035715: Grey-elf, T7699, Dlvl 9, XL 8, AC -4 (best run of the night)
- Jev was Stressed for the last 1600 turns, carrying a worn +4 crystal plate mail plus a spare banded mail, 2 Uruk-hai shields, 2 iron shoes, 3 cloaks and spare swords. It had half speed and no HP regeneration.
- Drop options only matched HEAVY (boxes, polearms), so nothing was ever offered.
- An owlbear, a giant beetle, a giant ant and a Grey-elf all came adjacent. Jev went 62 to 6 HP, prayed back to 66, then 66 to 0.
- Fix:
  - While Burdened, unworn armor and spare non-dagger weapons are offered as drops. Mithril and pick-axes are kept.
  - While Stressed with nothing near, Jev may only drop, eat, wear or pray.
  - No junk pickups while Burdened.

## Run 20261001-041036: magic missile from a gnome king, while praying (T2972, Dlvl 5, XL 4)
Held a Mines doorway against about 15 monsters (bugbears, hobgoblins and gnomes). A kill left no one adjacent, so `explore_1` was offered and stepped into the room. HP went 22 → 12 → 5, and the prayer failed 600 turns after the last one. Fix: with 3 or more hostiles within 3 squares, drop explore, door, search and goto options. The XL 3 → Dlvl 5 descent came from the 'anyway' fallback after 800+ turns of searching, which works as designed.

## Run 20261001-041408: elven arrow (T5416, Dlvl 7, XL 6)
A Woodland-elf meleed Jev from 30 to 2 HP. The last prayer was only 90 turns old. "Zap the unknown long wand" was offered on every turn, but kev-4b always chose melee. On Elbereth at 3 HP, the elf (an @, which ignores Elbereth) shot it from out of view. Fix: below 1/3 HP with no prayer available, keep only zap, quaff, flee and Elbereth.

## Run 20261001-041957: fire ant (T4491, Dlvl 7, XL 5). No fix
Jev went from 36 to 32 to 15 to 0 in three turns. A fire ant (speed 18) gets about two rounds of bite (2d4) plus fire (2d4) per turn, so up to about 32 damage. The Elbereth forced by the `losing` check was the right call: per the 5.0 source (engrave.c), dust writes 10 characters in one action. The ant still got its round in before the engraving landed. 15 HP is above the 1/7 prayer threshold, so a prayer would not have healed. The root cause is AC 6 on Dlvl 7: Jev never found body armor, only a small shield.

## Run 20261001-042321: fire ant (T5586, Dlvl 6, XL 5)
In the dark Mines, "The fire ant bites!" arrived every turn, but no 'a' ever showed next to Jev. `unseen_attacker` only matched "It bites", so `rest` was the only option. The Elbereth came out garbled, then rest, rest: 33 → 0. A known scroll of teleportation sat unread in the pack. Fixes:
- `unseen_attacker` now also counts a named attack when no hostile glyph is adjacent.
- Below 1/2 HP, with no prayer available and a monster near or unseen, offer the scroll of teleportation. Below 1/3 HP it becomes one of the forced-gamble options.

## Run 20261001-042954: ettin zombie, taking off clothes (T5019, Dlvl 7, XL 5, AC -3)
The nymph rule kept Jev on Elbereth for 116 turns at 51/53 HP, because a mountain nymph hovered within 3 squares. Meanwhile zombies, orcs, a dwarf king and a jaguar gathered and fought each other. Jev then got hit and attacked off Elbereth, and the nymph charmed it into removing its banded mail. Mid-mob, it died from 48 HP. Source check: any attack from Elbereth erases it (mon.c setmangry), throwing included. Fix: after 30 waits in the last 40 decisions, the nymph rule also offers a throw at the nymph (when she is 2+ squares away).

## Run 20261001-043659: fire ant, while praying (T4663, Dlvl 7, XL 6, AC 5)
At T3017 Jev zapped an unknown wand at a monster. It was a wand of wishing, and the wish produced a greased gray dragon scale mail. Jev carried it unworn for 1600 turns, along with the wand (more charges) and an oilskin cloak. Bugs:
- The early `{'wish'}`-only filter dropped `wear_w`. Later code re-added rest and explore, and kev-4b skipped 'wish' about 100 times.
- Fix: the late gear filter now keeps both wish and wear options.
- The oilskin cloak now counts as a plain cloak, wearable without a known BUC.

## Run 20261001-044321: gnome, fainted from lack of food (T5195, Dlvl 7, XL 6). No fix
Jev never carried food. Successful prayers at T2598 and T3613 fed it. The Fainting prayer at T4507 came 894 turns after the last one and still found the timeout above 200: "Tyr is displeased". In pray.c that message is angrygods' mildest case after p_type 0 (too soon), so the god is angry and further prayers would fail. `god_angry` is set correctly. The nearby delicatessen asked 80 to 240 zm per item; Jev had 31. Only a grid bug and a giant rat were killed nearby, so there were no corpses to eat. This is rnz variance, and the real fix is a food supply, which needs more thought.

## Run 20261001-044801: kitten, fainted from lack of food (T3459, Dlvl 5)
The prayer at T2343, 581 turns after the last, came back "Thou art arrogant": angry god, and Jev fainted for 1100 turns. In that time it killed about 5 kobolds, all skipped as NEVER_EAT (poisonous). Second starvation in a row. Source check (eat.c): a poisonous corpse without resistance costs rnd(15) HP and maybe Str. Fix: when Weak or Fainting, with no prayer on offer and HP above 15, kobold corpses become edible (`never_eat()`). The food-supply problem stays open.

## Run 20261001-045014: rothe, while praying (T2445, Dlvl 5 bones, XL 4)
On a bones level, a hobgoblin threw darts and a spear, so `shot` was set. While shot, `on_e` is off, so attacks from Elbereth came back and the Elbereth wait went away. At 13/51 on a fresh Elbereth, with a rothe adjacent, the only option was "attack the rothe". That erased Elbereth: the rothe hit 13 → 8, and the prayer 626 turns after the last one failed. Fixes:
- On Elbereth while shot, attacks are offered only against the shooter.
- The Elbereth wait stays available whenever a non-shooter is adjacent.

## Run 20261001-045201: rope golem (T5699, Dlvl 7, XL 6)
Jev was in a spiked pit, choked by two rope golems. A successful prayer at T5692 restored it to 70 HP, then 70 → 0 in 5 turns. An uncursed wand of fire (rope golems burn) went unused, because the held filter keeps only Elbereth, pray, attack and quaff. Elbereth was refused three times a turn: "You can't reach the floor" from the pit. Fixes:
- The held filter now keeps `zap_` options.
- After "could not engrave", Elbereth isn't offered for 5 turns.

## Run 20261001-045805: rope golem (T3597, Dlvl 7, XL 5)
A rope golem grabbed Jev at 23/59, and "You can't reach the ground" refused each Elbereth. An old garbled engraving still lay on the square, so every refusal was logged as "garbled", 3 times per turn, and the new `no_engrave` never fired. 23 → 5 → 0. Fix: act_elbereth checks for "can't reach the floor/ground" directly. The prayer at T3125 most likely angered Tyr, so none was available.

## Run 20261001-050355: Woodland-elf, praying on T9414 (Dlvl 4)
Took the downstairs at 23/31 HP and arrived next to 3 wolves, a Woodland-elf and a rothe. Jev stood on '<' and zapped the wand of striking three times (23 -> 6 HP), then prayed only 630 turns after the last prayer and died. Fix: when standing on '<' with 3 or more hostiles adjacent and a pack or a much stronger monster present, offer only 'upstairs' or 'pray'. Wolves can't follow, because they lack M2_STALK.

## Run 20261001-051940: garter snake, T4328 (Dlvl 5, Jev's own bones level)
Jev found a small and a large mimic on its own bones level. It spent about 100 turns beside them, re-engraving Elbereth and waiting. Mimics respect Elbereth, but they barely move, so a cornered, scared mimic attacks anyway (monmove.c panicattk). The bones-level crowd (iguana, kobold lord, manes, rothe, giant ant, ghost) gathered. Jev prayed at 9 HP and died 60 turns later. Fix: if every adjacent hostile has speed 3 or less (not a lichen), HP is below 70% and prayer isn't available, the only option is to retreat.

## Run 20261001-052603: fire ant, praying on T3879 (Dlvl 7)
A fire ant kept biting Jev while the map showed it 3 squares away or not at all. Jev searched for 15 turns three times, explored, and walked toward a corridor (the 'choke' option), dropping from 47 to 8 HP. It then prayed 227 turns after its last prayer and died. Fixes:
- A named "The X misses!" now also counts as an unseen attack.
- The corridor option no longer suppresses Elbereth while an unseen attacker is hitting.
- While an unseen attacker is active, explore, search, rest, door, goto and corridor options are dropped.

## Run 20261001-053341: hill orc, praying on T4145 (Sokoban)
An unseen hill orc zapped a wand of lightning, and the flash blinded Jev. 'Rest' was the only option offered between hits, because unseen_attacker() didn't count "You hear a nearby zap" or "The bolt of lightning hits you" as an attack. HP went 52 -> 30 -> 13 -> 7, then Jev prayed 300 turns after its last prayer and died. Fix: those two messages now count as an unseen attacker, so rest, explore and search are dropped. AC 5 with no escape items is still the underlying weakness.

## Run 20261001-054214: soldier ant, T6068 (Dlvl 9, XL 7)
Jev ran out of food rations by T4391. It prayed at 9 HP while Hungry (T5955). Off an altar with Luck 0, pray.c picks action rn1(2,1), so half the time only the worst trouble is fixed: it fixed HP, not hunger. Jev was Weak 85 turns later with no prayer left, so the Weak filter made it forage instead of waiting. It met a soldier ant (47 -> 24 HP in one turn) and then a fire ant. The second prayer fixed only Weak (the worst trouble), leaving 4 HP. No code change: corpse eating works (56 corpses eaten across 5 runs), and food buying is offered when a shop is in view. Packed food just runs out around T3000-4400. Still open: a reliable food supply.

## Run 20261001-054726: red dragon breath, T4125 (Dlvl 4)
A sewer rat gave Jev lycanthropy. Turning into a wererat repeatedly dropped its spear and armor, and a prayer at T3593 came too soon ("displeased"), so the lycanthropy wasn't cured. Jev was at AC 10 with no weapon when it zapped its unknown maple wand at a floating eye 3 squares away, which identification zaps allow for passive targets. The first zap made the eye "disappear" (it was polymorphed into something invisible). The second turned a floating eye into a red dragon, whose fire breath killed Jev. Fix: identification zaps at passive monsters are allowed only when Jev is walled in (3 or fewer reachable squares), the original reason for allowing them. Still open: lycanthropy loses gear.

## Run 20261001-055017: giant ant, praying on T2246 (Dlvl 5, XL 4, AC 6)
Two giant ants (speed 18) attacked Jev in the Mines at 40/40 HP. It went 38 -> 28 -> 19 HP while fighting. The ants hit it while it engraved, which garbles dust engravings (wipe_engr_at on being hit), so the Elbereth came out garbled. Then 19 -> 8, and a prayer 389 turns after the last one failed. No code change: fighting at 70% HP was reasonable, and two fast ants against AC 6 at XL 4 is the underlying problem (low AC, as in earlier runs).

## Run 20261001-055157: rock mole, fainted from hunger, T4008 (Dlvl 6)
Packed food ran out at T2563. Once Hungry, Jev chose "Hold position" 74 turns in a row: it was offered every turn while a mountain nymph 4 steps away never came closer. At Weak it prayed 1062 turns after its last prayer and got "Thou art arrogant", losing a level. The prayer timeout must still have been above 200; rnz(350) has a long tail. Jev fainted and a rock mole killed it. Fix: "Hold position" is no longer offered after 5 consecutive waits that brought nothing adjacent. Starvation is still the top killer.

## Run 20261001-055446: red dragon breath, T1893 (Dlvl 4 bones, XL 3)
This was the bones level of the earlier wand-of-polymorph death, and its red dragon was still there. With the dragon 3 steps away at full HP, Jev was offered only explore and Elbereth (breath ignores Elbereth). flee_up required '<' within 8 steps, and the '<' was about 30 away. Fix: against a "much stronger" monster, flee_up considers any reachable '<' (nearest first). A red dragon has speed 9 to our 12.

## Run 20261001-055607: shopkeeper Asidonhopo's wand of striking, T596 (Dlvl 2, XL 1)
Jev kicked open a locked door with no visible sign. The "Closed for inventory" dust had been wiped away. It was a shop, and the shopkeeper attacked. A search_hidden option was also on offer. Fix: locked-door kicks are dropped while search_hidden is offered and fewer than 200 turns have been searched on the level, as well as when downstairs are known (the existing rule).

## Run 20261001-055639: rothe, fainted from hunger, T3223 (Dlvl 6)
This was the fourth starvation death in the session. The run had many edible kills (jackals, foxes, rats, ponies, goblins, iguanas) but ate only 4 corpses. Jev even stood on a fresh pony corpse while Hungry and wasn't offered it. Root cause: observe() judged a corpse's freshness once, with lv.corpses.setdefault, the first time its '%' was drawn. Usually that happens before "You kill" is parsed into recent, so fresh kills were filed as stale (-10**6) forever. Fix: remember where monsters stood (mon_seen), re-judge a '%' for 2 turns after it first appears, and re-judge again once a monster has stood on that square. test_corpse.py covers this.

## Run 20261001-055859: wolf, T5914 (Sokoban, XL 5, AC 5)
The corpse fix is working: 4+ corpses eaten before T5500, and no hunger trouble this run. A werewolf gave Jev lycanthropy, and the prayer 583 turns after the last one cured it. The werewolf's summoned wolves then took Jev from 35 to 5 HP in Sokoban's corridors (a cornered wolf hit through Elbereth), with prayer already spent. No code change. The underlying problem is still AC: at T5900 Jev wore no body armor and no cloak (only a helm and a small shield).

## Run 20261001-060459: wolf while praying, T4477 (Dlvl 7, XL 5, AC 6, hallucinating)
Jev fell through a trap door into a crowd of monsters and dropped from 58 to 11 HP in about 10 turns. Elbereth came out garbled (Jev was hallucinating). At 11/63, which counts as major trouble under the 5.0 XL-scaled rule, Jev prayed 251 turns after its last prayer and lost the gamble. That gamble was reasonable. No code change. AC is the root problem again: this run and the last one never saw body armor on the floor, so the next lever is buying or looting armor.

## Run 20261001-060705: pony, unconscious from rotten food, T4291 (Dlvl 5)
While Weak, Jev picked up 2 food rations and ate one with a pony adjacent. In 5.0's eat.c, any non-cursed food older than 30 turns rots 1 time in 7, and that includes rations, so they aren't safe. The rotten one knocked Jev out and the pony killed it. Fix: eating from the pack is now blocked while a hostile that isn't passive is adjacent, unless Jev is Fainting. Weak alone doesn't kill, so the fight comes first.

## Run 20261001-061020: elven arrow, T3898 (Dlvl 7, XL 6, AC 10)
At T3453 a wood nymph stole Jev's worn +3 small shield while it rested. Inventory only refreshed every 25 decisions, and rest decisions take 20 turns each, so the inventory still showed the shield as worn for about 250 turns. Jev then reached Dlvl 7 at AC 10, where Woodland-elves (@, which ignore Elbereth) and giant ants killed it. A successful prayer at T3888 only bought 5 turns. Lycanthropy had already cost the orcish helm at T1743. Fix: theft messages ("She stole", "gladly hand over", ...) now force an inventory refresh.

## Run 20261001-061308: soldier ant, T5703 (Dlvl 8, XL 6, AC 1, full HP)
This was the best-geared run so far: orcish chain mail, a helm and a +3 shield. Two soldier ants (speed 18, bite plus sting) came into view, and because Jev was at full HP it was offered only "close in" and attack. It went from 53 to 0 in two turns. Fix: two or more fast hostiles (speed ≥ 15) that aren't weaker than Jev now count as dread. That bans approach and explore and offers Elbereth, which ants respect. A replay of T5702 now offers Elbereth.

## Run 20261001-062152: red dragon's fire, T1845 (Dlvl 4, XL 2, 11/25 HP)
A red dragon (difficulty 20, probably from a bones file or a polymorph trap) turned up on Dlvl 4 while Jev, at XL 2, was resting on Elbereth at 9 HP. Elbereth made the dragon flee, but breath works at range, and Jev was walking to the upstairs when it got breathed on. It had no wand, no escape item and no prayer. That's unwinnable at this point, so no code change.

## Run 20261001-062248: hill orc, T3665 (Dlvl 5, XL 5, AC 10)
Lycanthropy struck twice. The first time (T3167), Jev went back for the gear it shed. The second time (T3397), the prayer at T3432 cured it, but "recover_gear" required no monster in view at all, and a speed-3 rock mole stayed nearby for over 200 turns. Jev fought on at AC 10 with an orcish dagger until hill orcs killed it. Fix: recover_gear is now offered whenever no hostile is adjacent. Other options are only filtered out when nothing is in view.

## Run 20261001-062622: giant spider while Fainting, T2759 (Dlvl 7, XL 5)
Jev's first prayer (T2728, Weak) got "Tyr is displeased", and the dumplog says "You had sinned", so its alignment was negative. The cause: 5.0 uhitm.c skips the "Really attack?" prompt while hallucinating, confused or stunned. Hallucinating around T2305, Jev hit peaceful monsters ("gets angry!"), and 10 gnomes plus a dwarf died this game. Each peaceful attacked costs -1 alignment and each one killed -5. With hunger unfixed, Jev fainted and a giant spider killed it. Fix: while Hallu, Conf or Stun, attack, approach, throw and zap options are dropped unless Jev was hit in the last 2 turns.

## Run 20261001-062840: pony, T8603 (Dlvl 5, XL 6, AC -1)
This run had good gear (splint mail, AC -1) and reached T8600. Jev came down to Dlvl 5 onto '<' in the middle of about 10 monsters: rothes, giant ants, ponies, a floating eye and assorted small fry. Arriving among 3 or more adjacent monsters is supposed to limit the options to upstairs and pray, but a later filter ("badly hurt and Elbereth is on offer: only Elbereth/pray/quaff") then removed 'upstairs'. Jev stepped off '<', went from 67 to 8 HP, prayed back to 67, went down to 23, became Weak, and died. Fix: that filter now keeps 'upstairs'. A replay of T8530 now offers elbereth and upstairs.

## Run 20261001-063709: orc in Orc Town, T4713 (Dlvl 7, XL 6, AC 8)
A wood nymph stole the shield at T1696. Hunger went from Hungry to Fainting within 200 turns of a low-HP prayer, so Jev made two gamble prayers (T4476 and T4653). It ended up in Orc Town at AC 8. Stunned by an orc shaman, Jev swung 6 times and got "You attack thin air" (hack.c confdir: while Stunned every move goes in a random direction), then died at 24 -> 8 -> 0. Fix: while Stunned, Jev drops movement and attack options and gets "Wait out the stun" instead. Pray, quaff and upstairs remain. Random swings could also hit peacefuls without the confirm prompt.

## Run 20261001-064301: werewolf (gamble prayer), T5767 (Dlvl 9, XL 6, AC 3)
Jev reached Dlvl 9 with speed boots. Three of its five prayers went on being Weak (T1859, 3473, 4784): about 85 kills, mostly tiny monsters (newts, lichens, iguanas) that rarely leave corpses or give much nutrition, and 25 corpse meals. After a low-HP prayer at T5640, an orc mummy plus a werewolf in human form (@, which ignores Elbereth) took Jev to 7 HP while it was Weak. The gamble prayer 124 turns after the last one failed. No code change. The open problem is food supply: no rations bought, and gold is too low to buy them.

## Run 20261001-064958: shopkeeper's wand, T972 (Dlvl 2, XL 2)
With no downstairs found, Jev kicked open a locked door. Behind it was a shop closed for inventory, and Kinojevis zapped Jev dead. The check that reads the floor with `:` found nothing, because the dust sign "Closed for inventory" had been wiped. Fix: "You hear the chime of a cash register" now marks the level as town (a shopkeeper lives here), and that blocks door kicking. A locked level now falls back to searching.

## Run 20261001-065037: food poisoning from a rotted rothe corpse, T2090 (Dlvl 5)
The rothe corpse had been lying there since at least T1902. A hobbit stood on it, and that reset the corpse's "first seen" time. Two turns later Jev killed the hobbit within 7 squares, so the old corpse counted as fresh and Jev ate it at T2083 ("Ulch - that meat was tainted"). Then, with prayer ready and FoodPois flagged as fatal, the model chose goto_corpse and rest. Fixes: (1) a monster crossing a known-old '%' no longer resets its age, and test_corpse.py covers this case. (2) When prayer is offered for a fatal condition, it is the only option.

## Run 20261001-065205: hill orc pack (gamble prayer), T2926 (Dlvl 6, XL 5, AC 5)
A hill orc pack took Jev from 59 to 10 HP. Elbereth went back and forth with attacks, and one engraving came out garbled. Jev then made a gamble prayer 380 turns after the last one, and it failed. Jev was carrying an identified wand of digging the whole time, but the bot had no use for it. Fix: below half HP with a hostile adjacent, a 'dig_down' option zaps the wand at '>' and drops Jev a level. It isn't offered in Sokoban or on stairs, altars, thrones or fountains. It survives the low-HP filters, and when the prayer is a gamble it sits beside it. A replay of T2925 offers dig_down and pray.

## 2026-10-01 — Stay on Elbereth while a yellow light is near
Run 20261001-065349 died at T4702 on Dlvl 6. A hill orc killed Jev while it was praying.

- At T4658 Jev engraved Elbereth with a yellow light 4 squares north.
- Next turn the options were wait or explore. Jev explored, "moved right into the yellow light", and the explosion blinded it.
- Blind, Jev fought unseen hill orcs and went from 56 to 4 HP. Four Elbereth attempts were interrupted by attacks, and the final prayer failed.

Fix: when Jev stands on Elbereth and a yellow light is one of the threats, the explore, goto, fetch and pickup options are removed. That leaves waiting on Elbereth (which yellow lights respect), throwing, or attacking.

## 2026-10-01 — Put armor back on while standing on Elbereth
Run 20261001-065614 died to a quasit at T9072 on Dlvl 8.

- A mountain nymph charmed Jev into taking off its elven mithril-coat, then stole its shield.
- The coat stayed in the pack. Wear options are only offered with no hostile in view, and the quasit was always nearby. The stay-on-Elbereth filter also kept only pray, quaff and eat.
- Jev waited about 50 turns on Elbereth at AC 11. The quasit got through anyway, taking it from 22 to 1 HP, and the next prayer came too soon ("Thou art arrogant").

Fix: wearing armor is also offered while Jev stands on Elbereth with no hostile adjacent, and the stay-on-Elbereth filter keeps wear_. A replay of T9017–T9031 now offers ['wait', 'wear_k'].

## 2026-10-01 — Weak with a fresh corpse nearby: go eat it
Run 20261001-070143 died at T7451 on Dlvl 9. A giant spider killed Jev while it had fainted from hunger.

- Jev turned Weak at T7426 with goto_corpse on offer, a fresh corpse 10 steps away.
- Instead it dropped a helm, then prayed 790 turns after its last prayer. Prayer was offered because a vampire bat was adjacent, which lowers the bar to 500 turns. The prayer failed.
- Afterwards it explored and headed for the upstairs past the same corpse option, then fainted.

Fix: when Jev is Weak or Fainting and goto_corpse is offered, the options shrink to goto_corpse plus fight, eat, Elbereth, zap and quaff. Prayer stays only when HP is low or starvation is imminent.

## 2026-10-01 — No 15-turn rest with a monster 4 squares away
Run 20261001-071129 died at T2658 on Dlvl 5. A pony killed Jev while it was praying.

- A pony took Jev from 41 to 14 HP. It backed off, and Jev chose "Rest and search 15 turns" three times while the pony circled 3–4 squares away.
- The pony's square wasn't in the reachable-distance map, so it didn't count as `near`.
- The pony interrupted the search with kicks and bites (18 to 7), and Jev's prayer 207 turns after the last one failed.

Fix: the 15-turn rest also requires no non-passive hostile within 4 squares. Below half HP in that case, Jev is offered a one-turn wait instead. A replay at T2644 now offers ['explore_1', 'explore_2', 'wait'] instead of ['rest'].

## 2026-10-01 — Low-HP explore filter also covers the new one-turn wait
Run 20261001-071408 died at T4177 on Dlvl 4. A werejackal in @ form killed Jev while it was praying.

- Jev was Weak, its last prayer was at T4000, and it was at AC 6 with a +1 spear that kept missing.
- At 16/41 and 14/41 it explored with the werejackal 2 squares away and took a hit each time.
- A potion brought it back to 33 HP, but four melee rounds took it down to 8.

Change: the "hurt, so don't explore" filter now also applies when the new one-turn wait is offered, not only the 15-turn rest. The pony replay (T2644) now offers just ['wait'].

This run's real killer is food again: Weak, no rations, and its prayer already spent. With Weak and no prayer, the wait is still removed by design.

## 2026-10-01 — Altar desecration isn't god anger; no Elbereth on altars
Run 20261001-071653 died to a yeti at T5954 on Dlvl 9.

- At T5298 a quasit was fighting Jev while it stood on Tyr's altar, and Jev engraved Elbereth there. The game answered: "The voice of Tyr booms out: How darest thou desecrate my altar!"
- The bot's anger regex matched "voice of Tyr booms" and set god_angry, so prayer was never offered again.
- Per 5.0 pray.c altar_wrath, desecrating your own altar costs only 1 Wis and 1 alignment, not anger. A cross-aligned altar costs Luck instead.
- 650 turns later Jev was at 7/56 HP, 888 turns after a good prayer, surrounded by a yeti, an orc-captain and a chickatrice. Its only options were to explore off Elbereth. Dead.

Fixes:
- "desecrate my altar" no longer sets god_angry.
- Elbereth is never offered while standing on an altar.

## 2026-10-01 — One-turn waits must use the m prefix (safe_wait)
Run 20261001-072204 died to a gecko at T3299 on Dlvl 6.

- The new "Wait one turn" option sent a plain `s`. With 5.0's safe_wait (do.c cmd_safety_prevention), `s` beside a monster only prints "You already found a monster. Use 'm' prefix…" and takes no time.
- Jev re-chose that no-op wait dozens of times between 15-turn searches while something bit it from 14 HP down to 1.
- The other wait options already used `ms`. The stun wait and the "let it move off" wait had the same bug.

Fix: every one-turn wait now sends `ms`.

## 2026-10-01 — Level-teleported to Dlvl 9 at XL5 (no fix)
Run 20261001-072918 died to a Green-elf at T3810.

- At T3497 a level teleport trap on Dlvl 6 dropped Jev to Dlvl 9 at XL5.
- It never found the '<' in 300 turns, so "ascend" was never offered.
- Its fights there were with hill orcs, ettin and orc zombies, a soldier ant, and finally two Green-elves (they ignore Elbereth). The prayer at T3801 fully healed it, but the Green-elves took 48 HP in 5 turns.

Bad luck rather than a decision bug. The chance of a fix is low: walking around to find '<' is already what explore does.

## 2026-10-01 — Early gamble prayer: keep Elbereth on offer
Run 20261001-073230 died to a jaguar at T7122 on Dlvl 6.

- The jaguar took Jev from 51 to 11/69 in three turns, and one Elbereth came out garbled.
- At 11 HP, LOW_HP cut the options to the gamble prayer alone, only 123 turns after the last prayer. That prayer failed.
- rnz(350) puts that prayer near a coin flip, while a dust Elbereth lands about 72% of the time (1/25 typo per letter).

Fix: when the prayer is a gamble under 200 turns after the last one, Elbereth stays alongside it. A replay at T7122 now offers ['elbereth', 'pray'] instead of ['pray'].

## 2026-10-01 — Desperate hunger: bat and pet corpses are food
Run 20261001-073919 died at T1956 on Dlvl 4. A homunculus killed Jev while it was fainted from hunger.

- Jev had lycanthropy, and its prayer at T1545 had gone on HP 2.
- At T1701–1729 it stood on a 26–54-turn-old giant bat corpse, Hungry and then Weak. Eating was never offered, because NEVER_EAT includes 'bat'.
- It then turned into a jackal (3 HP), fainted, prayed too soon ("Thou art arrogant"), and died fainted.

Per eat.c a bat corpse only stuns, and dog, cat and pony corpses only aggravate. When Jev is "desperate" (Weak or Fainting, no prayer available, HP > 15), these now count as food, like kobolds already did.

## 2026-10-01 — Lycanthropy again: recover gear first at AC 10
Run 20261001-074301 died to a rat pack at T3091 on Dlvl 5, praying at 6/48.

- Jev prayed for hunger at T2935. At T2973 a wererat infected it, and with prayer on cooldown there was no cure.
- At T3046 Jev turned into a rat, its gear fell off, and it dropped the rest because it was overloaded.
- Back in dwarf form at T3087 it had 48 HP and AC 10, with a wererat 2 steps away. "Go back for your dropped armor" was offered, but Jev closed in instead.
- The wererat (@ form, which ignores Elbereth) plus sewer and giant rats took it from 46 to 6 in three turns.

Change: the gear-recovery filter (recover, pray, eat, pickup, wear, wield only) now also applies at AC 9+ when monsters are in view but none adjacent.

## 2026-10-01 — Stay on Elbereth when the only @ is a were
Run 20261001-074653 died to a sewer rat at T1818 on Dlvl 4.

- Jev sat on Elbereth at 24/36 HP. A wererat in @ form arrived, which ignores Elbereth.
- The rule "any @ within 7 means don't force the stay" released Jev, and it stepped off to close in.
- The wererat summoned sewer and rabid rats around it: 25 → 9 → 0 in two turns.

Summoned rats and jackals respect Elbereth, so leaving it is the worst move. Fix: were-@s no longer count in that rule. A replay at T1815 offers ['wait'] instead of ['approach', 'wait'].

## 2026-10-01 — Two foes within 2 at < 60% HP: Elbereth first
Run 20261001-075246 died to Uruk-hai at T4643 on Dlvl 6.

- A prayer at T4631 healed Jev to 66/66. It then closed in on an Uruk-hai pack. Each one is labeled "weaker than you", but they come several at a time with d8 weapons.
- It traded blows from 54 down to 23 with Elbereth on offer and never took it. The engraving then came out garbled, and a "fleeing" Uruk still hit it from 13 to 1.
- The pack rule never fired: the summed level of the visible Uruk-hai (3 each) was under 2×XL.

Change: Elbereth is forced (with pray, quaff, upstairs and dig) when two or more hostiles are within 2 squares and HP is below 60%. Replay screens only ever showed one Uruk at a time, so this exact death isn't verified. The remaining lesson is that after a full-heal prayer, closing in on a pack is a mistake. Not changed.

## Run 20261001-075611: Woodland-elves, T5738, Dlvl 7
Two Woodland-elves (adjacent N and E; @-shaped, so they ignore Elbereth) took Jev from 67 to 16 HP. The last-resort zap filter offered only a wand of magic missile, aimed at a C 5 steps south. The cause: in a losing melee, zap targets skipped anything marked "weaker than you", and that excluded the elves.
**Fix:** adjacent foes now count as zap targets once HP is below half.

## Run 20261001-080017: werejackal, fainted, T6255, max Dlvl 6
Jev prayed for lycanthropy 516 turns after its last prayer and got "Tyr is displeased", so the god was angry and there were no more prayers. It went Weak, then Fainting, with no food. A rock mole (speed 3, edible) kept biting, but the slow-monster rule walked away from it 6 times instead of killing it for food.
**Fix:** that retreat no longer fires while Weak or Fainting. The prayer gamble itself (about 87% safe at 500 turns) is unchanged.

## Run 20261001-080500: gelatinous cube, paralyzed, T9389, Dlvl 8 (XL 8, 92 max HP)
Jev's Elbereth scuffed, so it meleed the adjacent gelatinous cube. The passive paralysis froze it, and the cube plus an elf mummy took it from 67 to 0.
**Fix:** no melee on a gelatinous cube while any other active hostile is within 3 squares. The threat text now says that hitting it paralyzes.

## Run 20261001-081438: homunculus, while praying, T2171, Dlvl 3
Lycanthropy (wererat) shed all of Jev's armor; in dwarf form it was AC 10 and never got back to the gear. A homunculus's sleep bite then took it from 25 to 6 while Jev swung instead of engraving. A gamble prayer 515 turns after the last one failed.
**Fix:** after "put to sleep" in recent messages, below 70% HP, with Elbereth available and no adjacent @, attack options are dropped.

## Run 20261001-081629: wolf, fainted, T5571, Dlvl 7
At T3753 Jev prayed about being Weak from hunger with a wood nymph 3 steps away. During the helpless prayer the nymph stole the elven mithril-coat, the chain mail and every weapon. Jev spent the next 1800 turns at AC 10, bare-handed, mostly waiting on Elbereth while Hungry, and a wolf finished it off while fainting.
**Fix:** no prayer about non-fatal trouble (Weak hunger, not low HP, not Fainting) with a nymph within 7.
**Still open:** the long Elbereth waits burn nutrition.

## Run 20261001-083107: Woodland-elf, while praying, T5576, Dlvl 5 (XL 5)
At full HP (42) Jev meleed a lone Woodland-elf ("about your level") at the Oracle. It missed 6 swings in a row while the elf hit for about 11 a turn: 42 -> 6 in 4 turns. Then came a gamble prayer 161 turns after the last one. The only items left were an unknown potion and scrolls.
**No fix:** the choice was reasonable and the miss streak was variance. The deeper problem is being underleveled (XL 5 at T5576); elves at the Oracle depth keep killing Jev.

## Run 20261001-083440: giant beetle, fainted, T10905 (XL 8, max Dlvl 4)
Jev spent T1326–T9259 on Dlvl 3. The downstairs room was reached only through a hidden corridor, and search_hidden took about 6000 turns to find it. Meanwhile 7 prayers went on hunger, and it finally fainted to death on Dlvl 4. It carried 3 unknown scrolls the whole time.
**Fix:** once a level has 300+ searches and no downstairs, the bot reads unknown scrolls ("labeled") in place of searching. Magic mapping or teleportation can break the deadlock.

## Run 20261001-084546: rothe, T3797, Dlvl 5 (XL 4)
Mobbed by a rothe, 2 garter snakes and 2 sewer rats. Elbereth stopped working (got hit on it), and Jev switched targets between rats and the rothe while the rothe's 3 attacks a turn took it from 26 to 6. Prayer was 98 turns old.
**Fix:** with 3+ attackable neighbors, only the highest-difficulty one is offered as an attack target.

## Run 20261001-084917: hill orc, T4858, Dlvl 4 (XL 5)
A hill orc pack. Jev zapped magic missile, and "The magic missile bounces!" matched the being-shot regex. With `shot` set, the stay-on-Elbereth wait is withheld when nothing is adjacent, so Jev left fresh Elbereths at 7/54 to explore and go to a door, and the orcs finished it.
**Fix:** missile hits/misses/bounces messages within 2 turns of our own throw or zap no longer count as being shot. "throws/shoots/zaps" still do.

## Run 20261001-085317: Mordor orc, T4528, Dlvl 6 (XL 5)
Nymphs in Minetown had stripped Jev down to a knife (AC 10). Beside two Mordor orcs it alternated "engrave Elbereth" and "attack" 4 times (each attack erases it): 17 -> 6. Attacks were offered on Elbereth because `shot` was set by "The knife misses it. You are hit."
**Fix:** right after a successful engrave, attack options are dropped unless an @ or minotaur is adjacent.

## 2026-10-01: three engines in parallel
- LunaRoute serves two Jev-protocol (systemone) models, kev-4b and djev; everything else there is a chat model. Running:
  - `Jev` on 8770: kev-4b (`scripts/play.sh Jev 8770 https://gw.lunaroute.com/v1/systemone kev-4b kev-4b`)
  - `Hosted` on 8771: hosted Jev (`scripts/play.sh Hosted 8771`), spending the shared $25 budget
  - `Djev` on 8772: djev (`scripts/play.sh Djev 8772 https://gw.lunaroute.com/v1/systemone djev djev`)
- Each instance keeps its own save and `runs/NAME/runs.json` (Jev's is `runs/`). Stats come from the `engine` field across those files.
- `python -m jev.watch` now watches all three: keys 1-3 or Tab switch games, q quits, and the top bar shows each game's turn.
- A code fix now means restarting all three.

### Hosted 20261001-091022: starved on Dlvl 5 (T5819)
Hunger prayers at T2809 and T3923 worked, but the one at T5085, 1162 turns later, angered Tyr ("Thou must relearn thy lessons"). The prayer timeout was reset to rnz(350), which has about a 4% tail above 1360. After that it fainted with no food and died to a rothe. NEVER_EAT still listed 'pony', so it skipped two 250-nutrition pony corpses. eat.c only penalizes dogs and cats, so ponies are now edible.

### Djev 20261001-091023: starved behind floating eyes on Dlvl 3 (T12136)
It had no missiles: the dagger was gone and it wielded a scimitar. It walked to a corridor end, and three hostile floating eyes lined up behind it. Hostile eyes keep approaching, so wait_eye ("let it drift off") searched for about 4000 turns. The 200-turn last resort meleed them, and it was frozen and starved. wait_eye now engraves Elbereth first. monmove.c onscary exempts only humans, uniques, minions, shopkeepers and blind or peaceful monsters, so the eyes flee.

### Hosted 20261001-091226: hill orc pack in the Mines, Dlvl 5, XL 4 (T3245)
It had prayed 33 turns earlier, and its Elbereth engravings kept coming out garbled. This is the open Mines-depth question, so no fix.

### Hosted 20261001-091627: starved on Dlvl 6 (T2961) after a failed first prayer
A yellow light blinded it, and while blind it killed two unseen "it"s (T2622, T2650). Its first prayer of the game, at T2707, got "You feel that Tyr is displeased". The timeout should have been 0 by then (it starts at 300 and drops 1 per turn), so luck or alignment was negative. There was no "distant thunder", so it did not kill its pet. The likeliest cause is a peaceful it fought blind: mon.c gives adjalign -1 per hit and -5 per kill, with no message. It is unconfirmed, so no fix. Its last food was a carrot at T2539.

### Hosted 20261001-091842: jaguar in Sokoban, AC 10 (T5123)
A wood nymph that could not teleport in Sokoban stayed near for about 700 turns. At T4820 she charmed it out of its studded leather and +3 shield. Both stayed in the pack, but the bot did not know. The charm message did not mark the inventory stale, so it still showed them "(being worn)". The nymph-nearby rule also allowed only wait or Elbereth, so a wear option could never come up. It spent 300 turns at AC 10, and a jaguar killed it. Fix: "gladly start removing" now marks the inventory stale. On Elbereth with nothing adjacent, wear options survive the nymph filter.

### Djev 20261001-091604: starved and killed by a coyote on Dlvl 7 (T6480)
It made 8 prayers in 3400 turns, several of them low-HP gambles 320 turns apart, and they worked. At T6262 a Weak prayer angered Tyr ("You feel foolish! Farvel level 6"). The bot did not notice: in 5.0 the god's voice can "thunder" (pray.c godvoices), and the anger regex knew only booms and rings out. It prayed again 145 turns later and Tyr was displeased. The regex now also matches thunders, "relearn thy lessons" and "Thou hast angered me". This miss probably also hid the anger in Hosted 091022.

### kev-4b 20261001-090047: cave spider and rat mob in a shop doorway, Dlvl 4 (T7249)
It stood in Ermenak's shop doorway for about 600 turns. search_hidden walked into the shopkeeper ("Pardon me, Ermenak"), and that message set the debt flag. sell_pay then got "You do not owe Ermenak anything", and the cycle repeated 348 times. Rats, cave spiders, an iguana and floating eyes gathered, and it lost 57 HP to chip damage. A failed gamble prayer followed, then death. "Pardon me" no longer means debt. shk.c's "pay before leaving" and "leave without paying" do.

### kev-4b 20261001-093510: fainted and killed by a garter snake on Dlvl 7 (T4246)
A low-HP prayer at T3015 worked. A Weak prayer 1013 turns later angered Tyr. pray.c angers the god both for "too soon" and for bad luck or alignment, so the log cannot tell which happened. That makes three runs today where a prayer about 1000 turns on failed. Fix, from goto_corpse outcomes across ~120 recent runs: many "no edible corpse there" trips ended on giant bat, acid blob, kobold or dog corpses that were never edible, or on a slime mold, tripe, fortune cookie or eggs. Kills of never-eat species are no longer recorded as fresh corpses. An empty corpse trip now picks up non-corpse food there; eggs are skipped (cockatrice risk).

### Djev 20261001-093151: Uruk-hai archers on Dlvl 6 (Minetown), T6959
It had prayed 44 turns earlier. Uruk-hai shot it from 3 squares while it stood on Elbereth, from 21 HP down to 7. It carried two unknown potions, but on Elbereth only known healing is offered (an earlier lesson: sleeping on a working Elbereth). Elbereth does nothing against arrows, so when being shot at LOW_HP the unknown-potion gamble is now offered on Elbereth too.

### Djev 20261001-094012: unconscious from rotten food, killed by a rothe on Dlvl 5 (T3021)
It killed a rothe and ate the fresh corpse at full HP, 46/46. The corpse rolled rotten (eat.c, 1 in 7) and knocked it out, and the rothe's packmate killed it. act_eat_corpse now engraves Elbereth first unless it is Fainting. That costs one turn per meal, and the packmates respect it while it is out.

### Djev 20261001-094239: frozen by a floating eye in Minetown, killed by an iguana (T6695)
Two floating eyes boxed it into a corridor. It stood on 8 rocks with no other missiles. After the 200-turn wait, kill_blocker meleed one eye and was frozen. Rocks now count as missiles against passive monsters (d3 by hand). When an eye is the blocker and rocks lie here, kill_blocker picks them up instead of meleeing.

### kev-4b 20261001-093854: Aleax on Dlvl 9, XL 8 (T10337), the best kev-4b run of the session
A chameleon (seen as a "peaceful displacer beast", then as an arch-lich) cast summon monsters next to it, bringing an Aleax, an owlbear and a tengu. The Aleax is a lawful minion, which onscary exempts from Elbereth. A prayer at 4 HP worked, but the Aleax took 77 HP to 19 in three turns, with the upstairs 47 steps away. Bad luck, no fix.

### Hosted 20261001-092455: Woodland-elf on Dlvl 6 (T20657) after 13,000 turns stuck on Dlvl 2
It prayed as a gamble at 12/82, 377 turns after the last prayer, and the elf killed it mid-prayer. The bigger loss was turns 2,500 to 15,500 on Dlvl 2 with the downstairs unfound. Several floating eyes sat in the corridors to the unexplored east side. There were 307 wait_eye turns, 1230 search_hidden turns, 160 rounds of the "Pardon me, Pakka Pakka" pay loop, and dead_end trips up to Dlvl 1 and back. Most of this is covered by today's fixes: Elbereth before wait_eye, rocks against eyes, and Pardon me no longer meaning debt. The game was resumed under each restart, so it ran a mix of old and new code.

## kev-4b 095357 — invisible rope golem, T5475, Dlvl 6
Zapped an unknown oak wand at a rope golem: "The rope golem vanishes!" (make invisible). It kept zapping it while being choked, then died to the unseen golem at 16/71. Fix: a zap that makes a monster vanish marks that wand text bad for the rest of the run.

## kev-4b 100029 — giant spider, T2036, Dlvl 7 (XL4)
Fell through a hole from Dlvl 5 to Dlvl 7 at XL4. A giant spider (speed 15, 'stronger') closed in, and only 'attack' was offered at 35 HP. It took three swings, 35 -> 11, then the Elbereth engraving was interrupted. Fix: an adjacent or 2-step fast (speed > 12) 'stronger' monster counts as dread, so Elbereth is offered and approach/explore drop.

## Djev 095139 — gargoyle, T14824, Dlvl 9 (XL8)
At 39/90 the model chose melee against an 'about your level' gargoyle twice (39 -> 27 -> 8). Elbereth came out garbled and a too-soon prayer failed. Fix: the threat note for gargoyles now flags their 3-attack damage and says Elbereth works.

## Hosted 095517 — bones dwarf zombie, T8414, Dlvl 8
A bones level: Jev's own dwarf zombie, a wolf and a dog. HP was already low with a prayer 58 turns old, and the bot was hit while on Elbereth. No fix.

## Hosted 100249 — wererat while fainted, T2273, Dlvl 4
It had no food left by T1542, and the slime mold it ate was rotten. Its first prayer, Weak at T1727, got "Tyr is displeased". Prayer timeout was 0 by then (u_init 300, minus 1 per turn), so Luck or alignment had to be below 0. No peaceful kill, mirror, or "Really attack" shows in the logged messages; multi-step explores can hide messages. Cause unknown, no fix.

## Djev 100244 — hill orc while fainted, T3978, Dlvl 4
Not hungry at 16 HP, it ate a hill orc corpse in a room an orc pack was using (corpse-forcing). It was hit mid-meal, 16 -> 9, and made a gamble prayer 146 turns after the last one: "Thou art arrogant", level drained, Tyr angry. With no food left and prayer unusable, it fainted at T3940. Fix: optional corpse meals (Not hungry) are skipped below half HP.

## Hosted 100344 — Izchak, T6005, Dlvl 8 (Minetown)
It kicked in a locked door in Minetown. The ':' check found no sign, and no peaceful @ had been seen, so the level was never marked as a town. "How dare you break my door?" Izchak's wand of striking and a plains centaur took it from 58 to 0. Fix: a peaceful G or h seen while a fountain is on screen marks the level as a town, which means no door kicks. That cue was true on 25 earlier decisions on this level.

## Djev 100655 — bugbear while hallucinating/asleep, T4056, Dlvl 6
It had prayed at T4011 and was fighting a Mordor orc pack at 11-19 HP; several Elbereths came out garbled. It quaffed unknown potions as last resorts: the first was hallucination, a later one put it to sleep, and it died asleep. Unknown potions are a fair gamble with no prayer left, so no fix.

## Djev 101115 — jaguar, T3737, Dlvl 6
At AC 10, 28/53 HP and 50 turns after a prayer, it chose 'approach' toward a fleeing jaguar (speed 15, three attacks, 'about your level'). That stepped it off Elbereth, and the melee took it 28 -> 12 -> 3. Fix: fast (speed > 12) monsters 'about your level' within 2 squares count as dread when HP < 60%, which drops approach/explore.

## kev-4b 100216 — Uruk-hai pack, T6636, Dlvl 5
At T5888 a wood nymph stole the helm and the +3 shield, and the scale mail went too, leaving AC 10. A pack of four Uruk-hai then shot it while it stood on Elbereth ("You are hit", ranged attacks ignore Elbereth). That marked them as Elbereth-blockers, so only melee was offered: 61 -> 8. Note: djev's jaguar death was also at AC 10 after a nymph took its shield. Nymph theft is now a top cause of deaths. No fix yet; candidates are chasing the nymph down, or going back up when stripped (the AC>=9 pace rule exists).

## Hosted 100917 — raven, T6043, Dlvl 6
A raven (speed 20) blinded it during a monkey/giant-ant fight. Blind, its Elbereth engravings kept getting interrupted. A prayer took it back to 51 HP, but unseen biters took that to 5 in 7 turns. No clear fix: it was fighting blind against faster monsters.

## Djev 101423 — rothe, T3712, Dlvl 5
It was resting on Elbereth at 25/53 when the engraving wore away. The choke rule (hp >= 40%) removed the Elbereth option, so it walked toward a corridor and the rothe hit it, 25 -> 18 -> 8, while re-engraving garbled. At 8/53, prayer was just above the 1/7 low-HP line. Fix: choke only suppresses Elbereth at 60% HP or more.

## Hosted 101650 — coyote in a 12-monster swarm, T1499, Dlvl 4
Elbereth held off a crowd (rothe, jackal, cave spider, giant bat, orc zombie, and more) for many turns. Then a giant bat bit for 3. monmove.c: a scared monster with nowhere to flee panic-attacks (MMOVE_NOMOVES + scared). The bot treated that hit as "Elbereth not protecting", marked the crowd as blockers, and went to melee: 41 -> 3. Fix: a hit under 10% of max HP with Elbereth still readable keeps waiting on it.

## Djev 101801 — giant ant while asleep, T6117, Dlvl 4
It zapped an unknown wand at an adjacent kobold lady with a wall close behind her. The wand was sleep, the ray bounced back, and a giant ant killed the sleeping Valkyrie. zap.c buzz(): range rn1(7,7) = 7..13, and rays bounce off walls. Fix: unknown wands and known ray wands are only zapped along a line with 7 or more open squares, so a bounce can't reach us.

## Hosted 101910 — giant bat while fainted, T5749, Dlvl 3
Lycanthropy: the first shift (T4627) dropped the splint mail, shield and spear. A second shift (T4694) dropped nothing, but its "You turn into a were" message overwrote the drop spot, so fetch_gear never went back for the pile. The bot, unarmed and at AC 10, starved for 900 turns near a floating eye on a level with no '>' found. Fix: the drop spot is set only by the real drop messages ("Your armor falls", "You find you must drop", "can no longer hold your").

## Djev 102146 — starvation, T6672, Dlvl 3
It spent 5000 turns on a Dlvl 3 whose way on was past a boulder stuck at a corridor bend, living on prayers until one was too soon. 'dead_end' (go up) was offered 125 times, but search_hidden was offered beside it and won 123 times. The dead_end filter also dropped pickups, so it stood on a copper wand and a scroll without taking either. Fix: search_hidden isn't offered alongside dead_end, and the dead_end filter keeps pickup_ options.

## kev-4b 101507 — ettin zombie + snake, T8917, Dlvl 8
It meleed an ettin zombie and a snake (speed 15) at 56/85. 5.0 knockback ("knocks you backward with a powerful strike") staggered it, and Elbereth garbled once then wore off during a 15-turn rest. It prayed at 12/85, 400 turns after the last prayer: too soon, killed while praying. No fix: the melee from 56 HP was reasonable, and the prayer was a forced gamble.

## Djev 102351 — raven, T5905, Dlvl 7
This is the second raven death. A raven (speed 20) kept blinding it, and every Elbereth attempt was interrupted (5.0 engraving is an occupation). Blind, it fought "It", 49 -> 5, 36 turns after a prayer. No fix yet. If ravens keep killing: fight them in a corridor, or offer the upstairs when blinded by a fast monster.

## kev-4b 102926 — two rothes while stunned, T3736, Dlvl 5
Weak, 886 turns after its last prayer, with only tripe packed. The Weak prayer wait is 1000 turns, so it ate tripe instead. eat.c makes a non-orc vomit 1 in 2 times: "slightly confused", "can't think straight", "incredibly sick", then stunned. Two rothes arrived during that, 38 -> 6, and the gamble prayer failed. Fix: Weak waits only 500 turns to pray when the pack has no food except tripe, and a safe prayer removes eat-tripe options.

## Hosted 102245 — killed by a wand (Uruk-hai's striking), T7138, Mines Dlvl 7 (Minetown)
It was on Elbereth at 34/62 when a killer bee, a jaguar 2 steps off and an Uruk-hai with a wand of striking were in view. Then only explore_* was offered, and explore was blocked by a peaceful watch captain. The striking hits took it 34 -> 18 -> 0. The likely gap: `near` needed dist <= 1 or a reachable square, and a monster's own square isn't reachable, so the jaguar 2 steps away didn't count. With nothing near, Elbereth wasn't offered. Fix: near counts any hostile within 2 squares.

### Djev 20261001-102943 — giant ant + snake, T3303, Dlvl 6 (Minetown)
Two nymphs on Minetown stripped helm, shield, spear, daggers and lamp over ~300 turns; it ate its last ration and starved at AC 10. `leave_nymph` was gated on `dlvl <= xl`, and it was XL 5 on Dlvl 6, so it never left. **Fix:** allow `dlvl <= xl + 1`, the same pace rule used elsewhere.

### Hosted 20261001-103204 — pony while fainting, T19232, Dlvl 3
It spent 17k turns walled in on Dlvl 2, choosing search_hidden over dead_end (the hole) and living on prayers every ~900 turns. The earlier dead_end fix applied after the restart: it jumped, but it was Weak with its prayer 70 turns old. It fainted fighting a pony. No new fix.

### Djev 20261001-103511 — werejackal, T2336, Dlvl 4
It prayed for Weak at T2296, then a human-form werejackal (Elbereth doesn't stop @) hit it 25 -> 14. Then it summoned jackals, and the pack rule removed all attack options. flee_up walked 4 steps with speed-12 attackers adjacent, and it died. **Fix:** skip the pack/strong attack filter when every adjacent monster is weaker and the stairs aren't underfoot.

### Hosted 20261001-103620 — rope golem while praying, T5202, Dlvl 7
It approached a rope golem at 45/64 and got grabbed: it can't engrave or step away while held, and the choking took it to 4 HP. Its last prayer was 369 turns earlier, so the gamble prayer failed. This is the third rope-golem death.

### kev-4b 20261001-103839 — owlbear, T7718, Dlvl 7
A water nymph had already stripped it to bare hands and AC 10. It approached an owlbear, got grabbed, and died 81 -> 0 in five turns. **Fix (both):** rope golems and owlbears join the no-approach list (let them come or throw), with threat text warning about grabs.

### kev-4b 20261001-104107 — fire ants, T4266, Dlvl 7
It was waiting on Elbereth at 27/47 while two fire ants (speed 18) kept fleeing. A hobbit's thrown dagger set `shot`, which removes the Elbereth wait. The weak-shooter override only covered "stronger" monsters within 3, not "about your level". It explored off Elbereth and the ants killed it in one turn. **Fix:** the override now applies when anything not weaker is within 3.

### kev-4b 20261001-104431 — raven, T6860, Dlvl 7
At AC 10 a mob arrived (manes, dingo, little dog, Mordor orc, gold golem, raven) and a raven blinded it. The wererat bite from T6428 then transformed it mid-fight, dropping its shield, helm and spear. The prayer at T6817 fixed low HP, which outranks lycanthropy in pray.c's trouble order, so the lycanthropy stayed. No fix: it needs wolfsbane or holy water, or a prayer while lycanthropy is the worst trouble.

### Djev 20261001-103858 — explosion (gas spore), T9879, Dlvl 3
Yellow lights blinded it three times (T8218, T9615, T9817), and fainting from hunger fell in between. While blind at 15/75 and AC 10 it meleed an "unseen creature" that was a gas spore. No fix: a blind bot can't tell a spore from other invisible attackers, and it couldn't wait out the blindness with attackers adjacent.

### Hosted 20261001-104100 — wolf, T13328, Dlvl 7/8 (XL 8, AC -1)
leave_nymph took it down into a werewolf pack (wolves and a winter wolf), and it fled up. Twenty turns of rest later, leave_nymph sent it back down. It did this three times, 62 -> 28, and died. The 50-turn "fled up, don't go back down" guard filtered only descend/dig_down. **Fix:** it now filters leave_nymph too.

### kev-4b 20261001-110454 — wolf, T9557, Dlvl 10 (XL 8, AC 2)
It stepped off `<` to fight a raven, which blinded it, and a wolf pack arrived unseen. The prayer at T9521 healed it to 88/88, but it fought 3-4 unseen biters down to 1 HP. "Unseen creature" scored difficulty 1 in the pack sum, so `pack` never fired and flee_up was never offered. **Fix:** unseen creatures count as XL in the pack sum.

### Hosted 20261001-110428 — kitten while praying, T5140, Dlvl 5 (Sokoban)
A mob gathered in Sokoban: an Uruk-hai, a kitten, a jackal, a grid bug and a kobold mummy. Two Elbereths came out garbled and others were scuffed, taking it 31 -> 14. Its prayer at T4856 made the 2-HP gamble prayer fail. No fix.

(LunaRoute engines kev-4b and djev were suspended by the user at this point; Hosted Jev continues alone.)

### Hosted 20261001-111326 — Woodland-elf while praying, T5934, Dlvl 7
It waited on Elbereth to 38/55, then leave_nymph took the stairs to Dlvl 7 at XL 5. A Woodland-elf and a Mordor orc took it 38 -> 7 in 2 turns, and its T5421 prayer was too recent. leave_nymph had no HP gate. **Fix:** require 80% HP, the same as normal descending.

### Hosted 20261001-111713 — giant bat, T3549, Dlvl 3 (XL 3)
It had prayed at T3493, then a giant bat (speed 22) and a hostile little dog wore it down on Elbereth. The bat's erratic flight lands hits when Elbereth erodes, and it re-engraved at 5 HP. No fix.

### 2026-10-01 — local engines
LunaRoute is still suspended. The user started local MLX servers: kev-4b on 8784 (warm ~195 ms) and kev-0.8b on 8785 (~47 ms). `Jev` on 8770 now continues on local kev-4b. A new `Kev08` instance on 8772 runs kev-0.8b; it logs to runs/Kev08/ and has its own save.

### 2026-10-01 — Gold and protection (user request)
The user wants gold collected until it buys protection, then kept at 2000–4000 for shopping. Encumbrance should never shed gold, and any temple priest will do.
- **5.0 priest.c:**
  - The prompt reads "suggested: A or B". A = s×q and B = 2×s×q, where s = peak XL × rn1(101,150) (+40 per cheapskate) and q = max(1, gold / 3s).
  - Offering B gives q AC points (one per 2s). Offering 0 means −1 alignment and +1 cheapskate. Offering below A while holding more than 2× the offer counts as cheapskate.
- **`fetch_gold`:** any reachable `$` outside shops, offered while gold < 4000. The old fetch only reached 15 steps, and the last 15 Hosted games peaked at 13–533 gold.
- **`donate`:** shown when a peaceful "priest(ess) of X" is in view, nothing is near, and gold ≥ 500×XL (+4000 once already protected).
  - `act_donate` walks next to the priest, `#chat`s, parses A/B from the prompt, and offers B, or A or all of its gold if it can't afford B.
- Gold was already autopicked and never in the Burdened drop list. The strategy notes now mention protection.

### Hosted 20261001-112300 — watchman's magic missile, T2570, Dlvl 5 (Minetown)
It threw darts at an "unidentified 'G' (blue)" 6 squares away. That was a peaceful gnome lord, so the watch captain and watchmen turned hostile, and a wand of magic missile killed it. **Fix:** no throws or zaps at unidentified monsters on town levels.

(The user stopped the local-model bots; only Hosted runs now.)

## Stashes (user request)
Wiki *Stash*: early on, leave spares **next to** the stairs (not on `>`: items fall down); monsters don't act while you're off-level.
- When Burdened/Stressed with nothing near and a `<` within 40 steps, the drop options become "stash next to the up stairs". The bot walks there, drops the item, and records `run['stashes'][(dlvl,pos)]`.
- Back on that level, not Burdened, with nothing near: if a stashed armor piece fills a slot it's not wearing (a nymph stole it, or a were-change shed it), `stash_fetch` walks back. The pickup/wear options take over from there. Each item is tried only once (no loops).
- Ceiling: recall only fires on the stash's own level; there is no cross-level trip to fetch it.

## Corridor over Elbereth (user request)
User: "still taking on multiple monsters at once. instead of standing on elbereth, attempt to escape to a hallway to fight them one-on-one."
- `choke` ("Fight from a corridor") was offered only when off Elbereth. It's now offered on Elbereth too, the reach is 15 steps (was 8), and while HP ≥ 50% it replaces the Elbereth engrave/wait options.
- Once in a corridor/doorway square (≤2 open neighbours) with 2+ monsters near, Elbereth is no longer offered above 50% HP: fight them one at a time there. Below 50% Elbereth comes back.
- Hosted 112847 (killed by a mumak T8267, Dlvl 8): sat on Elbereth at 82/83 inside a tiny ring shop while 4 soldier ants circled. Then a mumak walked up and hit it to death, 83 -> 67 -> 28 -> dead. There was no reachable corridor (ants adjacent, shopkeeper at the door), so this fix wouldn't have saved it.

## Strategy revisit: wiki x 5.0.0 source (user request)
Re-read the wiki Strategy hub and its subpages (Standard strategy, Why do I keep dying?, Going to die next turn, Valkyrie, Movement tactics, Elbereth, Protection racket, Nutrition, Prayer/Trouble, plus soldier ant, nymph, yellow light, raven, owlbear, rope golem, mumak), and checked fixes5-0-0/5-0-1 against build/NetHack50/src.

5.0 differences that matter here (verified in source):
- mon.c make_corpse: a kill's random drop is deleted if it is food. Corpses are the main food source.
- mklev.c: 2/3 of levels above the Oracle get a chest or large box (5/6 locked), about half with potions of healing; the Mines entry level's box always has food. The bot never opened boxes (they're in HEAVY), so this was the biggest gap.
- monmove.c panicattk: a scared monster with nowhere to go still attacks. Elbereth is not a guarantee. Scaring does **not** erode it in 5.0; fighting, the per-turn random wipe and monsters standing on it do.
- attrib.c: Valkyrie stealth is XL 3, not XL 1; speed is XL 7. The starting weapon is a +1 (dwarvish) spear, not a long sword.
- eat.c: the first Weak -> Fainting always faints; starvation comes sooner (-(100+10 Con)).
- pray.c critically_low_hp: 1/5 at XL 1-5, 1/6 at XL 6-13 (LOW_HP already matched; the strategy text said 1/7).
- priest.c donation (already implemented): pay the larger "suggested" sum.

Changes:
- New `loot` option: standing on a chest or large box with no hostile within 6, `#loot` it. If it's locked, `#force` it with the wielded weapon (lock.c: a spear bashes, and 1 time in 3 the box is destroyed and its potions break), then loot. In the menus: 'o', then 'a'+'A' (all types plus auto-select; 'A' alone is rejected without paranoid_confirm:A), or '.' to select all. Two tries per box.
- STRATEGY text rewritten for 5.0: correct prayer threshold, stealth/speed XLs, Elbereth caveats (who ignores it, panic attacks, erased by any attack from it, ~1 in 4 engrave failure), corridor fighting, heal at half HP, food (no kill drops, corpses, never eat Satiated, avoid kobolds), open boxes.
- Mumak: threat warning (4d12 butt, slow: walk away or Elbereth) and no "close in" option. Hosted 112847 died to one.
- Hosted 113219 (imp T7465, fainted): Hungry for ~6000 of 7465 turns. It prayed for food 4 times, the last only 787 turns after the previous one ("Tyr is displeased"), then fainted with no food and 37 gold. Box food/potions and a fuller food policy are the lever.

Not done (noted): blindfolding against yellow lights/ravens (no blindfold logic yet), mirror vs nymphs, throwing food to tame hostile d/f, kicking gray stones before picking them up.

## Hosted 113735: killed by a grid bug while praying, T15494, max Dlvl 3
- **Blind on a Mines-like level** (the level counted as a town because of the peacefuls). Attacks only stay on offer in town when the last messages show "It hits/bites", and here the attackers had names ("The grid bug bites!", "The rothe bites!"). With them filtered out, "Wait until you can see" won: 55 -> 6 HP, then a gamble prayer. Fix: the pattern also accepts `The <monster> hits/bites/...`.
- **14000 turns on Dlvl 3** with "downstairs not found yet". The east half of the map was blank. The 591 searches were all spread over the explored west rooms, never at the right room's east wall or the dead-end corridor. Fix: `search_spot` subtracts (blank map cells within ±10 columns / ±5 rows) / 12, so walls facing unmapped space win (test_search_spot.py).
- (The XL "dropping" 6 -> 3 in my first look was my analysis regex matching "XL 3" in the new strategy text, not a game event.)

## Hosted 115052 — hill orc while praying, T5005, Dlvl 6 Mines
Choke walk and Elbereth alternated: the walk stopped after 1 step each time on "a monster came into view" (the pack itself), scuffing each fresh Elbereth, 22 -> 10 HP. Fix: the choke walk passes `stop_new=False` (it still stops on damage); below 50% HP with Elbereth offered/engraved, choke is dropped so Jev holds the square.

## Hosted 115737 — killed by a wand (hill orc), T4612, Dlvl 7
A hill orc with a wand of striking zapped Jev 32 -> 12 during a choke walk; Jev engraved Elbereth, the orc "turned to flee" but kept zapping from 2-3 squares off-line, Jev waited and then explored: dead. Elbereth doesn't stop ranged attacks. Fix: like the pyrolisk rule, a *weaker* shooter gets "Close in" even when hurt, and that charge survives the on-Elbereth filter and displaces explore/wait/search.

## Hosted 120033 — wererat, T8786, Dlvl 8
A wererat in @ form stood adjacent while Jev (12/72, prayed 90 turns earlier) was forced to "Stay on Elbereth" 23 times; @ ignores Elbereth, so it hit 12 -> 3 -> 0 even after the bot logged "not protecting you here". The forced-wait block exempted were-@ entirely (T1818: their summons respect Elbereth). Now a were-@ only gets that exemption when not adjacent, and the forced wait is skipped right after an Elbereth hit.

## Hosted 121507 — mumak, T8074, Dlvl 7
Fresh off a successful prayer (81/81), Jev fought an invisible thing, then engraved Elbereth beside a mumak at 64/81. Between 70% and 90% HP on Elbereth, attacks are dropped (attacking erases it) but "Stay on Elbereth" was only offered under 70%, so the only options were explore: Jev stepped off past the mumak, 4d12 butt + bite 64 -> 29, then garbled/interrupted engravings, dead. Now an adjacent monster also offers the wait in that band, and explore/goto/fetch are dropped while one is adjacent.

## Wiki lessons for the last four deaths (retroactive)
Rule from the operator: every death is a lesson: cause, wiki prevention, record, fix the strategy. And: most NetHack games are winnable, so every death was avoidable.
- 115052 hill orc pack: *Hill orc* page says groups are the first crowd-control test: draw them into a corridor so one attacks at a time, "be wary if any of them have scrolls or wands". Fixed via the corridor walk; strategy already says so.
- 115737 wand of striking: *Wand of striking*: force bolt beam, no reflection, only magic resistance stops it. Elbereth (wiki: "melee only") does nothing. Prevention: kill the zapper fast (hill orcs are weak), or get magic resistance. Strategy text now says Elbereth never stops wands/arrows/breath: kill weak shooters.
- 120033 wererat: *Wererat*: "take them out as quickly as possible", pull into a hallway, Elbereth repels only the animal form and its summons. Strategy text now names were-@ as ignoring Elbereth and says to kill wererats quickly.
- 121507 mumak: *Mumak*: the strongest single melee hit outside the Riders, AC 0, but speed 9: use ranged attacks, hit-and-run, or walk away. Strategy text now says never trade blows with it; the wait-on-Elbereth fix keeps Jev from walking past it.

## Hosted 122226 — rothe while blind, T5778, Dlvl 6
**Cause:** at 72/72 HP Jev stood on Elbereth in a crowd (yellow light adjacent, lizard, dust vortex, gray unicorn, nymph, hill orcs); the pack rule forced "Stay on Elbereth" for 10+ turns. The yellow light, scared but boxed in, panic-attacked (5.0 monmove.c) — its attack is the explosion: blind. Three unseen rothes then took 72 -> 0 while every Elbereth was interrupted. Third blind death to a yellow light.
**Wiki (Yellow light):** let it explode only if already blind (blindfold/towel), or carry a unicorn horn; otherwise kill it. **Source:** the explosion is its AT_EXPL attack (mhitu.c); killing it does not explode (mon.c lists it only for corpse-less deaths) — so melee at full HP is safe.
**Fix:** an adjacent yellow light while not blind and not low HP replaces every other option with killing it (pray/quaff kept). Strategy text says the same. Still open: blindfold/towel use when one is in the pack.

## Hosted 123244 — soldier ant + Green-elf, T3107, Dlvl 7 at XL 5
**Cause:** (1) `leave_nymph` took the downstairs Dlvl 6 -> 7 at XL 5 (its gate was dlvl <= XL+1 *before* descending, so it landed at XL+2); (2) a soldier ant (speed 18) and a Green-elf (@: ignores Elbereth) met Jev there; it meleed 43 -> 22 -> 0, prayer only 137 turns old, while an identified **wand of teleportation** picked up 40 turns earlier sat unused (only unknown wands got zap options).
**Wiki:** *Soldier ant*: avoid being surrounded, retreat to stairs/corridors, Elbereth reliably works on them, "have whatever escape items you can, e.g. scrolls of teleportation and wands of teleportation, ready". *Wand of teleportation*: zap yourself to escape when surrounded.
**Fix:** leave_nymph now only descends when dlvl < XL (arrive at <= XL+1); a known wand of teleportation is offered as "Zap at yourself" under 50% HP with monsters near, or under 70% with a stronger one adjacent (it joins the low-HP escape set). Strategy text names soldier ants and the teleport escape.

## Hosted 123518 — Mordor orc in a monster-filled room, T3499, Dlvl 8 at XL 5
**Cause:** a level teleport trap on Dlvl 6 dropped Jev (XL 5) into a closed room on Dlvl 8 behind a locked door. A pack gathered and the "pack at any HP" rule forced "Stay on Elbereth": 910 waits over ~1500 turns, at up to 50/58 HP. 5.0 spawns a random monster every ~70 turns above the Castle (allmain.c `maybe_generate_rnd_mon`), so the room filled with apes, fire ants, elf zombies and a giant beetle; cornered ones panic-attacked through Elbereth, 36 -> 0.
**Wiki (Elbereth):** "engrave it and wait for your HP to recover. Once you've recovered sufficiently, scuff the engraving and resume attacking... engrave it again." Elbereth is a rest stop, not a home.
**Fix:** `camped` = 40+ Elbereth waits in the last 50 decisions at >= 60% HP: the forced wait is lifted and attacks from Elbereth are offered again, so Jev thins the crowd and re-engraves when hurt. Strategy text says the same.

## Hosted 124104 — invisible Woodland-elves, T6670, Dlvl 8 (Mines) at XL 7
**Cause:** after a prayer (85/85) and a meal, unseen attackers (invisible Woodland-elves, which as @ also ignore Elbereth) hit Jev 60 -> 24 while it was forced to "Stay on Elbereth"; then, with no 'I' marked adjacent, the unseen-attacker filter fell back to `or opts` = only explore/retreat, and Jev walked around taking free hits, 24 -> 3 -> 0.
**Wiki (Invisibility):** "Searching will mark the location of unseen monsters, including invisible ones, with I... Searching can reveal their approximate location and help you take the fight to them." **Source:** detect.c dosearch0 calls `map_invisible` for an adjacent unseen monster.
**Fix:** with an unseen attacker and nothing adjacent marked, explore/retreat are dropped and "Search one turn to find the unseen attacker" is offered; the 'I' it maps gets the existing attack option. Strategy text says so. (The earlier "not protecting" change already lifts the forced Elbereth wait after a hit.)

## Hosted 124912 — coyote while fainted, T6390, Dlvl 2 (never got past it)
**Cause:** the only way on from Dlvl 2 was a locked door at (57,6). A shop on the level set `town`, and the kick rule refused *every* door on a town level, 13 times ("shopkeepers and the watch punish broken doors"). Jev searched 317 x 15 turns (mostly inside the shop, which can't have secret doors) for 4400 turns, prayed for hunger 5 times, then fainted out of prayer timeout beside shop food it couldn't afford.
**Wiki (Kick / Shopkeeper):** breaking a shop's door angers the shopkeeper; in Minetown the watch objects. **Source (dokick.c):** penalties only for `shopdoor` (add_damage SHOP_DOOR_COST) and `in_town(x, y)`; any other locked door may be kicked.
**Fix:** on a town-flagged level, a door is still refused if no for-sale squares are known, if it's within 3 squares of a for-sale item (the shop door), or if there's a fountain (likely Minetown); other doors get kicked. Still open: sell junk to buy food when starving beside a shop.

Follow-up (8aa4deb): search_spot skips squares within 2 of a for-sale item (a shop has one door; its walls hide nothing).

## 20261001-125203 — soldier ant, T6021, Dlvl 8 (XL 6)
- **Cause:** a trapdoor on Dlvl 7 dropped the bot to Dlvl 8 with no '<' known. It spent 450 turns resting and camping on Elbereth while a soldier ant (speed 18) kept coming back. It was stung on Elbereth at 23 → 7 HP. In 5.0, a scared monster that has no square to flee to still attacks: `panicattk`, monmove.c ~919. The gamble prayer (171 turns since the last one) was suppressed because the bot stood on Elbereth with HP above 5. It died with 4 unknown potions and 5 unknown scrolls.
- **Wiki (Soldier ant):** Elbereth works, but avoid being surrounded, know where the stairs are, and use escape items (teleportation) when a group threatens. Once you escape, steer clear.
- **Fix:** being hit within the last 3 turns now cancels the "on Elbereth, don't gamble" exemption and also counts as an attacker for the gamble prayer. STRATEGY now says that being hit on Elbereth means it isn't protecting you (pray, quaff or leave), and not to rest long beside a fast returning monster but to find '<'.

## 20261001-125400 — fire ant, T5164, Mines Dlvl 6 (max 9, XL 6)
- **Cause:** a yellow light was adjacent at 36/56. The bot swung at it under the "kill the yellow light" rule, missed, and it exploded, blinding the bot. Unseen fire ants then bit it. The blind block forced Elbereth, and 5 engravings in a row came back "interrupted" by the attacks. The bot never swung at the felt `I`s and was burned and bitten to death. (The run also reached Dlvl 9 at XL 4: the pace rule again.)
- **Wiki (Yellow light):** let it explode while you're already blind. A blindfold or towel makes it harmless, and a unicorn horn or cure-blindness fixes the aftermath. Killing it in melee is the fallback.
- **Fix:** with a towel or blindfold and a yellow light adjacent, the only option is to put it on. Once no light is in view, the only option is to take it off. When blind and engraving was interrupted within 5 turns, Elbereth is dropped and the felt adjacent unseen creatures get `F`-attack options. STRATEGY updated.

## 20261001-125902 — giant ant while fainted, T5236, Minetown Dlvl 6 (XL 4-5)
- **Cause:** chronic food shortage: 2 rations and 8 corpses in 5200 turns, plus prayers for hunger at T3095 and T4239. Minetown was fully explored, so the only option was "descend anyway" to Dlvl 7. That was too deep, so the bot ascended, and this repeated about 15 times (T3866-4198, ~300 Hungry turns). At Fainting it prayed again 910 turns after the last prayer: "Thou art arrogant", lost a level, still Fainting. A giant ant killed it while it was unconscious. It had 26 gold, a crossbow, bolts, daggers and gems to sell.
- **Wiki (Starvation / Minetown):** budget food early and carry spare rations. Minetown often has a delicatessen and general stores, so sell spare gear and buy food. Prayer fixes hunger only when the timeout allows; an early prayer angers the god and costs a level.
- **Fix:** "descend anyway" is not offered within 8 decisions of an `ascend`, which ends the ping-pong. STRATEGY now covers selling junk to buy food in Minetown and the risk of praying for hunger too soon. Open item: a real sell-to-buy-food option.

## 20261001-130229 — giant zombie, T5790, Dlvl 9 (XL 8, AC -1, speed boots, best run of the day)
- **Cause:** at 53/91 the bot sat on Elbereth between an ettin zombie and a giant zombie. Cornered, they panic-attacked (91-max HP: 56 → 31). Retreat went one step, and the bot then traded blows with the ettin. Its re-engrave came out garbled (28 → 6), and it waited on Elbereth until the giant zombie killed it. It had prayed 28 turns earlier, and '<' was 12 steps away. In speed boots (~20 speed) against speed-8 zombies, it could simply have walked away.
- **Wiki (Zombie / Speed boots):** zombies are slow; a fast hero outruns them. Don't melee heavy hitters while hurt; disengage.
- **Fix:** `spd` is 20 in worn speed boots. `outrun` means every nearby monster is at most 2/3 of our speed. With outrun and HP under 50%, `flee_up` is offered at any distance up to 60 and survives the adjacent "Elbereth-only" filter. The "fast" retreat check uses `spd`. STRATEGY updated.

## 20261001-130751 — potion of acid (quaffed at 3 HP), T6851, Dlvl 7 (XL 6, AC 7)
- **Cause:** two Uruk-hai came up a corridor, and the rear one zapped a wand of magic missile past the front one. The bot left Elbereth at 46/61 to melee the front orc (46 → 17). The "losing, Elbereth only" filter then left just `elbereth`. Elbereth does nothing against wands, and the bot was zapped 17 → 11 → 3. With the prayer 21 turns old, it quaffed an unknown potion (acid, d10) and died.
- **Wiki (Elbereth / Wand of magic missile):** Elbereth doesn't stop ranged attacks or wands. Against a zapper, get out of the line (step off the row or column, round a corner) or kill it fast. Reflection or magic resistance negates magic missile.
- **Fix:** the Elbereth-only filter no longer fires while `shot`, so attack and retreat options survive under wand fire. Open item: a "step out of the zap line" option.

## 20261001-131144 — gnome king, T4230, Mines Dlvl 6 (XL 5, AC 7)
- **Cause:** at 36/48 a gnome king (speed 10, also throws an aklys) attacked. The bot cycled through choke walks and Elbereth: 6 engravings in 11 turns, 5 of them "garbled". 5.0 engraving is an occupation, and each hit cut it off partway. It ignored its unknown wand (zap offered 4 times) and the attack options, falling 36 → 10 → dead. AC 7 at XL 5 also hurt.
- **Wiki (Elbereth):** engraving takes your turn and isn't protection until finished. Against one about-your-level melee monster, fighting (or zapping an unknown wand at it) beats re-engraving under its hits.
- **Fix:** a "garbled" engraving during which HP dropped now counts as interrupted (sets `engrave_interrupted` and `e_blockers`). The existing rule then drops Elbereth for 5 turns while that monster is adjacent, leaving attack, zap and flee.

## 20261001-131618 — hill orc, T2512, Mines Dlvl 5 (XL 4)
- **Cause:** two hill orcs and a wood nymph attacked. One orc threw a single dart at T2495, which marked "hill orc" as the shooter. Because a hill orc was within 8 squares, `shot` stayed true for 20 turns, so the adjacent orcs counted as shooters too. Elbereth waits were suppressed and attacks allowed, giving an engrave → attack (erases it) → engrave loop from 50 → 0, with a lucky healing quaff in the middle. It had a towel, 4 rations and an unread scroll.
- **Wiki (Elbereth):** Elbereth stops melee only; ranged attackers at a distance ignore it. Adjacent orcs respect it, and attacking from it erases it, so don't alternate.
- **Fix:** the 20-turn shot window applies only when the shooter is 2–8 squares away. An adjacent orc is a melee threat that Elbereth handles.

## 20261001-131856 — Woodland-elf, T4650, Mines Dlvl 7 (XL 5)
- **Cause:** after 400+ pace searches, "descend anyway" took XL 5 from Mines 6 to Mines 7. Two Woodland-elves (speed 12, AC 5, ignore Elbereth) attacked as it explored 15 steps from '<'. The only options were attacks: 55 → 15 in 3 turns. It zapped an unknown wand (nothing), prayed (healed to 55), then 55 → 10 → dead in 3 more turns.
- **Wiki (Woodland-elf / Gnomish Mines):** elves are the classic Mines killer for low-level characters. They come in groups, ignore Elbereth and hit hard with elven weapons. Retreat upstairs or fight them one at a time in a corridor; many players leave the lower Mines until stronger. (Mines-depth policy is still an open question for the user, so not changed.)
- **Fix:** two or more non-weaker monsters within 2 squares (`duo`) now offer `flee_up` with a 20-step radius. It is offered, not forced, because forcing a walk from speed-12 elves would give them free hits.

## 20261001-132133 — pony, T5858, Mines Dlvl 7 (XL 5)
- **Cause:** "descend anyway" took the bot to Mines 7 while Hungry and carrying no food (a peaceful gnome blocked the only fetch). It arrived on Elbereth 2 steps from '<'. Because of the pack rule it was forced to wait 16 turns at 55/55 while an orc horde, rothes and a pony gathered. Then it went Weak and prayed (prayed at T5000, now T5850); the prayer failed and cost a level. It walked off the square, the next Elbereth garbled, it was blocked from '<', and the pony and hill orcs took it from 46 to 0.
- **Wiki (Elbereth / Fleeing):** Elbereth buys time; it doesn't remove monsters, and new ones keep arriving. Stairs are the best escape, because only adjacent monsters follow you. Prayer timeout is random (about 50-1000), so praying again after ~850 turns can fail.
- **Fix:** the forced "stay on Elbereth" filter now keeps `flee_up`. STRATEGY: leave by nearby up stairs when a crowd keeps growing.

## 20261001-133139 — rothe while praying, T1233, Dlvl 5 (XL 4)
- **Cause:** 4 turns after arriving on Dlvl 5, a leprechaun, a wererat in @ form, a centipede, giant rats, a fox, a rothe and others boxed the bot in. The adjacent @ blocked Elbereth (correct, since @ ignores it). The mob rule kept only the attack on the highest-difficulty neighbour, the centipede, and never the wererat. HP went 51 -> 31 -> 24 -> 4; the prayer at T1233 came too late.
- **Wiki/source:** Wererat page: kill weres fast. mhitu.c (5.0): a were summons help on 1 in 10 of its attacks, in either form, so while it lives the crowd keeps growing.
- **Fix:** when mobbed, attack a were-creature first, then fall back to highest difficulty. STRATEGY updated.

## 20261001-133253 — wolf while praying, T3894, Mines Dlvl 6 (XL 6)
- **Cause:** a werewolf's bite infected the bot at T3725 ("You feel feverish"). The prayer at T3742 went to low HP (pray.c fixes TROUBLE_HIT before TROUBLE_LYCANTHROPE), so the lycanthropy stayed. At T3760 it turned into a 26-HP werewolf, Weak and Stressed with no food. In that form, "descend anyway" took it down twice, into the werewolf and its summoned wolves. It was Fainting when it prayed 150 turns after the last prayer; the prayer failed and it died praying.
- **Wiki (Lycanthropy):** cure it by prayer (major trouble), holy water or wolfsbane; avoid melee with animal-form weres. In animal form you are weak, so don't go deeper.
- **Fix:** no descend or "anyway" descend while polymorphed (`exp is None`). STRATEGY note on avoiding were bites and staying put in animal form.

## 20261001-133850 — hallucinogen-distorted imp, T4114, Dlvl 4 (XL 5)
- **Cause:** Weak, at 24/64 with a corroded cursed axe. A hill orc kept throwing a wielded (returning) aklys from 4 steps away. The "it shoots you, kill it" charge became the only option 3 times, at 15-24 HP, but the orc never got closer while an imp (speed 12, AC 2, regenerates) kept hitting. Off Elbereth at last, the bot quaffed unknown potions (hallucination, confusion), swung at thin air and died to the imp.
- **Wiki (Aklys / Imp):** a wielded aklys is tethered and returns to its thrower, so it acts as a repeatable ranged attack. Imps are fast and hard to hit, but respect Elbereth. Don't chase a ranged attacker you can't catch: break line of sight or leave.
- **Fix:** the forced charge at the shooter is dropped once 2 of the last 4 decisions were approaches and the shooter is still more than 2 away. STRATEGY: stop chasing a kiting thrower.

## 20261001-134441 — hill orc, T5706, Mines Dlvl 7 (XL 6)
- **Cause:** after fleeing up from Dlvl 8 and praying for hunger (T5697), the bot stepped on an unknown magic trap at 48/59. trap.c `domagictrap`: blinded (10-14 turns), deafened, and rnd(4) makemon calls beside it, which brought a hill-orc band, a pony and a wolf. With 10+ adjacent, the only option was Elbereth; the attacks interrupted it, and it died the next turn. '<' was 3 steps away; flee_up was filtered out because the bot couldn't outrun them.
- **Wiki (Magic trap):** the "flash of light / deafening roar" effect summons monsters around you. Prayer was spent and blind engraving gets interrupted, so the stairs were the only real exit.
- **Fix:** the adjacent-mob Elbereth/pray filter keeps flee_up when '<' is within 3 steps. STRATEGY line on summoned crowds.

## 20261001-135115 — giant rat, T1591, Dlvl 4 (XL 3)
- **Cause:** a wererat bite infected the bot (T1522). The first prayer at T1535 (6/23 HP) fixed low HP only. pray.c `pleased`: off an altar, action is rn1(Luck+2, 1), so with Luck 0 only half of prayers fix every major trouble. At T1560 it turned into a wererat, the shield and spear fell off, and it dropped the rest because it was Overloaded. Back in dwarf form at AC 10 with no weapon, beside the pile, it punched an acid blob 3 times (it wasn't marked passive, and the mob rule picked it as the highest-difficulty neighbour). Being splashed, and with two potions spent, 3 rats took it 24 -> 0.
- **Wiki (Lycanthropy / Acid blob):** a low-HP prayer may leave lycanthropy uncured. An acid blob only hurts you when you hit it (passive), so never fight it while other things bite.
- **Fix:** acid blobs and jellies are now `passive`, so they're ignored as mob targets and adjacent threats. Mob targeting never picks a passive monster.

## Run 20261001-135233: stuck in a closed shop (T399 to T10300+)
- **Cause:** a trap door on T399 dropped Jev into a shop that was "Closed for inventory", whose door is locked. With 0 gold, the town guard refused every kick. Explore bumped the door and waited, about 10000 turns, living on prayers.
- **Wiki:** a closed shop's door is locked. You can leave with an unlocking tool, a wand of opening, knock or teleportation. Breaking the door angers the shopkeeper unless you pay 400zm on the spot (shk.c pay_for_damage: money plus credit below the cost means angry).
- **Fix:** after 100 resets with nothing to do, read an unknown scroll, since it might be teleportation. After 300, kick the adjacent locked door anyway. A dangerous exit beats an endless wait.

## Run 20261001-141935: killed by an ape, praying on T4683 (Dlvl 6, XL 6)
- **Cause:** Elbereth wore off, and the bot closed in on an ape (3 attacks, up to 12 a turn). The engraving garbled, and melee went 38 -> 12 with `attack` as the only option. The bot had prayed 103 turns earlier, so the final gamble at 3 HP failed. Two unknown potions and an unknown iron wand stayed in the pack. Unknown potions were gated on LOW_HP (≤9 at XL 6). The wand was gated on 7 squares of ray room, which a wall rules out when the foe is adjacent.
- **Wiki:** when prayer is on timeout, unknown potions and wands are the escape items. Use them before HP is critical, since a bad one is rarely worse than dying in melee.
- **Fix:** if the last prayer was under 500 turns ago (or the god is angry) and HP is below a third, offer the unknown potions with a monster adjacent. Also zap the unknown wand at an adjacent foe even if a ray might bounce.

## Run 20261001-142245: killed by a giant bat on T2942 (Dlvl 4, XL 3, AC 6)
- **Cause:** at 21/28 the bot left its Elbereth to chase a giant bat. The bat (speed 22) bit about twice a turn, 15 -> 4 in one turn. A prayer healed the bot fully, but it kept meleeing, chose attack over Elbereth at 17 and 14 HP, and died. monsters.json rated the giant bat danger 0, so it showed as "about your level" with no tip.
- **Wiki:** giant bats are fast and erratic and hit hard for the early game. Let them come to you, fight with F, and don't chase them. They respect Elbereth.
- **Fix:** giant bat danger 1, plus a "Fight if HP above half...; avoid if below half: Elbereth, quaff or pray early" tip.

## Run 20261001-142442: killed by a werewolf on T3278 (Dlvl 6, XL 4, AC -3)
- **Cause:** the bot took the downstairs anyway at XL 4, reaching Dlvl 6. Fifteen turns later it was surrounded: a werewolf in @ form, 6 or 7 wolves it had summoned, plus an imp. It took 47 -> 24 -> 9, prayed (healed to full), then 47 -> 32 -> 11 -> 0. Two unknown scrolls stayed unread.
- **Wiki:** a werewolf in @ form ignores Elbereth and summons wolves. When surrounded, use an escape item (teleportation) or the stairs. Scroll of teleportation is the commonest unidentified escape scroll.
- **Fix:** with 3 or more hostiles adjacent and HP below half, offer reading an unknown scroll through the 'teleport' slot. The deeper cause, descending to Dlvl 6 at XL 4, is the unanswered question about the descend pace.

## Run 20261001-142718: killed by a wolf on T2110 (Dlvl 7, XL 5)
- **Cause:** the bot meleed an animal-form werewolf for 17 turns from 63/63 (the tip said avoid only "when hurt") and prayed at 12. The next bite gave lycanthropy (T2054). 34 turns later it turned into a wolf and burst out of its splint mail, shield and helm. It came back to dwarven form at AC 10 with no weapon, and wolves killed it. (The new unknown-scroll escape did fire on T2077, but it was enchant armor.)
- **Wiki:** never melee a were in animal form; each bite risks lycanthropy. Kill it with ranged attacks or from Elbereth, which scares the animal form. Cures are prayer, holy water or wolfsbane.
- **Fix:** with an animal-form were adjacent and no lycanthropy yet, drop the attack options whenever Elbereth is offered or already engraved. The tips for all three weres now say to avoid melee in animal form at any HP.

## Run 20261001-143047: killed by a winter wolf on T8516 (Dlvl 6, XL 6, AC 7)
- **Cause:** at 58/69 the bot stepped off Elbereth to explore, with its prayer 20 turns old. Two winter wolves (difficulty 9) took 58 -> 0 in 6 turns, about 10 HP a turn. Two unknown potions healed only a little. The tip said "Fight if over half HP", so the bot meleed them.
- **Wiki:** winter wolves are a mid-game threat (difficulty 9, 2d6 bite). A Valkyrie resists the breath, but the bite alone outdamages an XL 6 at AC 7. They respect Elbereth.
- **Fix:** winter wolf danger 1 -> 2, and the tip now says fight only at XL 10+ with AC 3 or better, and otherwise use Elbereth or the stairs early.

## Run 20261001-143800: killed by a rope golem on T4257 (Dlvl 7, XL 6, AC 2)
- **Cause:** a 130-turn bleed-out. The bot camped on Elbereth and rested among zombies, an ape, a giant ant, coyotes and a rope golem. Cornered monsters panic-attack anyway, so it slowly dropped 29 -> 1. The prayer at 12 HP did nothing. 4 unknown scrolls and an unknown wand stayed unused. The forced Elbereth-wait filter would have dropped a teleport option even if one had been offered.
- **Wiki:** Elbereth is breathing room, not healing, in a busy spot. Once prayer is gone, unknown scrolls are a teleportation lottery worth taking.
- **Fix:** with the prayer used (or the god angry), LOW_HP and a hostile within 3, offer reading an unknown scroll as 'teleport'. The forced Elbereth-wait filter now keeps 'teleport'.

## Run 20261001-144419: killed by her own bolt of fire on T7065 (Dlvl 7, XL 8)
- **Cause:** my b984ca7 change. Below 1/3 HP it let the bot zap any wand at an adjacent foe even without room for the ray. Blind in a corridor at 26/92, it zapped a known wand of fire at an unseen attacker. The ray bounced off the nearby wall and hit it back (Valkyries resist cold, not fire). Dead.
- **Wiki/source:** zap.c buzz() rays travel rn1(7,7) squares and bounce off walls, so a wall close behind the target sends the ray back through you. Only zap known ray wands where there's room.
- **Fix:** skip the room check only for unknown wands; known ray wands always need 7 squares of room.
- **Second lesson, AC 10 with a plate mail in the pack from T3173:** an 'apron' (alchemy smock) is a cloak, but the cloak regexes missed it. Wearing body armor failed with "You cannot wear armor over a apron", and the armor was marked unwearable. Fix: 'apron' is now in the cloak regexes, so act_wear takes it off first and puts it back on afterwards.

## Run 20261001-150143: killed by a land mine on T4823 (Dlvl 6, XL 4)
- **Cause:** at 14/50 on Dlvl 6 (XL 4: descend pace again), Uruk-hai were shooting poisoned arrows from 4 steps. Shots skip the forced Elbereth wait, because Elbereth doesn't stop missiles. The bot explored away instead and stepped on a hidden land mine (rnd(16) damage, trap.c), which was lethal at 14 HP.
- **Wiki:** a land mine is invisible until found or triggered. Wandering unexplored floor at low HP risks it, and the real fix is to rest before exploring. Breaking line of sight from archers is the right reaction to being shot.
- **Fix:** none yet. This is about 12% bad luck on top of two open items: the descend pace (awaiting the user) and moving out of a shooter's line (still to do).

## Run 20261001-150449: killed by a soldier ant on T5688 (Dlvl 8, XL 6, AC 5)
- **Cause:** on Dlvl 8 at XL 6 (pace again), a soldier ant hit through Elbereth (a scuffed engraving or a cornered panic-attack). The bot then spent 6 turns alternating Elbereth (2 garbled), wait and a single attack while the ant took 58 -> 14. A zap and a prayer 331 turns after the last one followed. The prayer failed, a level was drained, and the bot died.
- **Wiki:** you can't outrun a soldier ant (speed 18). Once Elbereth fails, every turn spent re-engraving is a free round for it, so fight back or use an escape item.
- **Fix:** for 6 turns after "not protecting", the forced Elbereth wait no longer applies. If an attack is on offer and no escape item is, drop elbereth and wait so the bot commits to the fight.

## Run 20261001-150815: killed by a human zombie, praying on T4041 (Dlvl 6, XL 5)
- **Cause:** a pack of human zombies on Dlvl 6 at XL 5 (pace again). The bot retreated, explored back into them, then fled for the upstairs and got clawed on the way, 30 -> 10. A prayer 252 turns after the last one failed, and the zombies surrounded it. The flee_up after the prayer crashed in act_go: @ wasn't on screen, so snap.me was None and cheb(None) raised.
- **Wiki:** zombies are slow (speed 6). Outwalk them or fight them one at a time in a corridor. Don't step back toward a pack.
- **Fix:** act_go returns when @ isn't on screen instead of crashing. The tactics are left to the pace question.

## Run 20261001-151100: killed by a hill orc on T4962 (Mines level 6, XL 5, AC 10, naked)
- **Cause:** ~1000 turns on Mines level 6 without finding the downstairs, mostly camped on Elbereth. A water nymph stole the shield (T3749, right after an attack from Elbereth), then the dagger and helm (T4641), then the bronze plate mail (T4701). With only gold left, AC 10 and bare hands, a hill orc pack finished it. leave_nymph needs known downstairs, so it never fired.
- **Wiki:** nymphs respect Elbereth, so don't attack from it (that erases it). Kill them with missiles, and leave the level once one has started stealing.
- **Fix:** the nymph tips now say never melee, wait on Elbereth when she's adjacent, and leave the level once she has stolen. Still open: leaving by the upstairs when the downstairs is unknown, which risks ping-ponging, plus the Mines/pace question.

## 20261001-151630 — poisoned by a rotted hill orc corpse (T2660, Dlvl 6)
- Cause: corpse age is tracked per square. A fresh lizard kill landed on an old hill orc corpse; after eating the lizard (age 17) the bot ate the orc under the same "21 turns" stamp. It was tainted (eat.c: age/(10+rn2(20)) > 5, so ≥50 turns old). The prayer then failed ("Tyr is displeased").
- Wiki: only eat corpses you saw die, or that are under 50 turns old; in a pile, the top corpse is the newest and the ones below are of unknown age.
- Fix: after eating a corpse, the square's age is reset to unknown, so leftover corpses there are treated as rotten.

## 20261001-152045 — killed by a Green-elf (T7362, Dlvl 8)
- Cause: XL7 at 47/86 meleed a Green-elf beside a giant spider, and both together took it to 11. It engraved Elbereth, and then the low-HP filter left only `pray`, 113 turns after its last prayer. Tyr: "Thou art arrogant", so it lost a level. At 1/74 it chose flee_up over an unread scroll (13 unknown scrolls in pack) and was hit on the way.
- Wiki (Prayer): the timeout after a good prayer is rnz(350) (median ~350), and major trouble is only fixed when timeout < 200. At ~100 turns the prayer is a coin flip with smiting on failure. On Elbereth, waiting for HP regen, or reading an unknown scroll (teleport is the most common), beats it.
- Fix: the low-HP filter keeps `wait` and `teleport` beside `elbereth` when the prayer is a <200-turn gamble. At low HP with no prayer and a hostile adjacent, drop `flee_up` when a teleport scroll is available.

## 20261001-152602 — killed by a gnome lord (T7245, Dlvl 7)
- Cause: it ate almost no corpses and lived on prayer (8 prayers, 6 of them for Weak). At T6974–7077 it bounced between `choke` (walk to a corridor because a bugbear/hobgoblin pack was 4 steps off) and `explore` (walks back, sees the pack, stops) 34 times. The pack never came, and it went from Hungry to Weak. Next, killer bees and a water nymph took its weapon and loot. It was Fainting with the prayer only 184 turns old, and gnomes finished it at AC 10.
- Wiki (Fighting in corridors / Nutrition): a corridor only helps if the pack follows. Monsters that don't approach should be ignored or walked away from, and the turns go to finding food.
- Fix: `choke` is no longer offered once it has been chosen 3 times in the last 12 decisions.

## 20261001-153148 — killed by a bolt of fire zapped by a mountain nymph (T9939, Dlvl 6)
- Cause: a mountain nymph stole one of two identified wands of fire (plus the spear). It came back and the bot waited on Elbereth (39/66) as the nymph tip said; fleeing, she zapped the stolen wand. A 6d6 bolt plus its bounce did 39+. The bot never zapped its own wand of fire at her: zaps were only offered below half HP, and the nymph filter kept just pray/quaff/wait.
- Wiki (Nymph): kill nymphs at range before they touch you. A nymph that steals a wand uses it (muse.c: monsters zap attack wands). Wand of fire kills any nymph (2d HD 3).
- Fix: a known wand (with the existing ≥7-square ray-room check for rays) is offered against a nymph in line within 6 at any HP, and the nymph filter keeps that zap.

## 20261001-153709 — killed by a bolt of lightning zapped by an ogre (T5319, Dlvl 10)
- Cause: the bot reached Dlvl 5–6 at XL 3 (descend-anyway pace, still an open question). A level teleporter took it to Dlvl 9 and an unknown scroll read to escape a mountain centaur took it to Dlvl 10. With no '<' found in 270 turns (mostly rest/wait at half HP), an ogre with a wand of lightning blinded it and zapped it dead while it retried Elbereth, which does not stop rays. It carried 3 unknown wands the whole game.
- Wiki (Engrave-identification): engraving with an unknown wand costs one charge. Digging, fire and lightning identify themselves, and wishing/create monster/light/enlightenment show their effect. A wand of digging zapped down is an instant escape hole out of a losing fight.
- Fix: with nothing hostile in view, not hungry/low, the bot engrave-tests each unknown wand once (answers the wish prompt with blessed +2 gray dragon scale mail). The existing low-HP "wand of digging" escape can now trigger.

## 20261001-154015 — killed by a hallucinogen-distorted dwarf king (T4026, Dlvl 5)
- Cause: hallucinating at XL 6, AC 4, 35/60, it meleed a monster that showed as a random name each turn. It was a dwarf king (mattock d12): 35 -> 14 in one turn. Elbereth is never offered while hallucinating and 14/60 is not low-HP by the prayer rule, so it threw a dart and died to the next hit.
- Wiki (Hallucination): you cannot judge monsters, so judge by damage taken. Elbereth works the same while hallucinating (only @ and minotaurs ignore it). Dwarves with mattocks are the classic early killer.
- Fix: `big_hit` = the last turn's damage ≥ current HP with something adjacent. Then Elbereth is offered even while hallucinating, and if any escape (elbereth/retreat/flee_up/upstairs) exists, attack/throw/approach/rest/wait are dropped.

## 20261001-154407 — killed by a rothe, fainted from lack of food (T7765, Dlvl 8)
- Cause: no packed food, lived on corpses and prayer (prayed at 7408, 7552 for HP, then Fainting at 7694, too soon, so it failed). While Hungry at 30–40/63 it camped ~40 turns on Elbereth (forced wait) against a single rothe, which is both weaker and food. It went Weak, then Fainting in Minetown, and a rothe got it while it was out. Also, the engrave-test option was offered 39 times and never chosen.
- Wiki (Nutrition): Hungry is the time to get food, not to rest. A rothe corpse is 100 nutrition and safe fresh. Elbereth-camping only trades HP regen for nutrition.
- Fix: the forced Elbereth wait no longer applies while Hungry once 15 of the last 20 choices were waits (no pack). The engrave-test is forced when nothing hostile is in view.

## 20261001-155117 — killed by a raven, while praying (T8632, Dlvl 5)
- Cause: all 7 earlier prayers were for Weak (no food found in 8600 turns). Three nymphs on Dlvl 5 stripped it from AC 0 to AC 10 and took the spear. The downstairs was never found, and the nymph rule ("on Elbereth, a nymph within 3: only wait") produced 874 waits in 2200 turns, e.g. 228 with a water nymph sitting 2 steps away. A raven blinded it and bit it from 46 to 7, unarmed at AC 10. A 639-turn prayer failed.
- Wiki (Nymph): leave her level or kill her. Waiting on Elbereth does not make a nymph leave, and every turn spent there is nutrition and exploration lost.
- Fix: the nymph wait-only filter is skipped once 70 of the last 80 choices were waits, so exploring (and finding the stairs) resumes.

## 20261001-160052 — killed by a soldier ant (T8671, Dlvl 8)
- Cause: at 65/76 a Woodland-elf shot it, then soldier ants and an elf mummy joined. It chose flee_up 4 times in a row; each step was cut short after 1 square and hit (55 -> 17 -> 0). It had a wand of fire and two potions of healing: the danger-quaff loop breaks on the first potion in inventory order, so only an unknown yellow potion was ever offered. An identified uncursed amulet of guarding sat unworn.
- Wiki (Soldier ant): "the top killer": don't run from speed 18 in the open. Fight from Elbereth (it respects it), quaff healing, zap attack wands. Running for stairs only works if they are a few squares away.
- Fix: known healing potions are offered first. flee_up is dropped after two one-step flee_up attempts in a row (when other options exist). Known-good uncursed amulets (life saving, reflection, guarding, ESP) are worn.

## Run 20261001-160537 — killed by Ms. Zum Loch, the shopkeeper (T17928, Dlvl 4)
- **Cause:** a yellow light exploded at the door of Zum Loch's liquor emporium and blinded Jev. When Elbereth was interrupted, the "fight back felt monsters" rule swung at the unseen creature next to the door. It was the shopkeeper ("You miss it. It gets angry!"), and no "Really attack?" prompt appears while blind. Her wand did the rest.
- **Wiki:** Shopkeeper: never fight blind near a shop. Peaceful checks need sight. Yellow light: kill it at range or let it go; its explosion blinds for a long time.
- **Fix:** a "Welcome (again) to X's" message records (dlvl, turn). Being blind within 100 turns of it on the same level counts as being in a shop, so the attack and zap options and the felt-monster swing are all withheld.

## Run 20261001-162838 — killed by a jaguar (T9280, Dlvl 7)
- **Cause:** the bot prayed at T9226, then descended into killer bees, a jaguar and a pony. It got to 4/68 HP on a working Elbereth (the jaguar "turns to flee"), but the forced Elbereth-wait still offered flee_up. Twice it stepped off toward '<' 3 squares away. The jaguar (speed 15, 3 attacks) is faster than the bot and finished it.
- **Wiki:** Elbereth: when it's working, stay on it. A faster monster gets free hits while you walk away, and fleeing only works if you can outpace it or the stairs are adjacent.
- **Fix:** the forced Elbereth-wait keeps flee_up only at or above 1/3 max HP. Below that it's wait/quaff/pray/teleport.

## Run 20261001-163526 — killed by a pony (T3251, Dlvl 5)
- **Cause:** at T729 the bot read an unknown scroll and was punished, chained to a heavy iron ball. At XL 4 with AC 5, a pony (speed 16) chipped it from 41 to 12 HP over ~10 turns of missed melee. The bot was carrying an identified **wand of cold** that it never zapped, because ray wands need 7+ squares of open line so the bounce can't come back. Then a garbled Elbereth and an unknown potion.
- **Wiki:** Valkyrie: intrinsic cold resistance, so your own bouncing cold ray can't hurt you. The wand of cold is a top escape and kill tool for a Valkyrie at any range.
- **Fix:** a wand of cold skips the bounce-room check.

## Run 20261001-163711 — killed by a giant spider while fainted (T6684, Dlvl 8)
- **Cause:** no permanent food, just prayers for Weak at T2048, 4522 and 5366. While Not hungry at T5976 the bot ate a homunculus corpse ("Ecch - that must have been poisonous!"), Str 17 → 13. Giant spider bites took it to 9, and a Weak-hunger giant beetle corpse took it to 5, then 4. By T6684 it was Weak, its prayer only 250 turns old after an HP prayer at 6435, at 32/73 HP. It fainted next to a giant spider on Dlvl 8.
- **Wiki/source:** Poisonous corpses (monsters.h M1_POIS: bees, soldier ants, giant beetles, homunculi, rabid rats, giant spiders, scorpions, snakes, yellow molds...) cost Str or rnd(15) HP without poison resistance, and a dwarvish Valkyrie has none. Only eat them when the alternative is fainting.
- **Fix:** POISONOUS joins NEVER_EAT, and is lifted like kobolds only when `desperate` (Weak/Fainting with no prayer).

## Operator rule: scrolls (after run 20261001-163526's punishment)
- **Rule (operator):** NEVER read an unknown scroll unless it's price-ID'd as identify. Always read identify when there's a major non-gem unknown.
- **Wiki:** Price identification: identify is the only base-20 scroll and the most common (18%). Unknown scrolls include fire, amnesia, punishment, create monster, teleportation, destroy armor and aggravate monster.
- **Fix:** removed all three unknown-scroll reads (stuck searching, trapped/walled in, emergency "teleport" gamble). Known or price-ID'd identify is now forced when nothing hostile is in view and an unknown wand, ring, amulet, potion or scroll is in the pack. The identify menu picks wands, then amulets, rings, armor, potions, scrolls, and gems last.

## Run 20261001-164503 — killed by a wolf (T3260, Dlvl 7 Minetown, XL 5)
- **Cause:** the bot dove from Dlvl 5 to 7 at XL 5. A wolf pack, a warg (difficulty 8) and a lizard arrived. On a fresh Elbereth at 32/38 with a wolf and a lizard 2 squares off, the only options were explore, because the forced Elbereth-wait needs a 3+ pack or under 75% HP. It stepped off, the warg joined, Elbereth came out garbled, and it went 32 → 19 → 0 in two turns without ever praying.
- **Wiki:** Wolf/warg: they come in packs, so fight from Elbereth or a corridor. Don't walk into the open while two of them are close.
- **Fix:** `duo`, two or more non-weaker hostiles within 3 squares, also holds the bot on a working Elbereth.
- The recurring pace problem (XL 5 on Dlvl 7) is still open with the operator.

## Run 20261001-164712 — killed by a hill orc (T6093, Dlvl 7, XL 6, AC -3)
- **Cause:** about 13 hill orcs arrived one or two at a time in Minetown, and one zapped a wand of striking. Elbereth is no help against wands, and its engraving was wiped or garbled while fighting. It went 35 → 16 in one turn, then down to 11/63 with three orcs adjacent. Prayer wasn't offered because 11 is above the 1/7 low-HP threshold, and none of its six unknown potions was offered while orcs were adjacent. Dead next turn.
- **Wiki:** Potion: when death is otherwise certain, an unknown potion is a fair gamble. Healing-family potions are about 12% of potions, and few outcomes are worse than dying. A wand-zapping orc is a priority kill.
- **Fix:** below 1/4 HP with two or more hostiles adjacent, unknown potions are offered even in melee.

## Operator request: 5.0 corpse safety review
- **Source (eat.c 5.0, monsters.h):**
  - Tainted means rotted > 5. In 5.0 you survive food poisoning with only a Con-in-100 chance (timeout.c), so it's still deadly; prayer cures it.
  - Globs no longer taint in 5.0; they shrink away.
  - Lizards, lichens and acid blobs never rot. Acid blobs do rnd(15) acid damage.
  - Poisonous corpses (M1_POIS) cost rnd(4) Str and rnd(15) HP 4 times in 5.
  - cpostfx side effects:
    - polymorph: chameleon, doppelganger, genetic engineer;
    - helpless 20-50 turns as gold: mimics;
    - stun: stalker 60+, bat 30, giant bat 60;
    - speed toggle: quantum mechanic;
    - random intrinsic loss: disenchanter;
    - 200 turns of hallucination: violet fungus, yellow mold;
    - aggravate monster: dogs and cats;
    - lycanthropy: human-form weres;
    - cannibalism (Luck -2..-5, aggravate): dwarves, for a dwarven Valkyrie. Humans and elves are fine, and elves give sleep resistance.
- **Fix:**
  - POISONOUS now covers the full list (snakes, jellyfish, salamander, guardian naga, green dragon) and is allowed only when desperate.
  - New BAD_EFFECT list is never eaten, even when desperate.
  - Acid blobs are allowed when desperate at any age.
  - Added a check to test_corpse.py.

## Run 20261001-165103 — killed by a jaguar (T3778, Dlvl 5, XL 3, AC 7)
- **Cause:** the bot descended to Dlvl 5 at XL 3 (pace again). A jaguar (speed 15, three attacks) and a Green-elf shooting arrows took it 31 → 14. It then chose "Run for the upstairs" twice with the jaguar adjacent, taking free hits each step: 14 → 8 → 0. Elbereth was on offer and unused. Prayer was never used, but at 8/31 HP it doesn't count as major trouble (≤5 or under 1/7 HP).
- **Wiki:** Elbereth stops the jaguar's melee. You can't outrun a faster monster, so walking away from it is worse than standing.
- **Fix:** with Elbereth available, an Elbereth-respecting hostile faster than 12 adjacent, and '<' not adjacent, flee_up is dropped.

## Run 20261001-165326 — killed by a Woodland-elf (T4520, Dlvl 7, XL 5, AC 6)
- **Cause:** pace again: XL 5 on Dlvl 7. A Woodland-elf, which ignores Elbereth, hit for 7–11 a turn, 47 → 11. Prayer was never used, but 11/47 is above major trouble (under 1/7 or ≤5), and the next hit killed it. Its five unknown potion types were never offered with only one monster adjacent.
- **Wiki:** Woodland-elf: avoid below XL 6 unless at a choke point, go upstairs. When one more hit kills you, an unknown potion beats a swing.
- **Fix:** below 1/4 HP, unknown potions are offered if any adjacent hostile isn't "weaker" (previously required two adjacent).

## Mines cap and Sokoban first (operator request)
- **Why:** 33 of 78 Hosted deaths were in the Mines, mostly on Dlvl 6–8 at an average XL of 5.5.
- **Fix:**
  - On every new Dlvl, ^O (dungeon overview) shows whether we are in the Gnomish Mines.
  - Mines levels get their own memory key, and the main-dungeon '>' that leads to the Mines is remembered.
  - Below XL 6 (`MINES_XL`), the Mines are left until Sokoban is done, and the bot never goes past Minetown (Mines level 3+). The Mines '>' on the branch level is skipped while the main '>' is unfound (up to 500 turns of searching).
  - This sends early games through the main dungeon to the Oracle and Sokoban.
- **Operator tip:** with no pick-axe and a pet nearby, follow a dwarf (up to 40 decisions per level) so the pet kills it. A pick-axe on the floor is always picked up.

## Run 20261001-165519 — killed by a snake while praying (T4589, Mines Dlvl 7, XL 6)
- **Cause:** a Mines level past Minetown. Elbereth was garbled 3 times, 3 striking zaps hit nothing, and the prayer came 797 turns after the last one.
- **Fix:** the Mines cap above.

## Run 20261001-165928 — fainted, killed by a giant bat (T5360, Dlvl 4)
- **Cause:** at Fainting with an imp adjacent, a gamble prayer 109 turns after the last one angered Tyr. After that the bot had no food and no prayer. It searched a Dlvl 4 whose '>' was never found, beside two locked doors, while carrying a key. "Unlock it with your key?" was answered with ESC, so keys never opened anything.
- **Wiki:** a locked door opens with an unlocking tool (key, lock pick, credit card). A closed shop can be unlocked and used as normal; only breaking its door angers the shopkeeper. Minetown's watch punishes lockpicking.
- **Fix:** the bot answers `y` to "Unlock it" outside town, and tries an unlocking tool on a locked door before kicking it.

## Run 20261001-170330: killed by a jaguar (T7489, Dlvl 7, XL 7)
- **Cause:** a jaguar and a Green-elf were adjacent at 28/72 HP. The bot zapped its wand of teleportation at itself five times and got "Nothing happens" every time. The wand was empty, and each zap was a free round of hits. A wand of cold was in the pack.
- **Wiki/source:** zap.c dozap: if the wand isn't zappable (no charges left), you get "Nothing happens". Bad luck instead gives "Unfortunately, nothing happens" and burns a charge.
- **Fix:** after a zap that reports "Nothing happens", the bot marks the wand "(empty, x:0)" in its inventory, and every wand option skips it. Teleport and attack zaps then fall through to the next option.

## Elbereth is for emergencies only (operator)
- **Operator:** "I've hardly used Elbereth in real games except for emergencies. The default is to retreat to a hallway and fight monsters 1 on 1."
- **Data:** the bot engraved 2–140 times per game, mostly with Elbereth as the only option offered (forced).
- **Fix:**
  - Elbereth is now offered only below 45% HP (was 70%), against dread monsters or unseen attackers, or for a pack in the open with no reachable corridor below 60% HP.
  - "Fight from a corridor" is also offered when monsters are already adjacent, if the bot can outrun them.
  - The strategy text now gives corridor fighting as the default.

## Run 20261001-170929: killed by a little dog (T1741, Dlvl 4, XL 4)
- **Cause:** at 51/51 HP the bot walked for '<' with a weaker but fast (speed 18) little dog adjacent. Three blocked steps gave three free bites, 51 → 14. Then Elbereth, a hit on it anyway, an early prayer, and a hill orc.
- **Wiki:** you can't outrun something faster than you. Fight it.
- **Fix:** whenever '<' isn't adjacent, the bot no longer runs for it on foot with a speed-13+ melee monster adjacent. This used to apply only when Elbereth was also on offer.

## Gold (operator rule, from earlier)
- **Rule:** gold buys protection from any temple priest, then keep 2000–4000 for shops.
- **Data:** the last eight games ended with 6–160 gold. fetch_gold was taken in 14 of 45 offers.
- **Fix:**
  - The bot always goes for visible gold when no active hostile is in view, HP is at least half, and it isn't Weak.
  - A '$' it fails to reach 3 times is dropped (it had walked "blocked after 1 step" six times in a row).

## Dart traps and lichen corpses (operator)
- **Dart traps:**
  - **How a trap is recognized:** "A little dart shoots out at you", or a '^' within 8 squares that farlooks as a dart trap.
  - **When it is used:** the bot has fewer than 10 darts, no active hostile is in view, and HP is at least 70%. It stands beside the trap and #untraps it, up to 15 tries per trap.
  - **Source (trap.c):** a disarm succeeds with chance 1 in 3 and drops 50-rnl(50) darts. A "Whoops" failure walks you onto the trap for one dart, which lies there if it missed.
  - **After a disarm or a Whoops:** the bot steps on the square, picks up the darts and drops all but 10. It stops picking up darts once it has 10.
  - **Risk:** 1 trap dart in 6 is poisoned, and without poison resistance poison is deadly 1 time in 30.
- **Lichen corpses:**
  - They never rot (eat.c nonrotting_corpse).
  - After a lichen kill, the bot steps onto the corpse and picks it up, carrying up to 4.
  - Lichen corpses in the pack get eaten like any other food when Hungry.

## Ghost on a bones level (run 171431, Dlvl 7, T6700-8950)
- Cause: "Hosted's ghost touches you!" matched unseen_attacker() → find_unseen/Elbereth, and every touch interrupted search_hidden ("You stop searching"), so the hunt for the hidden '>' never progressed.
- Wiki (Ghost): speed 3, AC -5, 1d1 touch: harmless and very hard to kill; lure it away and work elsewhere.
- Fix: ghost messages no longer count as an unseen attacker; on a ghost touch/miss the bot records lv.ghost and search_spot skips spots within 8 squares of it for 300 turns (it's 4x slower than us).

## Wand of speed monster (operator rule)
- Earlier deaths carried an unused "wand of speed monster" (the attack-wand picker rightly skips it).
- Source (apply.c do_break_wand): breaking it is a rnd(4*charges) magic explosion, then the speed effect hits every adjacent square.
- Fix: with no hostiles in view and HP ≥ max(35, 70%): zap self ('.'), zap an adjacent pet, then break it (when the pet is adjacent or there's no pet).

## Web sealed the stairs room (run 171431, Dlvl 7, T9000-11400)
- Cause: the only door into the '>' room (and a corridor) held a web, shown as '"'. nh.py walkable() didn't include '"' (neither trap nor object), so '>' was unreachable. The bot searched for a hidden path; once the ghost fix ruled out search spots near the ghost, it waited ("Nothing else is possible").
- Wiki (Web): walking in gets you stuck for a few turns; strong characters tear it apart. Not a wall.
- Fix: '"' is walkable at trap cost (20), like '^'.
- Follow-up: '>' still unreachable. The bot stood in an unlit area whose neighbors render blank, so no path existed from its square. The fallback 'wait' looped about 2000 turns, with 2 prayers spent on hunger. Fix: after 3 of 5 waits with no hostiles in view, step into a random blank/walkable neighbor to reveal the dark.

## Rope golem, dig_down while held (run 172609, Dlvl 7, T14075)
- Cause: a rope golem grabbed Jev. At HP < 50% the bot zapped the wand of digging down 12 times, and each zap failed with "You are being held, and cannot go down"; choked 47 -> 0. Prayer had been used at T13996 on hunger during the 2000-turn dark-spot wait loop (fixed above).
- Wiki (Rope golem): held, you can't move away or go down; kill it (AC 8, weak) or teleport; Elbereth works while grabbed.
- Fix: no dig_down offer while held; "You are being held" now also sets held, so only attack/Elbereth/pray/quaff/zap remain.

## Gold golem after a hole to Dlvl 7 (run 172642, XL4, T2696)
- Cause: a hole dropped Jev from Dlvl 5 to 7 (Oracle level) at XL4. With '<' unknown, ascend was never offered, and it spent ~300 turns on fetches, pickups and hidden-door searches. It meleed a yellow light off Elbereth (rule: kill it), missed, and the light exploded. Blind, it was mobbed by unseen Mordor orcs with prayer spent (T2605); a gold golem finished it.
- Wiki (Trap door/hole): you land on a random spot below; the way back is '<', so finding it is priority one when the level is beyond you.
- Fix: too deep with no '<' known (outside the Mines) → only exploring and fighting, no fetch/goto/shop detours (rest kept for healing) while explore options exist.

## Plains centaur (run 172855, Dlvl 7, XL6, T7850)
- Cause: a plains centaur (speed 18, weapon+kick) kept hitting and running. At 15/47, on a fresh Elbereth the centaur fled from, the only options were explore_*. Its square (3 steps NE, across a wall corner) wasn't in the path map, so it didn't count as 'near', and the stay-on-Elbereth wait wasn't offered. Jev explored off and died. It had prayed at T7835 (1 HP).
- Wiki (Plains centaur): fast; Elbereth works on it; don't let it get free hits while you wander.
- Fix: hostiles with speed ≥ 15 within 6 count as near even when their square isn't reachable, so Elbereth waits, retreat and flee_up apply to them.

## Black unicorn in Sokoban (run 173635, Dlvl 5, XL5, T3549)
- Cause: a hostile black unicorn in Sokoban. Jev waited ~20 turns near it, then walked toward it for a boulder push. Sokoban levels block teleporting ("A mysterious force prevents the black unicorn from teleporting!"), so the cornered unicorn (speed 24, butt 1d12 + kick 1d6) fought: 46 -> 27 in one turn. Elbereth garbled, 4 potions, and prayer was spent at T3472.
- Wiki (Unicorn): it keeps out of line with you and flees; cornered, it is one of the deadliest early melee monsters. Don't chase or corner it.
- Fix: in Sokoban, a hostile unicorn 2-6 squares away → leave by '>' (only pray/quaff stay open) and don't re-enter Sokoban for 300 turns.

## Soldier ant (run 173904, Dlvl 8, XL7, T7557)
- Cause: Jev fainted from hunger and prayed (T7501), and a soldier ant arrived. Elbereth made it flee and hover nearby (speed 18). Jev left the square to open doors at 69/69 (bitten to 45). At 49/69, just above the 70% wait threshold, it left again to kick a door: booby-trapped, stunned, the ant returned. Elbereth garbled, 34 -> 5 in one turn, dead.
- Wiki (Soldier ant): you can't outrun it; Elbereth works; never leave Elbereth while it is around unless you can kill it.
- Fix: a stronger hostile with speed ≥ 15 nearby → stay on Elbereth (wait offered at any HP, explore/goto/fetch/pickup dropped) until camped (40 of 50 waits at ≥60% HP), so fights still happen eventually.

## Werejackal after a nymph strip (run 174612, Dlvl 5, XL4, T3162)
- Cause: a wood nymph on Dlvl 4 stole 12 items over 2000 turns (shield T888, spear T2928, rings, potions, wand). leave_nymph required Dlvl ≤ XL, and Jev was XL3 on Dlvl 4, so it never fired until XL4. Then the walk to '>' stopped at every monster coming into view (~100 turns to leave). On Dlvl 5, with an empty pack at AC 10 and bare-handed, a werejackal pack killed it.
- Wiki (Nymph): she teleports away after each theft and comes back; leave the level (she only follows if adjacent) or kill her on sight.
- Fix: leave_nymph uses '<' when '>' would break the pace rule, and walks without stopping for newly seen monsters.

## Soldier ant while fainting (run 174940, Dlvl 7, XL6, T8693)
- Cause: hunger. Jev prayed for hunger 5 times in 8700 turns and ate only 3 corpses, despite dozens of kills with a corpse nearby. The prayer at T8646 (830 turns after the last) didn't fix Weak; it fainted mid-fight with a soldier ant.
- Found: corpse tracking only dates squares showing '%'. A kill whose square also holds dropped items (arrows, weapons) shows ')' or '[', so the corpse got 'unknown age = rotten' and was never offered (T7158: standing on a fresh giant ant corpse under 11 orcish arrows, no eat option).
- Wiki/eat.c: corpses under 50 turns old are safe (rot = age/(10+rn2(20))).
- Fix: a melee kill whose square shows a non-'%' object is recorded as a fresh corpse; goto_corpse already drops the entry if none is there.

## Hill orc, praying (run 180002, Dlvl 4, XL6, T4402)
- Cause: just after a hill orc band fight, at 24/45, goto_corpse was forced (it overrides rest) and the walk met the next orc: 24 -> 13, Elbereth garbled, 3 HP, prayed only 158 turns after the last. The previous fix (dating corpses under items) makes more corpses eligible, which made this path more likely.
- Wiki: corpses keep for ~50 turns; heal first.
- Fix: no goto_corpse below 60% HP or within 10 turns of being hit, unless Weak/Fainting.

## Rabid rat, blind and helpless (run 20261001-180329, Dlvl 6, T4302)
- Cause: Weak at T4171, carrying only a tripe ration, nothing in view. The bot prayed, because the T3736 rule strips tripe whenever a safe prayer is on offer. At T4189 it killed a yellow light and was blinded. At T4297 an unseen rabid rat started biting: 38 -> 11 HP. Prayer was only 131 turns old, so the bot drank an unknown black potion and was left helpless.
- Wiki/source: tripe makes a non-orc vomit 1 time in 2 (eat.c), and the confusion and stun only arrive near the end of the vomiting countdown. With nothing in view that costs little. A prayer costs a timeout of about 350 turns or more.
- Fix: when Weak, not in fatal trouble or at low HP, with no hostiles in view and any food (including tripe) on offer, drop the hunger prayer and eat, keeping the prayer for emergencies.

## Mountain centaur while fainting (run 20261001-180548, Dlvl 8, T8599)
- Cause: the bot had no packed food and had prayed 7 times, mostly for hunger. At T8379 it killed a carnivorous ape that had been holding it, and was left Hungry at 38/93 HP. The new goto_corpse HP gate (from the hill orc death) dropped the step onto the fresh corpse one square away, and the bot rested instead. The corpse went stale. At T8455 it prayed while Fainting, 449 turns after its last prayer, and Tyr was displeased. It fainted repeatedly, and a mountain centaur killed it.
- Wiki/source: a corpse is safe below 50 turns old (eat.c rotted = age/(10+rn2(20))). The bot's own kill is the only reliable food source.
- Fix: the HP and recent-hit gate on goto_corpse no longer applies when a fresh corpse is 2 or fewer steps away; one step costs nothing. Still open: when the bot turned Weak at T8395 no corpse walk was offered at all (cause not found from the log).

## Killer bee while fainting after 20 hunger prayers (run 20261001-181729, Dlvl 6-7, T20037)
- Cause: run['recent'] only changes when a new message arrives. A stale "The lizard bites!" (or "It bites!") therefore kept unseen_attacker() true with no monster in view and HP rising. find_unseen was chosen about 3600 times on one Mines level, so the bot made no progress and burned food. It prayed 20 times for hunger in 20000 turns, then fainted beside a killer bee.
- Wiki: an invisible attacker reveals itself by attacking; searching once marks it with an I. With no new hit, nothing is there.
- Fix: record the turn of the last message (msg_turn). unseen_attacker() is false when the last message is more than 2 turns old. Covered by a test in test_corpse.py.

## Dingo while fainting (run 20261001-185114, Dlvl 7, T7450)
- Cause: chronically short of food. The bot carried no food at all by T7000 and had prayed for hunger 5 times. The fifth prayer, while Weak at T7042 and 936 turns after the last one, drew "Thou art arrogant" (the timeout had not expired: rnz(350) is heavy-tailed, roughly a 6% chance). The bot lost a level, fainted, and a dingo killed it. Meanwhile it had killed 33 giant bats and eaten none, because 'bat' is in NEVER_EAT.
- Source: eat.c makes a bat corpse stun you for 30 turns and a giant bat for 60. There is no poison and no other harm.
- Fix: bat corpses are now edible (run['calm']) when the bot is Hungry or worse and nothing hostile is in view; stun handling already makes it rest in place. Bat kills are now dated as fresh corpses. Vampire bats are still banned through 'vampire'.

## Leocrotta + tiger (run 20261001-185848, Dlvl 8, T8476)
- Cause: the bot was resting on the '>' at 56/66 when a tiger at its own level showed up 3 steps away. It stepped off the stairs to close in. A leocrotta (speed 18, three 2d6 hits) joined, and the two took 56 -> 47 -> 27 -> 0. The stairs were one step away, but the only escape the bot ever offered was '<'.
- Wiki (Stairs, Fleeing): fight beside or on the stairs, so you can leave when a fight turns. Only adjacent monsters follow you.
- Fix: no 'approach' toward a monster that isn't weaker while the bot stands on '<' or '>'; it waits and lets the monster come. New 'downstairs' option: on '>' with danger, strong, pack or duo, and no up escape, flee down. It counts as a hop for the ping-pong guard, and attack/approach/explore are filtered as with upstairs when the threat is strong or a pack.

## Death ray from an unseen zapper (run 20261001-190539, Mines 7, T8536)
- Cause: "You hear a chugging sound" (a monster drank a potion, likely invisibility), then "You hear a nearby zap. The death ray whizzes by you!". The bot took this for an unseen melee attacker and searched in place with find_unseen, and the next ray killed it. It had no magic resistance or reflection.
- Wiki (Wand of death, Ray): a ray travels in a straight line; Elbereth does not stop wands. Without MR or reflection, the only defense is to leave the line or the level.
- Fix: for 2 turns after "whizzes by you" or "You hear a nearby zap", offer 'dodge': take stairs on or within 8 steps of the bot, else step to a random free neighboring square. Everything except dodge, pray, attack and quaff is dropped.

## Hill orc's wand of striking on Elbereth (run 20261001-191134, Dlvl 6, T2894)
- Cause: the bot sat on an Elbereth it had engraved on '<'. A hill orc that had fled from the engraving zapped a wand of striking at it: 43 -> 21, then a re-engrave, then 14, then dead. With the orc no longer in 'near', 'upstairs' was rarely offered, and when it was, the model chose wait.
- Wiki (Elbereth): it never stops wands or missiles.
- Fix: when shot or zapped while standing on '<' below 70% HP, the options become upstairs, pray, attack and quaff only.

## Ape among a fire ant and a plains centaur (run 20261001-191409, Dlvl 7, T6191)
- Cause: on Elbereth at 37/84 the bot was offered a charge at the plains centaur shooting at it (the "kill a weak shooter" rule), while an ape and a fire ant were within 3 squares. It stepped off and took hits. It then swung at a grid bug with the ape adjacent, quaffed an unknown potion (object detection), charged again at 20/84, and died.
- Wiki (Elbereth): stepping off gives every nearby monster free hits; a shooter is worth charging only when it is alone.
- Fix: the shooter charge at low HP is offered only when no other non-passive hostile is within 3 squares. Grid bugs, newts and lichens join the "don't swing at it while something real is adjacent" list.

## Gargoyle (run 20261001-191837, Dlvl 5, T12980)
- Cause: at 52/103 a gargoyle (AC -4, three attacks for up to 28 a turn) was offered as an 'approach' target, because the approach gate only blocks 'stronger' monsters and HP below half. The bot alternated approach and retreat 4 times, then took 53 -> 27 in one turn. Elbereth came out garbled, and two unknown potions and an unknown wand didn't save it.
- Wiki (Gargoyle): its hits are hard and its AC is very low; only fight it healthy, and Elbereth stops it.
- Fix: no approach toward an 'about your level' monster below 2/3 HP, which is the same threshold the monster's own fight rule gives. The bot waits and lets it come, keeping its Elbereth/retreat options.

## 2026-10-01 — bolt of fire, Woodland-elf, Dlvl 8 T8764 (run 20261001-193021)
- **Cause:** the bot arrived on Dlvl 8 into soldier ants, an ogre, an elf mummy and a Woodland-elf with a wand of fire. Its flee_up was interrupted after 1 step and its Elbereth came out garbled. At 23/62, with 4 monsters adjacent, every option was filtered away, so the empty-options fallback chose "Search 10 turns" and the fire bolt killed it.
- **Wiki:** soldier ants are the top killer. You should get out (stairs or teleport), and you should never stand idle while they are adjacent.
- **Fix:** when the fallback is reached with adjacent hostiles, it now offers melee on them instead of searching. Not yet found: which filter emptied the options. The fallback logs a warning, so the next occurrence can be traced.

## 2026-10-01 — fainted, iguana, Dlvl 2 T9979 (run 20261001-193731)
- **Cause:** the bot spent 9000 turns on Dlvl 1-2 and never found '>'. The only way on was a locked door at (75,6). A cash-register chime had marked Dlvl 2 as "town", no for-sale item had been seen and there was a fountain on the level, so the kick was vetoed 20 times. The bot lived on prayers until one failed, then fainted and was killed.
- **Wiki/source:** in dokick.c, breaking a door is only punished when it is the shop's own door, or anywhere in Minetown (the watch). A fountain only signals Minetown when you are in the Mines.
- **Fix:** outside the Mines, the town veto now lapses after 5 refusals on a level, and the bot kicks. The "Closed for inventory" sign check still applies. Kicks next to a for-sale item are still refused.

## 2026-10-01 — soldier ant, Dlvl 5 T2653 (run 20261001-194404)
- **Cause:** the bot was at XL4 and full HP, waiting on Elbereth beside a soldier ant rated "much stronger". The ant stepped out of view and the bot left the engraving to fetch an item. The ant came back and the bot ran 12 steps for '<' (the ant has speed 18, the bot 12). Two Elbereths came out garbled, a prayer healed it, and the melee killed it anyway.
- **Wiki:** soldier ants are the top killer, and you can't outrun one. Elbereth works against them, so stay on it.
- **Fix:** once a "much stronger" monster has been within 7 squares, the stay-on-Elbereth rule now holds for 20 turns, even at full HP and even when the monster is out of view.

## 2026-10-01 — sewer rat while praying, Dlvl 3 T1583 (run 20261001-194523)
- **Cause:** at 10/50 HP, beside a wererat in animal form and the rats it had summoned, the bot was offered both Elbereth and a gamble prayer. The last prayer had been 144 turns earlier. Jev chose the prayer (p 0.52); it failed and the rats killed it mid-prayer.
- **Wiki/source:** the prayer timeout after a successful prayer is rnz(350), so praying under ~200 turns later usually fails. Animal-form weres and rats respect Elbereth, and a dust Elbereth comes out legible about 72% of the time.
- **Fix:** when Elbereth is offered and the last prayer was under 200 turns ago, the gamble prayer is removed.

## 2026-10-01 — plains centaur, Dlvl 7 T5097 (run 20261001-194640)
- **Cause:** the bot had waited on Elbereth for 40+ turns and was at 36/59 HP. The "camped" release (60% HP) allowed attacks again, so it hit a giant rat off the engraving with a plains centaur and a fire ant nearby (both speed 18). Its next Elbereth came out garbled and it went from 37 to 0 in 2 turns.
- **Wiki:** you can rest on Elbereth until healed against monsters that respect it. Attacking from it erases it.
- **Fix:** with any non-weaker hostile within 5 squares, the camped release now needs 85% HP (it stays at 60% otherwise).

## 2026-10-01 — plains centaur, Dlvl 8 T3823 (run 20261001-195058)
- **Cause:** at XL4 the bot fell down a trap door from Dlvl 5 to Dlvl 8. A plains centaur (speed 18) caught it at 41/49 HP and its Elbereth came out garbled. Because it had lost HP while engraving, it was barred from engraving for 5 turns. That left melee as the only option, and it died.
- **Source:** mhitu.c never wipes engravings. Wipes only come from your own melee, throws and kicks, and from rare random wear. A garble is the 1/25-per-letter typo, so a retry is a fresh ~72%.
- **Fix:** the block now applies only after a second garble within 3 decisions, so one retry is allowed first.

## 2026-10-01 — hill orc band, Sokoban Dlvl 5 T3736 (run 20261001-195333)
- **Cause:** a mountain nymph stole the +3 shield, taking AC from 5 to 9. An unknown wand zapped at it turned out to be polymorph (it became a violet fungus). The fungus panic-attacked the bot on Elbereth, so it stepped off. At 14/41, with a hill-orc band 2-4 squares away and Elbereth on offer, Jev threw darts instead. The next Elbereth, with orcs adjacent, was interrupted and the bot died.
- **Wiki:** engrave Elbereth before a pack reaches you. In 5.0, engraving is an occupation and an adjacent attacker interrupts it.
- **Fix:** below 40% HP, with 2+ non-passive hostiles within 4 squares and none adjacent yet, the options are narrowed to Elbereth, prayer, stairs and potions.

## 2026-10-01 — plains centaur, Dlvl 7 T5761 (run 20261001-195705)
- **Cause:** the bot was waiting on an intact Elbereth in a crowded room at 28/74. A plains centaur was adjacent, boxed in by hill orcs, and hit and kicked it from 28 to 9 in one turn. Its prayer had been used 33 turns earlier, and it died the next turn.
- **Source:** in monmove.c, when Elbereth scares a monster and m_move returns MMOVE_NOMOVES, the monster panic-attacks. A cornered monster attacks every turn, Elbereth or not.
- **Fix:** a "boxed" monster is now detected: an adjacent hostile whose free neighbour squares are all next to the bot. While one is present, the forced wait on Elbereth is off, and attacks from Elbereth stay offered so the bot can kill it or move.

## 2026-10-01 — stuck "feeling around in the dark", then fire ant on Dlvl 5 T11560 (run 20261001-200412)
- **Cause:** a loop of leave_nymph down to Dlvl 5 (a room full of monsters), then upstairs straight back. fled_up blocks '>' for 50 turns and Dlvl 4 was fully explored, so no options were left. The "feel around in the dark" fallback then took thousands of random single steps beside the stairs. The user reported the bot as stuck. It went back down eventually and died to a fire ant while praying.
- **Fix:** with no options and a flight up within the last 50 turns, the bot now rests for 20 turns.

## 2026-10-01 — gargoyle, Sokoban Dlvl 7 T9530 (run 20261001-201806)
- **Cause:** the forced soko_push filter only stood down while hostiles were in view and HP was under 60%. The gargoyle (speed 10, up to 28 damage a turn) kept stepping out of view. Each time, a push became the only option, at 20/57 and then 10/57, and each one walked the bot off its Elbereth. It died on the last push.
- **Fix:** pushes are forced only at 60% HP or more. Below that, rest, Elbereth and the other options stay available.

## 2026-10-01 — rothe in the Mines, Dlvl 5 T3492 (run 20261001-202507)
- **Cause, part 1:** the main '>' on Dlvl 4, the Mines branch level, wasn't found within 500 search turns. stuck_main then opened the Mines at XL5, and the bot ping-ponged Dlvl 4↔5 about 30 times. The user flagged it: the plan was no Mines until XL 10.
- **Cause, part 2:** the bot put on a towel against a yellow light, and the towel was cursed. 'unblind' tried 'R' thousands of times on T3457, then a rothe killed the blind bot.
- **Source:** pray.c lists TROUBLE_CURSED_BLINDFOLD as major trouble (1), so a safe prayer uncurses it.
- **Fix:** MINES_XL is now 10. stuck_main now needs 1500 search turns, since the main '>' always exists and is just hidden. A worn cursed towel or blindfold is fixed by prayer (more than 1000 turns since the last one); otherwise 'unblind' isn't offered.

## 2026-10-01 — werejackal, Dlvl 4 T6987 (run 20261001-203017)
- **Cause:** at T6120 a werejackal bite turned Jev into a jackal, and its spear, shield and helm fell off. After the prayer cure, recover_gear walked to the recorded spot. The spot was one step off the real pile and the square was empty, so gear_at was cleared and Jev descended with the ')' one step away. It met the werejackal again at AC 9 with no weapon; the werejackal summoned jackals and a coyote, and they took it from 59 to 0 in 7 turns.
- **Fix:** when Jev reaches the gear spot and finds nothing there, it now retargets the nearest ')' or '[' within 3 squares instead of giving up.
- **Also (transcript strategies, source-checked):**
  - The blindfold is no longer disabled by telepathy. uhitm.c's passive paralysis needs canseemon, and display.h says that needs actual sight, so blind is always safe from a floating eye.
  - The donate text now matches priest.c in 5.0: base = peak XL × 150-250, offer the larger suggested sum (2× base), first purchase gives 2-4 AC.

## 2026-10-01 — strategies from "NetHack overexplained" (3.6.7), checked against 5.0
Each change below was checked against the 5.0 source:
- **Taming with food:** throw food at a hostile kitten, housecat, large cat, dog or horse instead of fighting it. befriend_with_obj (mondata.h) plus tamedog (dog.c) make it peaceful at worst. Horses only accept veggy food. The throw is forced unless a non-domestic monster is within 2.
- **Unicorn horn:** apply it for stun, confusion, hallucination or blindness (apply.c). In 5.0 it no longer restores lost attributes.
- **Stoning:** keep one lizard corpse (it never rots, eat.c), and eat it only when Fainting. When stoning starts, eat the lizard or an acid blob corpse, or quaff acid, before using the prayer (fix_petrification).
- **Lycanthropy:** quaff holy water before praying. Lawful heroes get "You feel full of awe" and you_unwere (potion.c peffect_water).
- **Spheres:** monster tips added. Explosions destroy wands and rings (shock) and scrolls and potions (fire) via explode.c destroy_items.
- **Not done:** Excalibur (operator rule), and priest protection, which is already 5.0-correct.

## 2026-10-01 — warg while asleep, Dlvl 7 T6060 (run 20261001-203449)
- **Cause:** a werewolf in @ form with a wand of fire zapped Jev 3 times (49 → 36 → 18). Only the first bolt, a miss, triggered 'dodge', which is limited to "whizzes by" from an unseen zapper. On the next turns, below half HP, the only option was exploring 1 step, which kept Jev in the ray's line. The werewolf then summoned wolves and a warg. A prayer at 6/77 restored HP, but the pack plus another fire bolt took it to 7. An unknown potion turned out to be sleeping, and Jev died.
- **Fix:** when a visible monster that is zapping is in line (row, column or diagonal), offer a step to a square off every line to it. Rays only travel in the 8 directions (zap.c buzz). Below half HP this step is forced when nothing is adjacent.

## 2026-10-01 — more transcript strategies (Mines/Sokoban part), checked against 5.0
- **#enhance:** weapon.c prints "You feel more confident in your weapon skills" when a skill can be advanced. Jev never ran #enhance, so its spear stayed at Basic. It now advances the wielded weapon's skill, otherwise the first skill offered, using the 5.0 menu format "x - name [Level]".
- **Orcish Town:** one of the Minetown variants (minetn-1.lua) has dozens of orcs and no temple. Five or more hostile 'o' in view on Minetown depth or deeper marks it. Jev then heads back up, and the Mines stairs on the branch level are skipped for the rest of the game.
- **Skipped:** Sokoban-top giant mimics and the zoo (Sokoban is already scripted), holes as an escape, and burned or dug Elbereth.

## Choke with a crowd adjacent; held by an owlbear (T11430, T12770)
- User screenshot: in a room corner on Dlvl 5 with an owlbear, gremlin, lizards, goblin and h around, Jev sat on garbling Elbereth for 100+ turns (61 -> 21) with a doorway 1 step north. Choke was only offered when no monster was adjacent (gap >= 2). Now with 3+ in the pack and HP >= 50%, a corridor/doorway square within 2 steps is offered, and attack/wait/explore are dropped in favor of it.
- Run 20261001-203850 died to that same crowd (by a snake): it went back down to Dlvl 5, the owlbear grabbed it, and it chose '<' 4 times ("You are being held, and cannot go up"), 82 -> 0. "You are being crushed" now counts as held, and the held filter (attack/Elbereth/pray/quaff/zap only) lasts 2 turns, not 1.

## User notes: vortex, Sokoban mimics, burned Elbereth, less Elbereth (2026-10-01)
- **Energy/fire vortex:** monsters.h gives both a passive AT_NONE shock or fire attack ((level+1)d4, 7-28 for an energy vortex) on every melee hit. Thrown missiles never trigger passive(). When engulfed by one, Jev now throws daggers or darts instead of meleeing.
- **Sokoban mimics:** soko1-*.lua places two giant mimics disguised as boulders. 5.0 premaps the real boulders, so the '0's on first sight become the boulder set, updated on each push. Any extra '0' is logged as a mimic and left out of replans. It is attacked with F only at XL 10+ and 80% HP.
- **Burned/dug Elbereth:** if a wand of fire or digging is known and charged, Jev engraves with it. engrave.c only makes typos for DUST and BLOOD, and wipe_engr_at never erodes BURN. Attacking from any Elbereth still erases it (mon.c setmangry).
- **Less Elbereth:** if Elbereth was chosen 4+ times in the last 12 decisions and HP is no higher than 12 decisions ago, the Elbereth and stay-on-Elbereth options are dropped whenever an attack, choke, stairs, retreat, zap, throw, quaff or pray option exists.
- **Shop mimics:** in 5.0, set_mimic_sym makes shop mimics copy the shop's own goods, so any item can be one. shop_look and shop_food now step one square at a time. Before each step, Jev searches once if any adjacent item square hasn't been tested yet; dosearch0 → mfind0 → seemimic always unmasks an adjacent mimic. At AC > 0, attack and approach options on a hostile mimic are dropped unless Jev is stuck to it. Mimics have speed 3, so walking away works.
- **Peeking down stairs:** this already happens. A pack or a much stronger monster on arrival forces '<' (the "arrived into 3 wolves" fix).

## 2026-10-01 — quasit's wand of fire, Dlvl 10 T15223 (run 20261001-205205)
- **Cause:** a quasit with a wand of fire waited near the Dlvl 10 upstairs. Jev fled up at T15174 and rested, then came back down 50 turns later. Standing on '<' in the quasit's line, it took 'find_unseen' (search) twice at 55/x instead of the offered 'dodge' or 'upstairs', since the quasit flickers invisible. It went 55 -> 33 -> 0.
- **Fix:** a visible zapper in line now narrows the options to dodge, upstairs, pray, quaff, zap and attack at any HP, not only below 50%.

## 2026-10-01 — fainted beside a floating eye, Minetown Dlvl 6 T7682 (run 20261001-210301)
- **Cause:** Jev stood in the corridor outside Minetown's NW wall. A floating eye in the 1-wide corridor south blocked the only way back to '>', and Jev held 16 darts. It still searched for hidden passages for 1300 turns, Hungry → Weak → Fainting, living on prayers until a hill orc killed it. Throwing at the eye was offered once. Every other time, the `shop` flag removed all throw and zap options, because shop squares it had stood on earlier were within Chebyshev 7 *through the town wall*.
- **Fix:** shop proximity now uses walking distance (dijkstra ≤ 7), not Chebyshev distance.

## 2026-10-01 — tainted newt corpse, Dlvl 9 T10532 (run 20261001-210838)
- **Cause:** at XL 8, AC -1, Jev killed an invisible quasit and went to eat the corpse while Not Hungry. An old newt corpse was on the same square, and eat.c floorfood asks about each corpse in pile order. Jev answered 'y' to the first prompt, which was the newt: "Ulch - that meat was tainted!", FoodPois. The prayer came too soon, so Tyr was displeased, and Jev then ate the quasit while sick and died.
- **Fix:** kills are recorded from "You kill/destroy the X!". The floor-eat prompt loop now answers 'y' only to a corpse species killed in the last 30 turns (lichens and lizards never rot), and 'n' to every other prompt.

## 2026-10-01 — jaguar while fainted, Dlvl 6 T10134 (run 20261001-211538)
- **Cause:** Jev was Weak with no food, 357 turns after a low-HP prayer, and kept walking toward stairs for leave_nymph. The Weak prayer threshold was 1000 turns. In eat.c newuhs, Weak covers uhunger 1-50, and moving from Weak to Fainting faints at once (`u.uhs <= WEAK`), so the Fainting threshold (300) only applies after the first faint. Jev fainted mid-fight with a jaguar and died.
- **Fix:** Weak with no food in the pack now prays at 300 turns, like Fainting (P ≈ .66 that the timeout is under 200).
- **Pattern:** 3 of the top 5 scores died "while fainted from lack of food". The food supply is the main thing still wrong.

## T6106 goblin, fainted (Dlvl 4)
Out of food, Weak at T5669: prayed 828 turns after the last one ("Tyr is displeased"), then picked "search for hidden passages" over a locked door 2 steps away ~30 times (51/49 split) while Fainting, with a **wand of digging** in the pack. The wand was only offered as an HP emergency. Fix: with no food and Hungry or worse, the wand's dig-down is offered whenever no downstairs is known and nothing is near; searching/resting is dropped whenever a door, kick, explore or dig option exists. A new level means new corpses.

## T7613 starved, boxed in (Sokoban, Dlvl 5)
A nymph had taken all but one item on Dlvl 6. In Sokoban a monster read a scroll of earth, and the boulders landed around Jev in a 3-square corner. No diagonal pushes in Sokoban, so there was no way out. The T5636 prayer ("well-pleased") fixed only the worst trouble (HP). The bot didn't know it was trapped and searched walls for 2000 turns. A Weak prayer 504 turns later angered Tyr, so it starved. Fix: 8 rock/wall/boulder neighbours (pray.c stuck_in_wall) now count as prayer trouble on the normal timeout.

## T3916 giant ant (Dlvl 7, XL4)
The wand of digging was empty. Engraving with it gave "The wand is too worn out to engrave", which the bot read as "attack interrupted" and retried 18 times beside a water nymph. It then zapped the wand at the nymph 4 times (a horizontal dig only bores walls), and at 14 HP it "dug down" with it for nothing. Fix: "too worn out" marks the wand empty, which every wand option already respects. Known digging wands are no longer offered as attack wands.

## T7048 soko4: stuck on two stacked boulders, ignoring "exit sokoban"
- A replanned solution pushed a boulder onto another in the doorway column; every push after that went "in vain". The repeated message was deduped out of `news`, so the -99 replan flag never fired and the bot looped on push/wait. Because soko_push was the only option, the operator's "exit sokoban" order never reached a choice.
- Fix: three failed pushes at the same step count as stuck. If no replan exists and the bot has a pick-axe or mattock, it offers to break the boulder, once per level (5.0 dig.c fracture_rock -> sokoban_guilt: Luck -1, which recovers 1 per 600 turns). Prayer is withheld for 600 turns per break, because with Luck < 0 a prayer fixes nothing. Without a pick it gives up the level. A standing order matching "exit/leave/skip … sokoban" sets soko_done.

## T9944 owlbear, Dlvl 9
- Met an owlbear in melee at 51/94. Its claws plus hug took 6, 13 and 18 HP. Once held, Elbereth failed with "cannot reach the floor": in 5.0 engrave.c, can_reach_floor is FALSE when stuck to an AT_HUGS monster. Escape was impossible too. At 14/94 the bot was not in prayer trouble (14×7 > 94), so it quaffed an unknown potion and died.
- Fix: when an AT_HUGS monster (owlbear, python, rope golem, couatl, salamander, kraken, pit fiend, carnivorous ape, guardian naga) is within 3 squares, HP is below 75%, and the bot is not already held, it offers Elbereth before contact and drops attack, approach, wait and rest.

## T9310 barrow wight, fainted, Dlvl 9
- A nymph stole on Dlvl 10, where the downstairs was unknown. leave_nymph went up '<'. On Dlvl 9 the pace rule (dlvl ≤ XL) sent it straight back down, and the loop ran for about 400 turns while the bot was Hungry with no food. It prayed while Weak 852 turns after the previous prayer: "Tyr is displeased" (p_type 0, too soon). It fainted beside a barrow wight.
- Fix: never leave a nymph level by '<'. When the downstairs is unknown, the existing branch explores for '>' instead.

## T10632 owlbear, while sleeping, Dlvl 6
- The bot stood in a doorway on Elbereth at 66/88 HP. A jaguar and an owlbear fled from it. It then picked "close in on jaguar", and from the doorway the only step south was a known '^' trap. The trap put it to sleep and the owlbear killed it.
- Fix: no approach option whose first step lands on a known trap. The monster comes to us anyway.

## T12125 scorpion, while praying, Dlvl 10
- Cause: a scorpion stood next to Jev in a dead-end corridor. monmove.c: a scared monster with no square to flee to sets `panicattk` and attacks anyway, so Elbereth did not stop it. Jev alternated "engrave" and "attack". Each attack erased the engraving, and each engraving gave the scorpion free stings (33 -> 16 -> 6 HP). Then Jev prayed 310 turns after the last prayer (too soon) and died.
- Fix: do not offer Elbereth when an adjacent hostile is boxed in (floating eyes excepted). Jev fights or retreats instead.

## T4379 giant mimic, Dlvl 4
- A giant mimic in a shop stuck to the bot ("You cannot escape from the giant mimic!"). The "walk away from the slow monster" rule replaced all options with 'retreat'. The bot tried to retreat 6 times and did not move, 62 -> 0 HP.
- monmove.c: monflee() calls release_hero(), so a mimic that Elbereth scares lets go.
- Fix: while held, the slow-monster rule does not apply, and no retreat or flee option is offered. Elbereth and attack stay.

## T4640 owlbear, Dlvl 4
- The bot came down to Dlvl 4 into a room with an owlbear, a pudding and molds. The owlbear was 2 squares away and the bot stood on the upstairs, with 'upstairs' offered. It picked wait, then 'choke', which walked it off the stairs. The owlbear hugged it: 65 -> 30 HP in one turn. Engraving failed while held, and two zaps of an unknown wand did nothing. Dead.
- Fix: on the upstairs with a hugger (AT_HUGS) within 3 squares and not held, the only option is 'upstairs'.

## Mimic memory (user note)
- User: you can walk away from a found mimic (speed 3), but it can follow you and hide again. The "new" item on the way back is probably the mimic.
- Fix: each level remembers every square where a mimic was seen. Object glyphs within 2 squares of those squares go into `avoid`, so the bot does not path through them.

## T4486 wererat, fainted, Dlvl 4
- The bot went down the Mines branch to Mines Dlvl 4, came back, and later took the main '>' to main Dlvl 4. `in_mines()` only checks if the Dlvl number is in `mines_dls`, and the set only grew. So main Dlvl 4 counted as the Mines, and the Mines XL cap said "far too deep" each time. The bot went 3 <-> 4 about 50 times (the giant mimic game showed the same loop).
- That burned the food. It prayed for hunger at T1235, T2298 and T3149. The fourth prayer, at Weak 1003 turns after the third, was too soon (pray.c p_type 0, "Thou art arrogant"). Then it fainted beside a wererat.
- Fix: when ^O overview says that the hero is not in the Mines, remove that Dlvl from `mines_dls`.

## User early-game tips (chests, pickups, keys, vaults)
- Boxes: `act_loot` unlocks with a key or lock pick (5.0 autounlock asks "Unlock it with ...?"). Else it wields a dagger with a known BUC, uses #force (a blade pries), and wields the main weapon again. Else it kicks the box from an orthogonal square. It stops when a kick does not give "THUD!", because the box opened or slid away (dokick.c), and kicking an empty square strains a muscle. The main weapon is never used to force.
- Pickups: no gems, stones or random weapons. Daggers up to 3, a pick-axe, a luckstone and named artifacts are allowed. A key, lock pick or unicorn horn is the only option when no hostiles are in view. Shops price them as worth buying.
- Watch: lock.c/monmove.c watch_on_duty counts any unlocking tool on a locked town door as picking. The bot already leaves watched town doors shut.
- Level notes: a vault sound (sounds.c: counting gold coins, guard footsteps, Ebenezer Scrooge), a known altar, or a stash adds a note. The bot writes the notes with `#annotate`.
- Not done yet: the vault raid with a pick-axe, hunting cross-aligned unicorns, BUC tests with a pet, and selling weapons for gold.

## T10457 chameleon (as a Grey-elf), Dlvl 10
- XL 8, AC 2, 84 max HP. A quasit, an elf zombie and a chameleon that looked like a Grey-elf (an @ ignores Elbereth) attacked together. Elbereth did not protect it. 'flee_up' toward a '<' a few steps away stopped twice with "a monster came into view". The bot then fought three monsters, 25 -> 0.
- Fix: 'flee_up' does not stop for monsters that come into view.
- Also: this game prayed 7 times in 10457 turns, most of them for hunger. Food stays the main weakness.

## T5086 werejackal, while praying, Dlvl 5

- Cause: A werejackal, its jackals, a giant ant and Mordor orcs mobbed Jev in a doorway at 27/76 HP. From 17 HP, Jev got only attack options. The scorpion fix (T12125) removed Elbereth when an adjacent monster was "boxed". In a crowd, the other monsters box each adjacent monster, so Elbereth was never offered. At 3 HP, a prayer 101 turns after the last one failed.
- Prevention: Elbereth scares the monsters that can flee. When they flee, they open squares for the boxed one.
- Fix: `jev/bot.py` removes the Elbereth option for a boxed monster only when the boxed monsters are all the monsters that are near.

## T13186 Grey-elf, while praying, Dlvl 8

- Cause: A leocrotta took Jev from 94 to 15 HP in 3 turns. A potion and Elbereth brought it to 18 HP. Then a Grey-elf came adjacent. A Grey-elf ignores Elbereth. Jev got only two options: zap an unknown wand, or walk 15 steps to `<`. It walked. The Grey-elf (speed 12) hit it on each step, 18 -> 8. The prayer failed because Jev prayed for hunger 350 turns before.
- Prevention: Do not walk away from an adjacent monster that is as fast as you. It gets a free hit on each step. Fight it, or use an item.
- Fix: `jev/bot.py` removes `flee_up` when an adjacent monster has speed 12 or more and `<` is more than 3 steps away. The attack options stay.
- Open problem: Jev prayed for Weak hunger 5 times in this game, so prayer was never ready for low HP.

## T3026 starvation, Dlvl 3

- Cause: Jev put on unknown "riding boots" that had no known BUC. They were cursed -1 levitation boots. Jev could not reach the stairs or the floor. For 1400 turns, it got only "take off the boots" (which fails on cursed boots) and "search". It never prayed. Weak, then Fainting, then starved.
- Source: in pray.c, `TROUBLE_CURSED_LEVITATION` is major trouble. A prayer removes the curse.
- Prevention: Boots, gloves and helmets with an unknown appearance can be levitation, fumbling or opposite alignment. Wear them only with a known BUC (the policy of the user).
- Fix: `jev/bot.py` counts worn cursed levitation as trouble and offers only the prayer instead of "take it off". The wear option now needs `uncursed` or `blessed` for unknown-appearance boots, gloves and helmets.

## T2578 hill orc, Dlvl 5

- Cause: A wood nymph stole the spear, the plate mail and a helm. Then a werejackal bite turned Jev into a jackal. The filter for random weapons (from the tips of the user) blocked the pickup of all weapons except daggers. Jev walked over 2 scimitars and fought hill orcs bare-handed, 34 -> 0.
- Prevention: The rule against random weapons is for a Valkyrie that has a weapon. With no weapon, any weapon is better than bare hands.
- Fix: `jev/bot.py` permits a weapon pickup when the pack has no weapon, and makes it a priority option. The existing wield rule then wields it.

## T7927 soldier ant, Dlvl 7

- Cause: Jev waited on Elbereth at 22/53 HP. A soldier ant (speed 18) fled out of view. After 10 turns with no monster in view, the Elbereth wait stopped, and Jev chose a 15-turn rest. The ant came back and took 22 -> 11 in one turn. An engraving try was interrupted, and the ant killed Jev.
- Prevention: A fast monster comes back faster than HP comes back. Stay on Elbereth until HP is high, also when the fast monster is out of view.
- Fix: `jev/bot.py` sets `scary_turn` for a monster with speed 15 or more that is not weaker than Jev. The Elbereth wait then continues for 20 turns after the monster goes out of view.

## T363 boulder, Dlvl 2

- Cause: At XL 1, a rolling boulder trap took Jev from 18 to 6 HP. Jev rested to 10/18. Then the gold rule made "fetch the gold" the only option, because HP was more than half. On the way, a second rolling boulder trap killed Jev.
- Prevention: With a low maximum HP, one trap or one hit can kill. Rest to 3/4 HP before you walk for an item that is not necessary.
- Fix: `jev/bot.py` forces `fetch_gold` only at 3/4 HP or more when `rest` is on offer.

## T7304 Uruk-hai, Dlvl 4

- Cause: Jev was at AC 10 with no armor. Uruk-hai shot poisoned arrows and came adjacent. Jev chose `flee_up` 6 times. Each time, an Uruk-hai blocked the path after 1 step, and it hit Jev for free. HP fell 31 -> 0. The armor loss near T6400 has no clear message in the log.
- Prevention: If a monster blocks the path to the stairs, fight it. Do not try the same walk again.
- Fix: `jev/bot.py` removes `flee_up` for 3 decisions after a `flee_up` that was blocked.

## T5635 rabid rat, Dlvl 5

- Cause: In the dark, a water nymph stole the plate mail, the shield and the spear (T5064). Later a wererat bite made Jev a wererat. As a rat, Jev was Overloaded. The drop options came from a stale inventory, so Jev tried 20 drops of items that were already gone. Monsters bit it 34 -> 15 meanwhile, and Jev used its prayer. 40 turns later, a mob killed it at AC 10.
- Prevention: Read the inventory again after each drop. Do not spend turns on items that you do not have.
- Fix: `jev/bot.py` reads the inventory after each `drop_` option.

## T3000 shopkeeper's wand, Dlvl 5

- Cause: In a food shop, a giant mimic stuck to Jev. Jev burned Elbereth, then chose `flee_up`, which cannot move a stuck hero (30 -> 13). It quaffed an unknown potion: hallucination. The shopkeeper then showed as a hostile "raging nerd", and Jev zapped fire at him. The shopkeeper killed Jev with his wand.
- Prevention: When a monster holds you, fight it. While you hallucinate, monster names and the peaceful flag are not correct. Do not attack, zap or throw at a square where a peaceful monster was before.
- Fix: `jev/bot.py` sets `held` on a mimic hit and offers attacks when `retreat` and `flee` are the only options. While Jev hallucinates, it removes attack, zap and throw options that point at the last known peaceful squares.

## T3624 little dog, Dlvl 6

- Cause: A were-form shed Jev's armor. Back in dwarf form at AC 10, a little dog (speed 18, 2 bites a turn) took Jev 42 -> 9. Jev had a wand of digging, but it chose a gamble prayer 290 turns after the last prayer. The prayer failed and the dog killed Jev.
- Prevention: A wand of digging or teleportation is a sure escape. A prayer before the timeout is a gamble.
- Fix: `jev/bot.py` removes the gamble prayer when a zap of digging down or a teleport is on offer.

## T6827 hill orc's wand of striking, Dlvl 6

- Cause: A band of 6 hill orcs came down a narrow room. One zapped a wand of striking. Jev closed in, 46 -> 29 -> 12. At 12/62 it engraved Elbereth instead of zapping its own unknown wand. The orc hit it during the engraving, and the next zap killed it.
- Prevention: Elbereth does not stop a wand. A scared monster steps away and zaps from range (monmove.c m_move, mhitu.c find_offensive).
- Fix: `jev/bot.py` removes `elbereth` at low HP when a monster zapped a wand in the last 3 messages and a zap, teleport or dig-down option is on offer.

## T4657 poisoned orcish arrow, Dlvl 6

- Cause: An Uruk-hai shot volleys of 2 poisoned arrows. When the second arrow of a volley misses, the game prints "It misses.", and the bot took this as an unseen attacker. Jev chose `find_unseen` 5 times. Later, beside the Uruk-hai on Elbereth, Jev engraved again at 16 HP instead of hitting it. The scared Uruk-hai shot again, and the poison killed Jev.
- Prevention: "It misses." after "shoots" or "throws" is a missile, not a monster. Elbereth does not stop arrows. Hit an adjacent archer.
- Fix: `jev/bot.py` ignores "It hits/misses" after a volley in `unseen_attacker`. It removes `elbereth` when the shooter is adjacent, it shot in the last 3 messages, and an attack is on offer.

## T4916 fire ant, Dlvl 6

- Cause: Jev stood on Elbereth in a shop door. A boxed-in fire ant (speed 18, fire bites) panic-attacked it, 20 -> 6 -> 0. Jev had a wand of magic missile, but the shop rule removed every zap and throw near a shop.
- Prevention: A known attack wand or a throw is safe in a shop when no peaceful monster is on the line or on its bounce.
- Fix: `jev/bot.py` keeps throws and known attack-wand zaps near a shop when no peaceful monster is within 13 squares on that line, in both directions.

## T6798 soldier ant, Dlvl 8

- Cause: A soldier ant (speed 18) was adjacent at 43/66 HP. Jev chose Elbereth over an attack. In 5.0, engraving is an occupation and a hit interrupts it. The ant bit and stung Jev through the engraving, and the poison finished it.
- Prevention: Engrave before a fast monster is adjacent. When it is adjacent, fight.
- Fix: `jev/bot.py` removes `elbereth` when a hostile with speed 15 or more is adjacent, an attack is on offer and HP is 1/3 or more.

## T245 shopkeeper Cahersiveen, Dlvl 2

- Cause: Jev kicked a locked door. No sign was in the dust, but the door was a closed shop. The shopkeeper zapped a wand of striking and killed Jev. Three explore options were open at that time.
- Prevention: A locked door can be a closed shop with a scuffed sign. Kick a locked door only when nothing else is left to explore.
- Fix: `jev/bot.py` stops when it finds a door locked and decides again. It removes locked-door options while explore options exist and Jev has no key or lock pick.

## T8105 soldier, Dlvl 9

- Cause: A wraith, a soldier and a pony were next to Jev on the stairs. Jev went up and down the stairs 7 times. The adjacent monsters followed on each trip and hit Jev. HP went from 71 to 0. Attack options were open each time.
- Prevention: Adjacent monsters follow you up and down the stairs. After two stair trips that did not shake them off, fight.
- Fix: `jev/bot.py` removes the stair options when a hostile monster is adjacent, attacks are open, and 2 of the last 3 decisions were stair trips.

## T7569 ogre, Dlvl 8

- Cause: A mumak, an ogre and a soldier ant were next to Jev. The last prayer was 75 turns before. Jev had a wand of digging, but the bot offered it only at 4 HP. Before that, Jev attacked and tried Elbereth. The ant interrupted the engraving. HP went from 48 to 4 in three turns.
- Prevention: If two or more monsters are adjacent, one of them is stronger, and prayer is not available, escape at once.
- Fix: `jev/bot.py` offers the wand of digging in this case, and removes the attack and Elbereth options.

## T4427 cave spider, Dlvl 5

- Cause: Jev was Hungry and had no food in its pack. It stood on a fresh kobold corpse, but the bot forbids a poisonous corpse until Jev is Weak and cannot pray. Jev then prayed for food 840 turns after the last prayer. The god was angry and took a level. Jev fainted again and again, and a cave spider bit it to death.
- Prevention: With no food in the pack, eat the next safe or poisonous fresh corpse. Without poison resistance, the poison costs rnd(15) HP or some Str 4 times in 5. Starving costs the game.
- Fix: `jev/bot.py` allows kobold and other poisonous corpses when Jev is Hungry with no food and more than 30 HP, or Weak with no food and more than 15 HP.

## T8554 Woodland-elf, Dlvl 6

- Cause: Jev killed one Woodland-elf. Then it walked toward three more at 61/71 HP. The up staircase was 5 steps away. Jev had AC 5, because it found no body armor in 8500 turns. Two elves hit it from 61 to 15 in three turns. The potions that it drank did not heal it.
- Prevention: Do not close in on a group of monsters at your level or above. Let them come to a corridor, or leave by the stairs. Elves ignore Elbereth.
- Fix: `jev/bot.py` does not offer "close in" on a monster that is not weaker when two or more such monsters are within 8 squares.
- Open problem: AC 5 at T8500. Jev needs a way to get body armor (shops, kills of armored monsters).

## T3361 kitten, Dlvl 5

- Cause: A wood nymph on Dlvl 4 stole from Jev six times in 240 turns. It took the darts, the shield, the sling, the spear, a scroll and the potions. The bot offered "leave this level" only when no monster was near. The nymph itself was near most of the time, so Jev waited on Elbereth 39 times. Jev went down with no weapon and AC 10, and a kitten killed it.
- Prevention: After the first theft, leave the level at once. A nymph teleports and comes back. Elbereth only makes it run, and it returns.
- Fix: `jev/bot.py` does not count nymphs as near monsters for "leave this level". With only a nymph near, Jev leaves at half HP or more.

## T8623 pony, Dlvl 5

- Cause: On the Oracle level (Dlvl 6), a peaceful gnome lord stood in the only corridor that was not explored. Jev could not pass it. It chose "explore" 2045 times, and each walk was blocked ("Pardon me, gnome lord"). Jev stayed 4400 turns and lived on five prayers. The sixth hunger came too soon after a prayer. Jev fainted and a pony killed it.
- Prevention: A peaceful monster that blocks the only way on for many turns must go. 5.0 source (mon.c): a peaceful kill costs Luck -1 half the time, and some alignment. That is much less than the cost of starving.
- Fix: `jev/bot.py` offers "attack the peaceful monster" after 20 of the last 30 explore walks were blocked, with a peaceful non-human adjacent and no hostile within 3 squares. Not in a town, and not when hallucinating. The option removes explore, wait and search.

## T13037 Ms. Kediri the shopkeeper, Dlvl 5

- Cause: Jev stood in the doorway of a delicatessen, and the shopkeeper stood next to it. Explore was blocked, so Jev chose "dig down" with its pick-axe. Digging in a shop doorway damages the door. The shopkeeper got angry ("How dare you ruin my door?"). She took Jev from 87 HP to 0 with a wand of striking and her hits.
- Prevention: Never dig in a shop, in a shop door, or near a shopkeeper.
- Fix: `jev/bot.py` does not offer the pick-axe dig on a door, in or near a known shop, or with a peaceful `@` within 8 squares. The wand of digging escape is also not offered in or near a shop.
