import { useEffect, useState, type ReactNode } from "react"
import {
  Activity, ChevronRight, Cpu, Footprints, Map as MapIcon, Moon, Package, Pause, Play, RotateCcw,
  Send, StepForward, Sun, Swords, Wifi, WifiOff,
} from "lucide-react"
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

function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("text-label text-muted-foreground tracking-[1.5px] uppercase block", className)}>{children}</span>
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
        {right && <CardDescription className="text-xs text-muted-foreground flex items-center gap-2">{right}</CardDescription>}
      </CardHeader>
      <CardContent className={cn("p-2.5", bodyClass)}>{children}</CardContent>
    </Card>
  )
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
        <Tag t={s.mode === "hardfought" ? "purple" : "frost-2"}>{s.mode}</Tag>
        <div className="flex items-center gap-1.5 text-label uppercase tracking-wider" style={{ color: tone(connTone) }}>
          {conn === "offline" ? <WifiOff className="size-3.5" /> : <Wifi className="size-3.5" />}
          {connText}
        </div>

        <div className="flex flex-wrap items-center gap-2 ml-auto">
          <Button size="sm" variant={s.paused ? "default" : "outline"} onClick={() => control({ action: s.paused ? "resume" : "pause" })}>
            {s.paused ? <Play /> : <Pause />}
            {s.paused ? "resume" : "pause"}
          </Button>
          <Button size="sm" variant="outline" disabled={!s.paused} onClick={() => control({ action: "step" })}>
            <StepForward /> step
          </Button>
          <Button
            size="sm" variant="outline"
            onClick={() => confirm("Abandon the current game and start a new one?") && control({ action: "new_game" })}
          >
            <RotateCcw /> new game
          </Button>
          <div className="flex items-center gap-2 pl-2 w-[210px]">
            <Label className="whitespace-nowrap w-[88px]">delay {delay}ms</Label>
            <Slider
              min={0} max={2000} step={50} value={[delay]} className="flex-1"
              onValueChange={([v]) => setDrag(v)}
              onValueCommit={([v]) => { setDrag(null); control({ action: "speed", delay_ms: v }) }}
            />
          </div>
          <Button size="icon" variant="ghost" className="size-8" onClick={() => setDark(!dark)} aria-label="toggle theme">
            {dark ? <Sun /> : <Moon />}
          </Button>
        </div>
      </div>
      <div className="h-px bg-gradient-to-r from-transparent via-primary/60 to-transparent" />
    </nav>
  )
}

// ---------- vitals ----------

function Stat({ label, value, t }: { label: string; value: ReactNode; t?: Tone }) {
  return (
    <div className="bg-background border border-border px-2 py-1 min-w-0">
      <Label>{label}</Label>
      <div className="text-lg font-medium tracking-tight leading-tight truncate" style={t ? { color: tone(t) } : undefined}>
        {value}
      </div>
    </div>
  )
}

function Meter({ label, cur, max }: { label: string; cur?: number; max?: number }) {
  const f = cur != null && max ? cur / max : 0
  const t = fracTone(f)
  return (
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
  const attrs: [string, ReactNode][] = [["st", st.st], ["dx", st.dx], ["co", st.co], ["in", st.in], ["wi", st.wi], ["ch", st.ch]]
  const hunger = st.hunger && st.hunger !== "Not Hungry" ? st.hunger : null
  return (
    <Panel
      title={<><Activity className="size-3.5" /> vitals</>}
      right={<span className="normal-case tracking-normal truncate max-w-[220px]">{st.name} {st.title}</span>}
    >
      <div className="space-y-2">
        <Meter label="hp" cur={st.hp} max={st.hpmax} />
        <Meter label="pw" cur={st.pw} max={st.pwmax} />
        <div className="grid grid-cols-3 gap-1.5">
          <Stat label="dlvl" value={st.dlvl ?? "--"} t="frost-2" />
          <Stat label="ac" value={st.ac ?? "--"} />
          <Stat label="xl" value={<>{st.xl ?? "--"}<span className="text-xs text-muted-foreground">/{st.exp ?? 0}</span></>} />
          <Stat label="turn" value={num(st.turn)} />
          <Stat label="gold" value={num(st.gold)} t="yellow" />
          <Stat label="align" value={<span className="text-sm uppercase tracking-wider">{st.align ?? "--"}</span>} />
        </div>
        <div className="grid grid-cols-6 border border-border">
          {attrs.map(([k, v]) => (
            <div key={k} className="text-center py-0.5 border-r border-border last:border-r-0">
              <Label>{k}</Label>
              <div className="text-sm font-medium">{v ?? "--"}</div>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5 min-h-5">
          {hunger && <Tag t={hungerTone(hunger)}>{hunger}</Tag>}
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
  if (!d) {
    return <Panel title="jev // decision"><div className="text-sm text-muted-foreground">awaiting first decision...</div></Panel>
  }
  return (
    <Panel
      className="min-h-0" bodyClass="min-h-0 overflow-auto"
      title={<><Cpu className="size-3.5" /> jev // decision #{d.id}</>}
      right={
        d.pending
          ? <span className="flex items-center gap-1.5 text-[hsl(var(--smui-frost-2))]"><Dot t="frost-2" pulse /> thinking</span>
          : <>
              <span>conf <span className="text-foreground">{pct(d.confidence)}</span></span>
              <span>lat <span className="text-foreground">{ms(d.latency_ms)}</span></span>
            </>
      }
    >
      <Tabs defaultValue="options">
        <TabsList variant="line" className="w-full justify-start mb-2">
          <TabsTrigger value="options" className="flex-none">options ({d.options.length})</TabsTrigger>
          <TabsTrigger value="question" className="flex-none">instructions</TabsTrigger>
          <TabsTrigger value="state" className="flex-none">state text</TabsTrigger>
        </TabsList>
        <TabsContent value="options" className="space-y-1">
          <div className="text-sm text-muted-foreground mb-2 line-clamp-3" title={d.question}>{d.question}</div>
          {d.options.map((o) => {
            const chosen = o.id === d.choice
            return (
              <div
                key={o.id}
                className={cn(
                  "grid grid-cols-[14px_minmax(0,1fr)_minmax(80px,32%)_48px] items-center gap-2 px-2 py-1 border-l-2",
                  chosen ? "border-primary bg-[hsl(var(--smui-frost-2)/0.07)]" : "border-transparent",
                )}
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
          <pre className="text-xs whitespace-pre bg-background border border-border p-2 overflow-auto">{d.state_text}</pre>
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
              <th className="px-2 py-1.5 font-normal">t</th>
              <th className="px-2 py-1.5 font-normal">dl</th>
              <th className="px-2 py-1.5 font-normal">choice</th>
              <th className="px-2 py-1.5 font-normal text-right">p</th>
              <th className="px-2 py-1.5 font-normal text-right">conf</th>
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
  const lvl: Record<string, Tone> = { info: "frost-3", warn: "yellow", error: "red" }
  return (
    <Card className="card-glow min-w-0 flex-1 min-h-0">
      <Tabs defaultValue="messages" className="gap-0 flex-1 min-h-0">
        <TabsList variant="line" className="w-full justify-start px-1.5 h-9 shrink-0">
          <TabsTrigger value="messages" className="flex-none">game messages</TabsTrigger>
          <TabsTrigger value="log" className="flex-none">
            harness log {s.log.some((l) => l.level === "error") && <Dot t="red" />}
          </TabsTrigger>
          <TabsTrigger value="runs" className="flex-none">runs ({s.runs.length})</TabsTrigger>
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
    </Card>
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
    <Panel title={<><Send className="size-3.5" /> standing orders</>} right={draft != null && <Tag t="yellow">unsent</Tag>}>
      <Label className="mb-1">current</Label>
      <div className="text-xs text-primary px-2 py-1 bg-background border border-border mb-2 whitespace-pre-wrap max-h-16 overflow-auto">
        {s.order || <span className="text-muted-foreground">none</span>}
      </div>
      <Label className="mb-1">new order</Label>
      <Textarea
        value={text}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send() }}
        placeholder="e.g. prioritize finding the downstairs"
        className="text-xs min-h-[48px]"
      />
      <div className="flex items-center justify-between mt-1.5">
        <span className="text-label text-muted-foreground tracking-wider">ctrl+enter to send</span>
        <Button size="sm" onClick={send} disabled={draft == null}>
          <Send /> {sent ? "sent" : "transmit"}
        </Button>
      </div>
    </Panel>
  )
}

function Telemetry({ s }: { s: State }) {
  const j = s.jev
  const used = j.budget_usd ? j.cost_usd / j.budget_usd : 0
  return (
    <Panel title={<><Cpu className="size-3.5" /> jev telemetry</>} right={<span className="normal-case tracking-normal">{j.last_model ?? "--"}</span>}>
      <div className="grid grid-cols-3 gap-1.5">
        <Stat label="calls" value={num(j.calls)} />
        <Stat label="errors" value={num(j.errors)} t={j.errors ? "red" : undefined} />
        <Stat label="avg lat" value={ms(j.avg_latency_ms)} />
      </div>
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
    </Panel>
  )
}

function LevelInfo({ s }: { s: State }) {
  const l = s.level
  return (
    <Panel title={<><MapIcon className="size-3.5" /> level {l.dlvl}</>} right={<span>{pct(l.explored)} explored</span>}>
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
          <div key={it.letter} className="flex items-center gap-2.5 py-0.5 border-b border-border/50 last:border-b-0 text-ui">
            <span className="w-5 h-5 flex items-center justify-center border border-border bg-background text-primary text-xs shrink-0">
              {it.letter}
            </span>
            <span className="truncate" title={it.text}>{it.text}</span>
          </div>
        ))}
        {s.inventory.length === 0 && <div className="text-sm text-muted-foreground">empty</div>}
      </div>
    </Panel>
  )
}

function Runs({ s }: { s: State }) {
  return (
      <div>
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
const engine = (r: { engine?: string; models?: string[] }) => r.models?.length ? r.models.join(" → ") : r.engine ?? "--"

export default function App() {
  const [s, conn] = useJevState()
  return (
    // fills the viewport (sized for a 1512x780 laptop window); long lists scroll inside their panels
    <main className="h-screen flex flex-col overflow-hidden">
      <Header s={s} conn={conn} />
      <div className="flex-1 min-h-0 p-1.5 grid grid-cols-[520px_minmax(0,1fr)_340px] gap-1.5">
        <div className="flex flex-col gap-1.5 min-h-0 min-w-0">
          <Panel
            title={<>terminal // {s.status.name ?? "agent"}</>}
            right={<><span>dlvl {s.status.dlvl ?? "--"}</span><span>t:{s.status.turn ?? "--"}</span></>}
            bodyClass="p-0"
            className={cn("shrink-0", s.phase === "dead" && "border-[hsl(var(--smui-red)/0.6)]")}
          >
            <Terminal screen={s.screen} />
          </Panel>
          <Feeds s={s} />
        </div>
        <div className="flex flex-col gap-1.5 min-h-0 min-w-0">
          <DecisionPanel s={s} />
          <Timeline s={s} />
          <Orders s={s} />
        </div>
        <div className="flex flex-col gap-1.5 min-h-0 min-w-0">
          <Vitals s={s} />
          <Telemetry s={s} />
          <LevelInfo s={s} />
          <Inventory s={s} />
        </div>
      </div>
    </main>
  )
}
