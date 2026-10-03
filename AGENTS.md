# Agent notes for nethack-jev

Read this file at the start of each session. It holds the instructions of the user and the lessons of earlier sessions.

## Goal

- Get an ascension in NetHack 5.0.0 with Jev, and with no LLM in the loop. The model is kenforthewin's LLM ascension.
- Jev only picks one option from a list. `jev/bot.py` makes the options and does the keystrokes.
- Use the hardfought configuration (`jev/nethackrc`). The character is a dwarven Valkyrie.
- The user can be asleep. Do not wait for answers. Make a decision and continue.

## Rules from the user

- The repo is public (github.com/statico/jev-nethack). Never commit secrets.
- `.env` holds `JEV_API_KEY`, `HARDFOUGHT_*`, `NAO_*`, and `LUNAROUTE_API_KEY`. Never print or commit it.
- `runs/`, `build/`, `nethack/`, `.env`, and the wiki dump stay out of git.
- The wiki dump is `nethackwiki_current.xml.gz` in the repo root. If it is missing, tell the user to download it from https://nethackwiki.com/wiki/NetHackWiki:Download. We must not redistribute it, so `.gitignore` excludes it.
- Commit and push after each change. Do not collect changes into one commit.
- End each commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Write the minimum code. Do not add abstractions that nobody asked for.
- Write docs in Simplified Technical English (`/simple-english`).
- Do not ask about `/schedule`.
- If the sandbox blocks a command, run `nono why`.
- Put reports and research notes in `research/`. Give each topic its own folder, with `report.md` for the result.
- Keep the "Current status" section of `README.md` current. Update it when a game sets a new record.

## Death loop

Every death is a lesson. Most games can be won, so do not call a death bad luck. Do these steps for each death:

1. Find the decision that lost the game. Use `runs/Hosted/<RUN>/decisions.jsonl` and `runs/Hosted/server.log`.
2. Read the wiki page: `gzip -dc nethackwiki_current.xml.gz | grep ...`. Do not use `zcat` (it fails on macOS).
3. Read the 5.0.0 source in `build/NetHack50/src/` and `dat/`. If the wiki and the source disagree, the source is correct.
4. Fix `jev/bot.py`. Put the turn number and the cause in the code comment.
5. Add an entry to `JOURNAL.md`: the cause, the prevention, the fix.
6. Run the tests (below).
7. Commit and push.
8. Restart Hosted (below).
9. Give the user a short report.

## Commands

- Tests: `.venv/bin/python test_corpse.py && .venv/bin/python test_loop_guard.py && .venv/bin/python test_sokoban.py && .venv/bin/python test_price_id.py && .venv/bin/python test_search_spot.py && .venv/bin/python test_mines.py && .venv/bin/python test_pursuit.py && .venv/bin/python test_shops.py && .venv/bin/python test_plan.py && ! .venv/bin/python -m pyflakes jev/ | grep 'undefined name'`. The pyflakes step finds a deleted variable that is still in use. Two crashes came from this.
- Restart Hosted: `kill $(pgrep -f "[j]ev.server --name Hosted --port 8771")`. Then run `JEV_BUDGET_USD=35 scripts/play.sh Hosted 8771` as a background command. The cap is $35: the user added $10 to the $25 that was spent. Do not raise it again. When it runs out, add the kev-4b arguments `http://127.0.0.1:8784/v1/systemone jev-latest kev-4b`. The bot continues from the saved game.
- The user stopped Hosted (2026-10-02) and the Jev calls. Do not restart Hosted until the user asks. In the death loop, restart NoModel instead. Earlier rule: run only Hosted (port 8771). The user stopped the LunaRoute engines and the local models. Do not start them.
- The user also asked for a "no model" test: `scripts/play.sh NoModel 8772 none none "no model"`. It always takes the first option and makes no Jev call. Its log is `runs/NoModel/server.log`. Compare its max Dlvl and turns with Hosted.
- Never use `pkill -f jev.server`. It also kills the shell of the tool.
- Death monitor: `tail -n0 -F runs/Hosted/server.log | awk '/run .* over|Traceback|Error|budget|ascended/{print; fflush()}'`. The monitor stops after 30 minutes. Start it again when it stops.
- Web UI: `web/` (React, Vite, Tailwind, shadcn with the SMUI theme). Build with `cd web && npm run build`. The server gives `web/dist` and `/api/state`.

## Game policy from the user

- Never read an unknown scroll. The exception is a scroll that a price identification shows to be identify.
- Read identify scrolls when unknown wands, rings, amulets, potions, or scrolls are in the pack.
- Armor: compare the cost of a cursed item. Wear plain cloaks and mithril without a known BUC. A cloak with an unknown appearance needs a known BUC.
- Do not dip for Excalibur.
- Gold: buy protection from a priest first. After that, keep 2000 to 4000 gold.
- Elbereth is for emergencies. The default against a group is to fight from a corridor or a doorway.
- Boxes: unlock with a key or lock pick. If you have neither, pry the lock with a dagger. If you have no dagger, kick the box. Never force a lock with the main weapon. Keep 2 to 3 daggers until you have a key or lock pick.
- A key, a lock pick and a unicorn horn are priority items. Buy them in shops.
- 5.0 source: the watch treats any tool on a locked town door as lock picking, keys too. Do not unlock town doors where the watch can see you.
- Do not pick up gems or gray stones (a gray stone can be a loadstone). Do not pick up random weapons. The Valkyrie keeps the spear until Mjollnir (sacrifice at a co-aligned altar) or a better artifact.
- Test BUC on altars. Wear any armor with a known good BUC: helmets (elven is better than orcish), gloves, boots, shirts. Target AC -10 by Dlvl 10.
- Note vaults, altars and stashes with `#annotate`. With a pick-axe, raid known vaults, then buy protection from a priest.
- Rate limit: NEVER send more than 2 to 3 actions each second to a public server (hardfought, NAO). `REMOTE_GAP` in `jev/hardfought.py` sets this limit, and `Term.floor` enforces it. A new NAO launcher must use the same floor. Local play has no limit. The delay includes the time of the Jev call.

## UI rules from the user

- Use no transitions and no animations.
- Use the Iosevka font with the CRT effect.
- The layout must fit a 1512x872 window.
- Give a tooltip to each control and each statistic.

## Notes from the 5.0.0 source

- Prayer: a prayer during the timeout, or with Luck below 0, fixes nothing. Low HP is trouble only at 1/7 of max HP or less, or at 5 HP or less.
- A broken Sokoban boulder costs 1 Luck. Luck recovers 1 point each 600 turns.
- A hugging monster (owlbear, python, rope golem, and others) stops engraving and movement. Engrave Elbereth before it is adjacent.
- "The wand is too worn out to engrave" means that the wand has 0 charges.
