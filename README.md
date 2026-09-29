# nethack-jev

NetHack 5.0 played by [Jev](https://typesafe.ai) (TypeSafe's `systemone` API) with no LLM in the loop.
This is a Jev-only take on [kenforthewin's LLM ascension run](https://kenforthewin.github.io/blog/posts/llm-nethack-ascension),
structured like [jev-doom](https://github.com/olivier-motium/jev-doom). Code reads the tty and lists the legal,
concrete options (attack a monster, explore an edge, eat, pray, descend, kick a door, dig...). Jev picks one
per turn as a `choice` question, and code "motors" carry it out.

## Run locally

```sh
scripts/build-nethack.sh                    # Hardfought's NetHack50 fork + sysconf -> ./nethack
/opt/homebrew/bin/python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd web && npm install && npm run build)    # SMUI dashboard -> web/dist
echo 'JEV_API_KEY=...' > .env
.venv/bin/python -m jev.server              # http://127.0.0.1:8770
```

The dashboard shows the live terminal, Jev's options with probabilities, decision history, the budget, and
run records. It can pause, step, set speed, start a new game, and give Jev a standing order.
`JEV_BUDGET_USD` (default 5) caps spend. Each run's decisions go to `runs/<id>/decisions.jsonl`.

## Hardfought

```sh
# .env: HARDFOUGHT_USERNAME=... HARDFOUGHT_PASSWORD=...
# once: paste jev/nethackrc into your NetHack 5.0 rc at https://www.hardfought.org/nethack/rcedit/
.venv/bin/python -m jev.server --hardfought
```

The connection goes through Hardfought's web terminal websocket (`jev/wsbridge.py`), because port 22 is blocked
on some networks. Set `HARDFOUGHT_SSH=1` to use ssh instead.

See `JOURNAL.md` for the development log.

## Watching in a terminal

With the server running, keep this open in any terminal (at least 80x40):

    .venv/bin/python -m jev.watch

It redraws the live game screen in color. Below the screen it shows Jev's current options with their probabilities, the last few decisions and their outcomes, the Jev API spend, and recent deaths. Ctrl-C quits.
