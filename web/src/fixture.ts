import type { Run, State } from "./types"

// Sample NetHack screen: 24 lines x 80 cols. Row 0 = message, 1-21 = map, 22-23 = status.
const MAP = [
  "The little dog picks up a gnome corpse.  You see here a scroll labeled ELBIB YLOH.",
  "",
  "            -----------                                -------------",
  "            |.........|                                |...........|",
  "            |....{....+#########                     ##+...........|",
  "            |.........|        #                     # |.....>.....|",
  "            |..%......|        #####                 # |...........|",
  "            -----.-----            #                 # -------------",
  "                 #                 ############     ##",
  "                 #                            #     #",
  "                 ##              -------------.-----#---",
  "                  #              |.....................+",
  "                  ########       |...$.......d.......F.|",
  "                         #       |...........@..)......|",
  "                         ########+............!........|",
  "                                 |..?.....:.......[....|",
  "                                 -----------------------",
  "",
  "",
  "",
  "",
  "",
  "Agent the Stripling            St:17 Dx:14 Co:18 In:7 Wi:10 Ch:8 Lawful",
  "Dlvl:3 $:42 HP:14(18) Pw:1(1) AC:6 Xp:2/31 T:812 Hungry",
]

type Attr = [fg: string, bold: boolean]
const GLYPH: Record<string, Attr> = {
  "@": ["white", true], d: ["white", false], F: ["green", true], ":": ["brown", true],
  "+": ["brown", false], "{": ["blue", false], "$": ["brown", true], "%": ["red", false],
  "!": ["magenta", false], "?": ["white", false], ")": ["cyan", false], "[": ["cyan", false],
  ">": ["default", false], "#": ["default", false],
}

function rowRuns(line: string, map: boolean): Run[] {
  const text = line.padEnd(80).slice(0, 80)
  const runs: Run[] = []
  for (const ch of text) {
    const [fg, bold] = (map && GLYPH[ch]) || ["default", false]
    const last = runs[runs.length - 1]
    if (last && last[1] === fg && last[3] === bold) last[0] += ch
    else runs.push([ch, fg, null, bold, false])
  }
  return runs
}

const rows = MAP.map((l, i) => rowRuns(l, i > 0 && i < 22))
// Highlight "Hungry" in brown/yellow like curses status hilites.
rows[23] = [["Dlvl:3 $:42 HP:14(18) Pw:1(1) AC:6 Xp:2/31 T:812 ", "default", null, false, false],
  ["Hungry", "brown", null, true, false], ["".padEnd(80 - 55), "default", null, false, false]]

const now = Date.now()
const iso = (msAgo: number) => new Date(now - msAgo).toISOString()

const labels = ["explore: travel to unexplored", "fight: attack newt", "move: go east", "eat: gnome corpse",
  "pickup: scroll", "search here", "descend stairs", "move: go north", "pray", "wield: long sword"]

export const FIXTURE: State = {
  mode: "local",
  paused: false,
  phase: "thinking",
  delay_ms: 250,
  order: "Descend steadily but eat when Hungry. Do not pray more than once per 1000 turns.",
  screen: { rows, cursor: [44, 13], cols: 80, lines: 24 },
  status: {
    name: "Agent", title: "the Stripling", align: "Lawful", dlvl: 3, gold: 42, hp: 14, hpmax: 18,
    pw: 1, pwmax: 1, ac: 6, xl: 2, exp: 31, turn: 812, hunger: "Hungry", conditions: [],
    st: "17", dx: 14, co: 18, in: 7, wi: 10, ch: 8,
  },
  decision: {
    id: 318, at: iso(900), turn: 812, pending: false,
    question: "You are Hungry. A newt is 4 squares east. Your pet is adjacent. Choose the next high-level action.",
    options: [
      { id: "eat_corpse", label: "Eat the gnome corpse here", detail: "fresh (killed T:806), safe for a Valkyrie", p: 0.08 },
      { id: "eat_ration", label: "Eat a food ration (inventory d)", detail: "takes 5 turns; newt could interrupt", p: 0.61 },
      { id: "fight_newt", label: "Fight the newt", detail: "F: newt (:) at +4,+2", p: 0.19 },
      { id: "explore", label: "Continue exploring", detail: "room 38% unexplored", p: 0.07 },
      { id: "descend", label: "Travel to > and descend", detail: "downstairs known on this level", p: 0.05 },
    ],
    choice: "eat_ration", confidence: 0.61, latency_ms: 1840,
    state_text: MAP.join("\n") + "\n\nInventory:\na - a +1 long sword (weapon in hand)\nb - a +0 dagger\nc - an uncursed +3 small shield (being worn)\nd - 2 food rations\ne - a scroll labeled ELBIB YLOH",
  },
  history: Array.from({ length: 60 }, (_, i) => {
    const conf = 0.35 + 0.6 * Math.abs(Math.sin(i * 1.7))
    return {
      id: 259 + i, at: iso((60 - i) * 4000), turn: 640 + i * 3, dlvl: i < 30 ? 2 : 3,
      choice: `opt${i % labels.length}`, label: labels[(i * 7) % labels.length],
      p: conf, confidence: conf, n_options: 3 + (i % 5), latency_ms: 900 + Math.round(1400 * Math.abs(Math.cos(i * 0.9))),
    }
  }),
  messages: [
    { turn: 790, text: "You kill the jackal!" },
    { turn: 796, text: "You hear some noises in the distance." },
    { turn: 801, text: "There is a doorway here." },
    { turn: 806, text: "You kill the gnome!" },
    { turn: 809, text: "You are beginning to feel hungry." },
    { turn: 812, text: "The little dog picks up a gnome corpse.  You see here a scroll labeled ELBIB YLOH." },
  ],
  log: [
    { at: iso(60000), level: "info", text: "run started: val-hum-fem-law" },
    { at: iso(21000), level: "warn", text: "jev latency 4.2s exceeded soft limit" },
    { at: iso(8000), level: "error", text: "jev call failed (timeout); retrying" },
    { at: iso(2000), level: "info", text: "decision #318 -> eat_ration (p=0.61)" },
  ],
  jev: { calls: 318, errors: 2, cost_usd: 0.4127, avg_latency_ms: 1620, last_model: "jev-1", budget_usd: 5 },
  run: { id: "r-0007", started: iso(3600_000), character: "Val-Hum-Fem-Law", max_dlvl: 3, decisions: 318 },
  runs: [
    { id: "r-0006", started: iso(9000_000), ended: iso(7200_000), character: "Val-Dwa-Fem-Law", turns: 4211, max_dlvl: 6, death: "killed by a soldier ant", score: 3120 },
    { id: "r-0005", started: iso(12000_000), ended: iso(10000_000), character: "Sam-Hum-Mal-Law", turns: 1780, max_dlvl: 4, death: "died of starvation", score: 912 },
    { id: "r-0004", started: iso(15000_000), ended: iso(14000_000), character: "Val-Hum-Fem-Neu", turns: 302, max_dlvl: 1, death: "killed by a jackal", score: 48 },
  ],
  inventory: [
    { letter: "a", text: "a +1 long sword (weapon in hand)" },
    { letter: "b", text: "a +0 dagger" },
    { letter: "c", text: "an uncursed +3 small shield (being worn)" },
    { letter: "d", text: "2 food rations" },
    { letter: "e", text: "a scroll labeled ELBIB YLOH" },
  ],
  level: { dlvl: 3, explored: 0.62, downstairs: true, upstairs: false },
}
