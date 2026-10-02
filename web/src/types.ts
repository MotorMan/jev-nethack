// Mirrors the server's State JSON (see /api/state).
export type Run = [text: string, fg: string, bg: string | null, bold: boolean, reverse: boolean]

export interface DecisionOption { id: string; label: string; detail: string; p: number | null }

export interface Decision {
  id: number; at: string; turn: number; pending: boolean
  question: string
  options: DecisionOption[]
  choice: string | null; confidence: number | null; latency_ms: number | null
  state_text: string
}

export interface HistoryEntry {
  id: number; at: string; turn: number; dlvl: number; choice: string; label: string
  p: number; confidence: number; n_options: number; latency_ms: number
}

export interface Status {
  name?: string; title?: string; align?: string; dlvl?: number; gold?: number
  hp?: number; hpmax?: number; pw?: number; pwmax?: number; ac?: number; xl?: number
  exp?: number; turn?: number; hunger?: string; conditions: string[]
  st?: string; dx?: number; co?: number; in?: number; wi?: number; ch?: number
}

export interface RunSummary {
  id: string; started: string; ended: string | null; character: string; turns: number
  max_dlvl: number; death: string | null; score: number | null
  engine?: string; models?: string[]
}

export interface State {
  mode: "local" | "hardfought"
  paused: boolean
  phase: string
  delay_ms: number
  order: string
  screen: { rows: Run[][]; cursor: [number, number]; cols: number; lines: number }
  status: Status
  decision: Decision | null
  history: HistoryEntry[]
  messages: { turn: number; text: string }[]
  log: { at: string; level: "info" | "warn" | "error"; text: string }[]
  jev: { calls: number; errors: number; cost_usd: number; avg_latency_ms: number; last_model: string | null; budget_usd: number
    last?: { request: { state: string; model: string; questions: unknown }; response: unknown } | null }
  run: { id: string; started: string; character: string; max_dlvl: number; decisions: number; engine?: string; models?: string[] }
  runs: RunSummary[]
  inventory: { letter: string; text: string; contents?: string[] }[]
  level: { dlvl: number; explored: number; downstairs: boolean; upstairs: boolean; notes?: [number | string, string][] }
}
