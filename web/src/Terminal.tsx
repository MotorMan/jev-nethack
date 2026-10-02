import { memo } from "react"
import type { Run, State } from "./types"

// pyte color name -> [normal, bright]. Nord-leaning but keeps NetHack's hue semantics
// (brown != yellow; bold brown = yellow).
const PALETTE: Record<string, [string, string]> = {
  black: ["#4c566a", "#6b7589"],
  red: ["#bf616a", "#e0808a"],
  green: ["#8fae74", "#b4d99a"],
  brown: ["#c08457", "#ebcb8b"],
  blue: ["#5e81ac", "#81a1ff"],
  magenta: ["#b48ead", "#d8a6e8"],
  cyan: ["#6fb3c4", "#8fe0ef"],
  white: ["#c4ccd8", "#ffffff"],
  default: ["#c4ccd8", "#eceff4"],
}
const TERM_BG = "#0f1216"

function color(name: string | null, bold: boolean, isBg: boolean): string | undefined {
  if (!name || name === "default") return isBg ? undefined : PALETTE.default[bold ? 1 : 0]
  if (/^[0-9a-f]{6}$/i.test(name)) return `#${name}`
  const p = PALETTE[name]
  return p ? p[bold && !isBg ? 1 : 0] : undefined
}

function runStyle([, fg, bg, bold, reverse]: Run): React.CSSProperties {
  let f = color(fg, bold, false)
  let b = color(bg, false, true)
  if (reverse) [f, b] = [b ?? TERM_BG, f]
  return { color: f, backgroundColor: b, fontWeight: bold ? 700 : undefined }
}

export const Terminal = memo(function Terminal({ screen }: { screen: State["screen"] }) {
  const { rows, cols, lines } = screen
  // ponytail: assumes cursor is [col, row] (pyte cursor.x, cursor.y).
  const [cx, cy] = screen.cursor
  return (
    // container query units scale the grid to the panel width: cols * --ch em = 100cqw (--ch is the font advance, set per mode in index.css)
    <div className="term p-2" style={{ containerType: "inline-size" }}>
      <div style={{ fontSize: `calc(100cqw / (${cols} * var(--ch) + 0.5))`, lineHeight: 1.2 }} className="relative">
        <pre>
          {Array.from({ length: lines }, (_, y) => (
            <div key={y} style={{ height: "1.2em" }}>
              {(rows[y] ?? []).map((r, i) => (
                <span key={i} style={runStyle(r)}>{r[0]}</span>
              ))}
            </div>
          ))}
        </pre>
        <span
          className="term-cursor absolute bg-[#88c0d0]/70"
          style={{ left: `calc(${cx}em * var(--ch))`, top: `${cy * 1.2}em`, width: "calc(1em * var(--ch))", height: "1.2em" }}
        />
      </div>
    </div>
  )
})
