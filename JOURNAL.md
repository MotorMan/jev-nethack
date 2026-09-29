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
