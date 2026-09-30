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
