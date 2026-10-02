import { Children, Fragment, useEffect, useRef, useState, type ReactNode } from "react"
import {
  Activity, Check, ChevronRight, Copy as CopyIcon, Cpu, Footprints, Map as MapIcon, LayoutPanelLeft, Maximize2, Moon, Package, Pause, Play, RotateCcw,
  Send, StepForward, Sun, Swords, Wifi, WifiOff, WrapText, X,
} from "lucide-react"
import { Dialog } from "radix-ui"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Slider } from "@/components/ui/slider"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { FIXTURE } from "./fixture"
import { Terminal } from "./Terminal"
import type { State } from "./types"

type Conn = "demo" | "connecting" | "live" | "offline"
type Tone = "green" | "yellow" | "orange" | "red" | "frost-2" | "frost-3" | "purple" | "muted"

const DEMO = new URLSearchParams(location.search).has("demo")

// ---------- data ----------

function useJevState(): [State, Conn] {
  const [state, setState] = useState<State>(FIXTURE)
  const [conn, setConn] = useState<Conn>(DEMO ? "demo" : "connecting")
  useEffect(() => {
    if (DEMO) return
    const es = new EventSource("/api/events") // browser reconnects automatically
    es.onmessage = (e) => {
      try {
        setState(JSON.parse(e.data))
        setConn("live")
      } catch { /* ignore malformed frame */ }
    }
    es.onerror = () => setConn("offline")
    return () => es.close()
  }, [])
  return [state, conn]
}

function control(body: Record<string, unknown>) {
  return fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => undefined)
}

// ---------- tiny helpers ----------

const tone = (t: Tone) => (t === "muted" ? "var(--muted-foreground)" : `hsl(var(--smui-${t}))`)
const pct = (x: number | null | undefined, d = 0) => (x == null ? "--" : `${(x * 100).toFixed(d)}%`)
const ms = (x: number | null | undefined) => (x == null ? "--" : x >= 1000 ? `${(x / 1000).toFixed(2)}s` : `${Math.round(x)}ms`)
const num = (x: number | undefined) => (x == null ? "--" : x.toLocaleString())
// average game turns per wall-clock second since the run started
const tps = (turns: number | undefined, started?: string, ended?: string | null) => {
  const secs = ((ended ? Date.parse(ended) : Date.now()) - Date.parse(started ?? "")) / 1000
  return turns && secs > 0 ? (turns / secs).toFixed(2) : "--"
}
const hhmmss = (iso: string) => new Date(iso).toLocaleTimeString([], { hour12: false })
const fracTone = (f: number): Tone => (f > 0.66 ? "green" : f > 0.4 ? "yellow" : f > 0.2 ? "orange" : "red")

function Dot({ t, pulse }: { t: Tone; pulse?: boolean }) {
  return (
    <span
      className={cn("inline-block w-[6px] h-[6px] rounded-full shrink-0", pulse && "pulse-dot")}
      style={{ background: tone(t), color: tone(t) }}
    />
  )
}

function Tag({ t, children }: { t: Tone; children: ReactNode }) {
  const c = tone(t)
  return (
    <span
      className="text-label tracking-wider uppercase px-1.5 py-px border whitespace-nowrap"
      style={{ color: c, borderColor: `color-mix(in srgb, ${c} 35%, transparent)` }}
    >
      {children}
    </span>
  )
}

function Tip({ tip, children }: { tip?: ReactNode; children: ReactNode }) {
  if (!tip) return <>{children}</>
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className="max-w-xs">{tip}</TooltipContent>
    </Tooltip>
  )
}

// copy button: navigator.clipboard needs a secure context (localhost or https); over plain http on the LAN fall back to execCommand
function Copy({ text, tip }: { text: string; tip: string }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const t = document.createElement("textarea")
      t.value = text
      document.body.appendChild(t)
      t.select()
      document.execCommand("copy")
      t.remove()
    }
    setDone(true)
    setTimeout(() => setDone(false), 1200)
  }
  return (
    <Tip tip={tip}>
      <Button size="xs" variant="ghost" className="text-muted-foreground" onClick={copy}>{done ? <Check /> : <CopyIcon />} {done ? "copied" : "copy"}</Button>
    </Tip>
  )
}

function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("text-label text-muted-foreground tracking-[1.5px] uppercase block", className)}>{children}</span>
}

// maximize button: shows `children` again, enlarged, in a fixed overlay (Esc / backdrop / close button dismiss)
function Max({ title, right, bodyClass, children }: { title: ReactNode; right?: ReactNode; bodyClass?: string; children: ReactNode }) {
  return (
    <Dialog.Root>
      <Tip tip="maximize">
        <Dialog.Trigger asChild>
          <Button size="icon" variant="ghost" className="size-4 text-muted-foreground" aria-label="maximize"><Maximize2 className="size-3" /></Button>
        </Dialog.Trigger>
      </Tip>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
        <Dialog.Content aria-describedby={undefined} onCloseAutoFocus={(e) => e.preventDefault()}
          className="fixed inset-4 z-50 bg-card text-card-foreground border flex flex-col card-glow outline-none">
          <div className="flex items-center justify-between py-1.5 px-2.5 border-b border-border">
            <Dialog.Title className="text-xs text-muted-foreground tracking-[1.5px] uppercase font-normal flex items-center gap-2">{title}</Dialog.Title>
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              {right}
              <Dialog.Close asChild><Button size="icon" variant="ghost" className="size-4 text-muted-foreground" aria-label="close"><X className="size-3" /></Button></Dialog.Close>
            </div>
          </div>
          <div className={cn("p-2.5 flex-1 min-h-0 flex flex-col overflow-auto", bodyClass)} style={{ containerType: "size" }}>{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function Panel({ title, right, children, className, bodyClass }: {
  title: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string
}) {
  return (
    <Card className={cn("card-glow min-w-0", className)}>
      <CardHeader className="flex flex-row items-center justify-between py-1.5 px-2.5">
        <CardTitle className="text-xs text-muted-foreground tracking-[1.5px] uppercase font-normal flex items-center gap-2">
          {title}
        </CardTitle>
        <CardDescription className="text-xs text-muted-foreground flex items-center gap-2">
          {right}
          <Max title={title} right={right} bodyClass={bodyClass}>{children}</Max>
        </CardDescription>
      </CardHeader>
      <CardContent className={cn("p-2.5", bodyClass)}>{children}</CardContent>
    </Card>
  )
}

// JSON pretty-printer with smui-palette highlighting: keys, strings, numbers, true/false/null, punctuation
const JSON_TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}[\],:])/g
function Json({ v, wrap }: { v: unknown; wrap: boolean }) {
  const src = JSON.stringify(v, null, 2) ?? "null"
  const out: ReactNode[] = []
  let last = 0
  for (const m of src.matchAll(JSON_TOKEN)) {
    out.push(src.slice(last, m.index))
    const c: Tone = m[1] ? (m[2] ? "frost-2" : "green") : m[3] ? "purple" : m[4] ? "orange" : "muted"
    out.push(<span key={m.index} style={{ color: tone(c) }}>{m[1] ?? m[0]}</span>)
    if (m[2]) out.push(<span key={m.index + "c"} style={{ color: tone("muted") }}>{m[2]}</span>)
    last = m.index + m[0].length
  }
  out.push(src.slice(last))
  return <pre className={cn("text-xs bg-background border border-border p-2 overflow-auto", wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre")}>{out}</pre>
}

function Bar({ value, t, className }: { value: number; t: Tone; className?: string }) {
  return (
    <Progress
      value={Math.max(0, Math.min(100, value * 100))}
      className={cn("h-2", className)}
      style={{ ["--bar" as string]: tone(t) }}
    />
  )
}

// ---------- header ----------

function Header({ s, conn }: { s: State; conn: Conn }) {
  const [drag, setDrag] = useState<number | null>(null)
  const delay = drag ?? s.delay_ms
  const [dark, setDark] = useState(true)
  useEffect(() => { document.documentElement.classList.toggle("dark", dark) }, [dark])

  const connTone: Tone = conn === "live" ? "green" : conn === "offline" ? "red" : conn === "demo" ? "purple" : "yellow"
  const connText = conn === "offline" ? "offline // sample data" : conn
  return (
    <nav className="sticky top-0 z-50 bg-card border-b border-border">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-3 py-1 min-h-10">
        <div className="flex items-center gap-2">
          <Swords className="size-4 text-primary" />
          <span className="text-sm font-semibold tracking-[3px] uppercase">
            jev <span className="text-muted-foreground">//</span> nethack
          </span>
        </div>
        <Tip tip="where the game runs: local NetHack, or a public server over SSH"><span><Tag t={s.mode === "hardfought" ? "purple" : "frost-2"}>{s.mode}</Tag></span></Tip>
        <Tip tip="connection to the bot's live state stream">
        <div className="flex items-center gap-1.5 text-label uppercase tracking-wider" style={{ color: tone(connTone) }}>
          {conn === "offline" ? <WifiOff className="size-3.5" /> : <Wifi className="size-3.5" />}
          {connText}
        </div>
        </Tip>

        <div className="flex flex-wrap items-center gap-2 ml-auto">
          <Tip tip={s.paused ? "let the bot keep playing" : "stop after the current decision"}>
          <Button size="sm" variant={s.paused ? "default" : "outline"} onClick={() => control({ action: s.paused ? "resume" : "pause" })}>
            {s.paused ? <Play /> : <Pause />}
            {s.paused ? "resume" : "pause"}
          </Button>
          </Tip>
          <Tip tip="while paused: make exactly one decision">
          <span><Button size="sm" variant="outline" disabled={!s.paused} onClick={() => control({ action: "step" })}>
            <StepForward /> step
          </Button></span>
          </Tip>
          <Tip tip="abandon this game and start a fresh character">
          <Button
            size="sm" variant="outline"
            onClick={() => confirm("Abandon the current game and start a new one?") && control({ action: "new_game" })}
          >
            <RotateCcw /> new game
          </Button>
          </Tip>
          <Tip tip="minimum time between actions sent to the game, thinking time included (remote servers: at least 250ms)">
          <div className="flex items-center gap-2 pl-2 w-[210px]">
            <Label className="whitespace-nowrap w-[88px]">delay {delay}ms</Label>
            <Slider
              min={0} max={2000} step={50} value={[delay]} className="flex-1"
              onValueChange={([v]) => setDrag(v)}
              onValueCommit={([v]) => { setDrag(null); control({ action: "speed", delay_ms: v }) }}
            />
          </div>
          </Tip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="icon" variant="ghost" className="size-8" onClick={() => dispatchEvent(new Event("split-reset"))} aria-label="reset panes">
                <LayoutPanelLeft />
              </Button>
            </TooltipTrigger>
            <TooltipContent>reset panes to default sizes</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="icon" variant="ghost" className="size-8" onClick={() => setDark(!dark)} aria-label="toggle theme">
                {dark ? <Sun /> : <Moon />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{dark ? "light theme" : "dark theme"}</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <div className="h-px bg-gradient-to-r from-transparent via-primary/60 to-transparent" />
    </nav>
  )
}

// ---------- vitals ----------

function Stat({ label, value, t, tip }: { label: string; value: ReactNode; t?: Tone; tip?: ReactNode }) {
  return (
    <Tip tip={tip}>
    <div className="bg-background border border-border px-2 py-1 min-w-0">
      <Label>{label}</Label>
      <div className="text-lg font-medium tracking-tight leading-tight truncate" style={t ? { color: tone(t) } : undefined}>
        {value}
      </div>
    </div>
    </Tip>
  )
}

function Meter({ label, cur, max, tip }: { label: string; cur?: number; max?: number; tip?: ReactNode }) {
  const f = cur != null && max ? cur / max : 0
  const t = fracTone(f)
  return (
    <Tip tip={tip}>
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <Label>{label}</Label>
        <span className="text-sm tabular-nums">
          <span style={{ color: tone(t) }} className="font-semibold">{cur ?? "--"}</span>
          <span className="text-muted-foreground"> / {max ?? "--"}</span>
        </span>
      </div>
      <Bar value={f} t={t} className="h-2.5" />
    </div>
    </Tip>
  )
}

function hungerTone(h: string): Tone {
  const x = h.toLowerCase()
  if (x.includes("faint") || x.includes("starv")) return "red"
  if (x.includes("weak")) return "orange"
  if (x.includes("satiated")) return "frost-2"
  return "yellow"
}

function Vitals({ s }: { s: State }) {
  const st = s.status
  const attrs: [string, ReactNode, string][] = [
    ["st", st.st, "strength: melee to-hit and damage, carrying capacity"], ["dx", st.dx, "dexterity: to-hit, especially with thrown weapons"],
    ["co", st.co, "constitution: HP gained per level, carrying capacity"], ["in", st.in, "intelligence: spellcasting for most roles"],
    ["wi", st.wi, "wisdom: power regeneration, spellcasting for priests and healers"], ["ch", st.ch, "charisma: shop prices"],
  ]
  const hunger = st.hunger && !/^not hungry$/i.test(st.hunger) ? st.hunger : null
  return (
    <Panel
      title={<><Activity className="size-3.5" /> vitals</>}
      right={<span className="normal-case tracking-normal truncate max-w-[220px]">{st.name} {st.title}</span>}
    >
      <div className="space-y-2">
        <Meter label="hp" cur={st.hp} max={st.hpmax} tip="hit points: at 0 the character dies. Prayer can restore them when they get very low" />
        <Meter label="pw" cur={st.pw} max={st.pwmax} tip="power: the energy spent to cast spells" />
        <div className="grid grid-cols-3 gap-1.5">
          <Stat label="dlvl" value={st.dlvl ?? "--"} t="frost-2" tip="dungeon level: how deep the character is. Deeper levels have tougher monsters" />
          <Stat label="ac" value={st.ac ?? "--"} tip="armor class: lower is better. Below 0 also reduces damage taken" />
          <Stat label="xl" tip="experience level / experience points" value={<>{st.xl ?? "--"}<span className="text-xs text-muted-foreground">/{st.exp ?? 0}</span></>} />
          <Stat label="turn" value={num(st.turn)} tip="game turns elapsed" />
          <Stat label="gold" value={num(st.gold)} t="yellow" tip="gold carried: buys from shops and protection from temple priests" />
          <Stat label="align" tip="alignment: which god answers prayers. Co-aligned altars and priests help" value={<span className="text-sm uppercase tracking-wider">{st.align ?? "--"}</span>} />
        </div>
        <div className="grid grid-cols-6 border border-border">
          {attrs.map(([k, v, tip]) => (
            <Tip key={k} tip={tip}>
            <div className="text-center py-0.5 border-r border-border last:border-r-0">
              <Label>{k}</Label>
              <div className="text-sm font-medium">{v ?? "--"}</div>
            </div>
            </Tip>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5 min-h-5">
          {hunger && <Tip tip="Hungry: eat soon. Weak: fix it now (eat or pray). Fainting: passes out at random, often fatal"><span><Tag t={hungerTone(hunger)}>{hunger}</Tag></span></Tip>}
          {st.conditions.map((c) => <Tag key={c} t="red">{c}</Tag>)}
          {!hunger && st.conditions.length === 0 && <Tag t="green">nominal</Tag>}
        </div>
      </div>
    </Panel>
  )
}

// ---------- decision ----------

function DecisionPanel({ s }: { s: State }) {
  const d = s.decision
  const [wrap, setWrap] = useState(() => { try { return localStorage.getItem("wrap") === "1" } catch { return false } })
  const [tab, setTab] = useState(() => { try { return localStorage.getItem("tab") ?? "options" } catch { return "options" } })
  const pickTab = (t: string) => { setTab(t); try { localStorage.setItem("tab", t) } catch { /* private mode */ } }
  const toggleWrap = () => { setWrap(!wrap); try { localStorage.setItem("wrap", wrap ? "0" : "1") } catch { /* private mode */ } }
  const io = s.jev.last
  const lastNums = useRef({ conf: "----", lat: "-----" })  // shown muted while thinking, so the header does not blink
  if (d && !d.pending) lastNums.current = { conf: pct(d.confidence), lat: ms(d.latency_ms) }
  const numTone = d?.pending ? "text-muted-foreground" : "text-foreground"
  if (!d) {
    return <Panel title="jev // decision"><div className="text-sm text-muted-foreground">awaiting first decision...</div></Panel>
  }
  return (
    <Panel
      className="min-h-0" bodyClass="min-h-0 overflow-auto"
      title={<><Cpu className="size-3.5" /> jev // decision #{d.id}</>}
      right={
        // fixed-width fields so the header doesn't jump between thinking and acting
        <span className="font-mono whitespace-pre tabular-nums">
          <span style={{ color: tone("frost-2") }}>{(d.pending ? "thinking" : "acting").padStart(8)}</span>
          {" · "}
          <Tip tip="confidence: how decisively Jev preferred its choice over the alternatives">
            <span>conf <span className={numTone}>{lastNums.current.conf.padStart(4)}</span></span>
          </Tip>
          {" "}
          <Tip tip="latency: time Jev took to answer">
            <span>lat <span className={numTone}>{lastNums.current.lat.padStart(5)}</span></span>
          </Tip>
        </span>
      }
    >
      <Tabs value={tab} onValueChange={pickTab}>
        <TabsList variant="line" className="w-full justify-start mb-2">
          <TabsTrigger value="options" className="flex-none" title="the actions the bot offered, with Jev's probability for each">options ({d.options.length})</TabsTrigger>
          <TabsTrigger value="question" className="flex-none" title="the question asked of Jev">instructions</TabsTrigger>
          <TabsTrigger value="state" className="flex-none" title="the game state as text, as Jev read it">state text</TabsTrigger>
          <TabsTrigger value="request" className="flex-none" title="the raw JSON sent to Jev and its reply">request</TabsTrigger>
          <Tip tip="wrap long lines in state text and request">
            <Button size="xs" variant="ghost" className="ml-auto text-muted-foreground" onClick={toggleWrap}><WrapText /> wrap {wrap ? "on" : "off"}</Button>
          </Tip>
          {tab === "state" && <Copy text={d.state_text} tip="copy the state text to the clipboard" />}
        </TabsList>
        <TabsContent value="options" className="space-y-1">
          <div className="text-sm text-muted-foreground mb-2 line-clamp-3" title={d.question}>{d.question}</div>
          {[...d.options].sort((a, b) => (b.p ?? -1) - (a.p ?? -1)).map((o) => {
            const chosen = o.id === d.choice
            return (
              <div
                key={o.id}
                className="grid grid-cols-[14px_minmax(0,1fr)_minmax(80px,32%)_48px] items-center gap-2 pr-2 py-1"
              >
                {chosen ? <ChevronRight className="size-3.5 text-primary" /> : <span />}
                <div className="min-w-0">
                  <div className={cn("text-ui truncate", chosen && "text-primary")}>
                    {o.label} <span className="text-label text-muted-foreground">[{o.id}]</span>
                  </div>
                  {o.detail && <div className="text-label text-muted-foreground truncate">{o.detail}</div>}
                </div>
                <div className="h-2 bg-background border border-border relative overflow-hidden">
                  {d.pending || o.p == null
                    ? <div className="absolute inset-0 bg-[hsl(var(--smui-surface-2))]" />
                    : <div
                        className={cn("h-full", chosen ? "bg-primary" : "bg-[hsl(var(--smui-frost-4))]")}
                        style={{ width: `${o.p * 100}%` }}
                      />}
                </div>
                <span className={cn("text-ui tabular-nums text-right", chosen ? "text-primary font-semibold" : "text-muted-foreground")}>
                  {d.pending ? "..." : pct(o.p)}
                </span>
              </div>
            )
          })}
        </TabsContent>
        <TabsContent value="question">
          <pre className="text-xs whitespace-pre-wrap bg-background border border-border p-2 overflow-auto">{d.question}</pre>
        </TabsContent>
        <TabsContent value="state">
          <pre className={cn("text-xs bg-background border border-border p-2 overflow-auto", wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre")}>{d.state_text}</pre>
        </TabsContent>
        <TabsContent value="request" className="space-y-2">
          {!io ? <div className="text-sm text-muted-foreground">no request sent yet</div> : <>
            {/* always one line of text, so the JSON boxes below never shift */}
            <div className="text-xs text-muted-foreground truncate">
              {io.request.state === d.state_text ? "the call for this decision"
                : d.pending ? "waiting for Jev; showing the previous call" : "one option, Jev not asked; showing the previous call"}</div>
            <div className="flex items-center justify-between"><Label>request</Label><Copy text={JSON.stringify(io.request, null, 2)} tip="copy the request JSON to the clipboard" /></div>
            <Json v={io.request} wrap={wrap} />
            <div className="flex items-center justify-between"><Label>response</Label><Copy text={JSON.stringify(io.response, null, 2)} tip="copy the response JSON to the clipboard" /></div>
            <Json v={io.response} wrap={wrap} />
          </>}
        </TabsContent>
      </Tabs>
    </Panel>
  )
}

// ---------- timeline ----------

function Sparkline({ s }: { s: State }) {
  const h = s.history.slice(-60)
  const W = 300, H = 56
  const bw = W / 60
  const maxLat = Math.max(1, ...h.map((x) => x.latency_ms))
  const pts = h.map((x, i) => `${(i + 0.5) * bw},${H - (x.latency_ms / maxLat) * (H - 4) - 2}`).join(" ")
  return (
    <div>
      <div className="flex justify-between mb-1">
        <Label className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 bg-primary/70" /> confidence</Label>
        <Label className="flex items-center gap-1.5"><span className="inline-block w-3 h-px bg-[hsl(var(--smui-yellow))]" /> latency (max {ms(maxLat)})</Label>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-10 bg-background border border-border">
        {h.map((x, i) => (
          <rect
            key={x.id} x={i * bw + 0.5} width={bw - 1} y={H - x.confidence * H} height={x.confidence * H}
            fill={tone(fracTone(x.confidence) === "green" ? "frost-2" : fracTone(x.confidence))} opacity={0.65}
          >
            <title>{`#${x.id} T:${x.turn} conf ${pct(x.confidence)} lat ${ms(x.latency_ms)}`}</title>
          </rect>
        ))}
        <polyline points={pts} fill="none" stroke={tone("yellow")} strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}

function Timeline({ s }: { s: State }) {
  const rows = [...s.history].reverse()
  return (
    <Panel
      title={<><Footprints className="size-3.5" /> decision timeline</>} right={<span>{s.history.length} logged</span>}
      className="flex-1 min-h-[180px]" bodyClass="flex-1 min-h-0 flex flex-col"
    >
      <Sparkline s={s} />
      <div className="mt-2 flex-1 min-h-0 overflow-auto border border-border">
        <table className="w-full text-ui">
          <thead className="sticky top-0 bg-card">
            <tr className="text-label text-muted-foreground uppercase tracking-wider text-left">
              <th className="px-2 py-1.5 font-normal" title="game turn">t</th>
              <th className="px-2 py-1.5 font-normal" title="dungeon level">dl</th>
              <th className="px-2 py-1.5 font-normal" title="the action chosen">choice</th>
              <th className="px-2 py-1.5 font-normal text-right" title="Jev's probability for the chosen action">p</th>
              <th className="px-2 py-1.5 font-normal text-right" title="confidence: margin over the alternatives">conf</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.id} className="border-t border-border/50 hover:bg-[hsl(var(--smui-frost-2)/0.03)]">
                <td className="px-2 py-1 text-muted-foreground tabular-nums">{x.turn}</td>
                <td className="px-2 py-1 text-muted-foreground tabular-nums">{x.dlvl}</td>
                <td className="px-2 py-1 max-w-0 w-full">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="truncate">{x.label}</div>
                    </TooltipTrigger>
                    <TooltipContent>{`#${x.id} ${x.choice} // ${x.n_options} opts // ${ms(x.latency_ms)} // ${hhmmss(x.at)}`}</TooltipContent>
                  </Tooltip>
                </td>
                <td className="px-2 py-1 text-right tabular-nums">{pct(x.p)}</td>
                <td className="px-2 py-1 text-right tabular-nums" style={{ color: tone(fracTone(x.confidence)) }}>{pct(x.confidence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

// ---------- feeds ----------

function Feeds({ s }: { s: State }) {
  return (
    <Card className="card-glow min-w-0 flex-1 min-h-0">
      <FeedTabs s={s} max={<Max title="feeds" bodyClass="p-0"><FeedTabs s={s} /></Max>} />
    </Card>
  )
}

function FeedTabs({ s, max }: { s: State; max?: ReactNode }) {
  const lvl: Record<string, Tone> = { info: "frost-3", warn: "yellow", error: "red" }
  return (
      <Tabs defaultValue="messages" className="gap-0 flex-1 min-h-0">
        <TabsList variant="line" className="w-full justify-start px-1.5 h-9 shrink-0">
          <TabsTrigger value="messages" className="flex-none">game messages</TabsTrigger>
          <TabsTrigger value="log" className="flex-none">
            harness log {s.log.some((l) => l.level === "error") && <Dot t="red" />}
          </TabsTrigger>
          <TabsTrigger value="runs" className="flex-none">runs ({s.runs.length})</TabsTrigger>
          {max && <span className="ml-auto pr-1.5 flex">{max}</span>}
        </TabsList>
        <TabsContent value="messages" className="p-0 min-h-0 overflow-auto">
          <div className="p-2 space-y-0.5">
            {[...s.messages].reverse().map((m, i) => (
              <div key={i} className={cn("text-ui flex gap-3", i === 0 ? "text-foreground" : "text-muted-foreground")}>
                <span className="text-label text-muted-foreground tabular-nums w-12 shrink-0 pt-px">T:{m.turn}</span>
                <span>{m.text}</span>
              </div>
            ))}
          </div>
        </TabsContent>
        <TabsContent value="log" className="p-0 min-h-0 overflow-auto">
          <div className="p-2 space-y-0.5">
            {[...s.log].reverse().map((l, i) => (
              <div key={i} className="text-ui flex gap-3">
                <span className="text-label text-muted-foreground tabular-nums shrink-0 pt-px">{hhmmss(l.at)}</span>
                <span className="text-label uppercase w-10 shrink-0 pt-px" style={{ color: tone(lvl[l.level] ?? "muted") }}>{l.level}</span>
                <span className="text-muted-foreground break-words min-w-0">{l.text}</span>
              </div>
            ))}
          </div>
        </TabsContent>
        <TabsContent value="runs" className="p-0 min-h-0 overflow-auto"><Runs s={s} /></TabsContent>
      </Tabs>
  )
}

// ---------- orders / telemetry / level / inventory / runs ----------

function Orders({ s }: { s: State }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const text = draft ?? s.order
  const send = async () => {
    await control({ action: "order", text })
    setDraft(null)
    setSent(true)
    setTimeout(() => setSent(false), 1500)
  }
  return (
    <Panel
      title={<><Send className="size-3.5" /> standing orders</>}
      right={draft != null ? <Tag t="yellow">unsent</Tag> : <span className="normal-case tracking-normal">ctrl+enter to send</span>}
      bodyClass="p-1.5 flex gap-1.5 items-stretch"
    >
      <Textarea
        value={text}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send() }}
        placeholder="e.g. prioritize finding the downstairs"
        rows={2}
        className="text-xs min-h-0 py-1 resize-none flex-1"
      />
      <Button size="sm" className="h-auto" onClick={send} disabled={draft == null}>
        <Send /> {sent ? "sent" : "transmit"}
      </Button>
    </Panel>
  )
}

function Telemetry({ s }: { s: State }) {
  const j = s.jev
  const used = j.budget_usd ? j.cost_usd / j.budget_usd : 0
  return (
    <Panel title={<><Cpu className="size-3.5" /> jev telemetry</>} right={<span className="normal-case tracking-normal">{j.last_model ?? "--"}</span>}>
      <div className="grid grid-cols-3 gap-1.5">
        <Stat label="calls" value={num(j.calls)} tip="requests sent to the Jev model, all games" />
        <Stat label="errors" value={num(j.errors)} t={j.errors ? "red" : undefined} tip="failed model requests (timeouts, HTTP errors)" />
        <Stat label="avg lat" value={ms(j.avg_latency_ms)} tip="average round-trip time of a model request" />
      </div>
      <Tip tip="model spend so far against the configured budget">
      <div className="mt-2">
        <div className="flex items-baseline justify-between mb-1">
          <Label>cost // budget</Label>
          <span className="text-sm tabular-nums">
            <span style={{ color: tone(used > 0.9 ? "red" : used > 0.7 ? "yellow" : "green") }}>${j.cost_usd.toFixed(4)}</span>
            <span className="text-muted-foreground"> / ${j.budget_usd.toFixed(2)}</span>
          </span>
        </div>
        <Bar value={used} t={used > 0.9 ? "red" : used > 0.7 ? "yellow" : "frost-2"} />
      </div>
      </Tip>
    </Panel>
  )
}

function LevelInfo({ s }: { s: State }) {
  const l = s.level
  return (
    <Panel title={<><MapIcon className="size-3.5" /> level {l.dlvl}</>} right={<Tip tip="share of this level's map the bot has seen"><span>{pct(l.explored)} explored</span></Tip>}>
      <Bar value={l.explored} t="frost-2" />
      <div className="flex gap-1.5 mt-2">
        <Tag t={l.downstairs ? "green" : "muted"}>&gt; down {l.downstairs ? "known" : "unknown"}</Tag>
        <Tag t={l.upstairs ? "green" : "muted"}>&lt; up {l.upstairs ? "known" : "unknown"}</Tag>
      </div>
    </Panel>
  )
}

function Inventory({ s }: { s: State }) {
  return (
    <Panel
      title={<><Package className="size-3.5" /> inventory</>} right={<span>{s.inventory.length} items</span>}
      className="flex-1 min-h-0" bodyClass="flex-1 min-h-0 overflow-auto"
    >
      <div>
        {s.inventory.map((it) => (
          <Fragment key={it.letter}>
          <div className="flex items-center gap-2.5 py-0.5 border-b border-border/50 last:border-b-0 text-ui">
            <span className="w-5 h-5 flex items-center justify-center border border-border bg-background text-primary text-xs shrink-0">
              {it.letter}
            </span>
            <span className="truncate" title={it.text}>{it.text}</span>
          </div>
          {it.contents?.map((c, i) => (
            <div key={i} className="pl-7.5 py-0.5 text-ui text-muted-foreground truncate" title={`Inside ${it.letter}: ${c}`}>└ {c}</div>
          ))}
          </Fragment>
        ))}
        {s.inventory.length === 0 && <div className="text-sm text-muted-foreground">empty</div>}
      </div>
    </Panel>
  )
}

// max Dlvl of each finished game (restarts of one game share the death), with a 10-game moving average to show the trend
function DlvlTrend({ runs }: { runs: State["runs"] }) {
  const g = runs.filter((r) => r.death)
  if (g.length < 2) return null
  const W = 300, H = 40, top = Math.max(...g.map((r) => r.max_dlvl)), bw = W / g.length
  const y = (d: number) => H - (d / top) * (H - 2)
  const avg = g.map((_, i) => { const w = g.slice(Math.max(0, i - 9), i + 1); return w.reduce((a, r) => a + r.max_dlvl, 0) / w.length })
  return (
    <div className="px-2 pt-1">
      <div className="flex justify-between mb-0.5">
        <Tip tip="max dungeon level of each finished game, oldest on the left"><Label className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 bg-primary/70" /> max dlvl ({g.length} games, best {top})</Label></Tip>
        <Tip tip="average max dlvl of the last 10 games: a rising line means the bot improves"><Label className="flex items-center gap-1.5"><span className="inline-block w-3 h-px bg-[hsl(var(--smui-yellow))]" /> 10-game avg {avg[avg.length - 1].toFixed(1)}</Label></Tip>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-10 bg-background border border-border">
        {g.map((r, i) => (
          <rect key={r.id} x={i * bw} width={Math.max(bw - 0.3, 0.3)} y={y(r.max_dlvl)} height={H - y(r.max_dlvl)} fill={tone("frost-2")} opacity={0.6}>
            <title>{`${r.id} Dlvl ${r.max_dlvl} T:${r.turns} ${r.death}`}</title>
          </rect>
        ))}
        <polyline points={avg.map((a, i) => `${(i + 0.5) * bw},${y(a)}`).join(" ")} fill="none" stroke={tone("yellow")} strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}

function Runs({ s }: { s: State }) {
  return (
      <div>
        <DlvlTrend runs={s.runs} />
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>character</TableHead>
              <TableHead>engine</TableHead>
              <TableHead className="text-right">turns</TableHead>
              <TableHead className="text-right">t/s</TableHead>
              <TableHead className="text-right">dlvl</TableHead>
              <TableHead>fate</TableHead>
              <TableHead className="text-right">score</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow className="bg-[hsl(var(--smui-frost-2)/0.05)]">
              <TableCell className="text-primary">{s.run.character}</TableCell>
              <TableCell className="text-muted-foreground">{engine(s.run)}</TableCell>
              <TableCell className="text-right tabular-nums">{num(s.status.turn)}</TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">{tps(s.status.turn, s.run.started)}</TableCell>
              <TableCell className="text-right tabular-nums">{s.run.max_dlvl}</TableCell>
              <TableCell><Badge variant="outline" className="text-[hsl(var(--smui-green))] border-[hsl(var(--smui-green)/0.3)]">live</Badge></TableCell>
              <TableCell className="text-right text-muted-foreground">{s.run.decisions} dec</TableCell>
            </TableRow>
            {[...s.runs].reverse().map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.character}</TableCell>
                <TableCell className="text-muted-foreground">{engine(r)}</TableCell>
                <TableCell className="text-right tabular-nums">{num(r.turns)}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">{tps(r.turns, r.started, r.ended)}</TableCell>
                <TableCell className="text-right tabular-nums">{r.max_dlvl}</TableCell>
                <TableCell className="max-w-[220px] truncate" title={r.death ?? ""}>
                  <span className={r.death ? "text-[hsl(var(--smui-red))]" : "text-muted-foreground"}>{r.death ?? (r.ended ? "ended" : "--")}</span>
                </TableCell>
                <TableCell className="text-right tabular-nums text-primary">{r.score == null ? "--" : num(r.score)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
  )
}

// ---------- page ----------

// version strings the engine reported (jev-1.13.0); a game continued on another engine shows both
// Panes separated by invisible 6px drag handles (the old gap). Sizes are flex-grow ratios saved per
// split (0 = natural size); until a split has sizes its panes use display:contents, i.e. their natural layout.
function Split({ id, row, init, className, children }: {
  id: string; row?: boolean; init?: number[]; className?: string; children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [sizes, setSizes] = useState<number[] | undefined>(() => {
    try { return JSON.parse(localStorage.getItem("split:" + id) ?? "null") ?? init } catch { return init }
  })
  const drag = (i: number) => (e: React.PointerEvent) => {
    e.preventDefault()
    const panes = [...ref.current!.children].filter((_, k) => k % 2 == 0)
    const px = panes.map(p => { const r = (p.firstElementChild ?? p).getBoundingClientRect(); return row ? r.width : r.height })
    const pos = (ev: { clientX: number; clientY: number }) => row ? ev.clientX : ev.clientY
    const start = pos(e), pair = px[i] + px[i + 1]
    const move = (ev: PointerEvent) => {
      const a = Math.min(Math.max(px[i] + pos(ev) - start, 40), pair - 40)
      const next = [...px]; next[i] = a; next[i + 1] = pair - a
      setSizes(next)
      try { localStorage.setItem("split:" + id, JSON.stringify(next)) } catch { /* private mode */ }
    }
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up) }
    addEventListener("pointermove", move); addEventListener("pointerup", up)
  }
  useEffect(() => {
    const reset = () => { try { localStorage.removeItem("split:" + id) } catch { /* private mode */ } setSizes(init) }
    addEventListener("split-reset", reset)
    return () => removeEventListener("split-reset", reset)
  }, [id, init])
  const kids = Children.toArray(children)
  return (
    <div ref={ref} className={cn("flex min-h-0 min-w-0", row ? "flex-row" : "flex-col", className)}>
      {kids.flatMap((c, i) => [
        <div key={i} className={sizes ? "flex flex-col min-h-0 min-w-0 overflow-hidden [&>*]:flex-1 [&>*]:min-h-0" : "contents"}
          style={sizes ? { flex: sizes[i] ? `${sizes[i]} 1 0` : "none" } : undefined}>{c}</div>,
        i < kids.length - 1 && <div key={"h" + i} onPointerDown={drag(i)}
          className={cn("shrink-0 touch-none", row ? "w-1.5 cursor-col-resize" : "h-1.5 cursor-row-resize")} />,
      ])}
    </div>
  )
}

const engine = (r: { engine?: string; models?: string[] }) => r.models?.length ? r.models.join(" → ") : r.engine ?? "--"

export default function App() {
  const [s, conn] = useJevState()
  return (
    // fills the viewport (sized for a 1512x780 laptop window); long lists scroll inside their panels
    <main className="h-screen flex flex-col overflow-hidden">
      <Header s={s} conn={conn} />
      <Split id="cols" row init={[520, 640, 340]} className="flex-1 p-1.5">
        <Split id="left" init={[48, 52]}>
          <Panel
            title={<>terminal // {s.status.name ?? "agent"}</>}
            right={<><span>dlvl {s.status.dlvl ?? "--"}</span><span>t:{s.status.turn ?? "--"}</span></>}
            bodyClass="p-0 flex-1 min-h-0 flex flex-col"
            className={cn(s.phase === "dead" && "border-[hsl(var(--smui-red)/0.6)]")}
          >
            <Terminal screen={s.screen} />
          </Panel>
          <Feeds s={s} />
        </Split>
        {/* fixed ratios so the decision panel doesn't resize with its option count */}
        <Split id="mid3" init={[0, 45, 55]}>
          <Orders s={s} />
          <DecisionPanel s={s} />
          <Timeline s={s} />
        </Split>
        <Split id="right">
          <Vitals s={s} />
          <Telemetry s={s} />
          <LevelInfo s={s} />
          <Inventory s={s} />
        </Split>
      </Split>
    </main>
  )
}
