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
