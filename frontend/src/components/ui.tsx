import { ReactNode } from 'react'

/* ── Formatting helpers ──────────────────────────────────────────────────── */

// API datetimes arrive as ISO ("...T...") or "YYYY-MM-DD HH:MM:SS+00:00".
export function fmtDateTime(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value.includes('T') ? value : value.replace(' ', 'T'))
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function fmtDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value.includes('T') ? value : value.replace(' ', 'T'))
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

// "3h ago" style relative time for recency cues.
export function fmtRelative(value?: string | null): string {
  if (!value) return ''
  const d = new Date(value.includes('T') ? value : value.replace(' ', 'T'))
  if (isNaN(d.getTime())) return ''
  const s = Math.round((Date.now() - d.getTime()) / 1000)
  if (s < 60) return 'just now'
  const m = Math.round(s / 60); if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60); if (h < 24) return `${h}h ago`
  const days = Math.round(h / 24); if (days < 30) return `${days}d ago`
  return fmtDate(value)
}

/* ── Status / priority tokens ────────────────────────────────────────────── */

const STATUS: Record<string, string> = {
  pending: 'bg-sky-50 text-sky-700 ring-1 ring-sky-100',
  in_progress: 'bg-amber-50 text-amber-700 ring-1 ring-amber-100',
  done: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100',
  blocked: 'bg-violet-50 text-violet-700 ring-1 ring-violet-100',
  escalated: 'bg-rose-50 text-rose-700 ring-1 ring-rose-100',
  missed: 'bg-amber-50 text-amber-700 ring-1 ring-amber-100',
  active: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100',
  paused: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
}
const PRIORITY: Record<string, string> = {
  high: 'bg-rose-50 text-rose-700 ring-1 ring-rose-100',
  medium: 'bg-amber-50 text-amber-700 ring-1 ring-amber-100',
  low: 'bg-slate-100 text-slate-600 ring-1 ring-slate-200',
}

export function StatusBadge({ status, onClick }: { status: string; onClick?: () => void }) {
  return (
    <span onClick={onClick}
      className={`badge ${STATUS[status] || 'bg-slate-100 text-slate-600'} ${onClick ? 'cursor-pointer hover:opacity-80' : ''} capitalize`}>
      {status.replace('_', ' ')}
    </span>
  )
}
export function PriorityBadge({ priority }: { priority: string }) {
  return <span className={`badge ${PRIORITY[priority] || 'bg-slate-100 text-slate-600'} uppercase tracking-wide`}>{priority}</span>
}

/* ── Layout primitives ───────────────────────────────────────────────────── */

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 mb-6">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="muted text-sm mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}

export function Card({ children, className = '', interactive = false, onClick }:
  { children: ReactNode; className?: string; interactive?: boolean; onClick?: () => void }) {
  return (
    <div onClick={onClick} className={`card ${interactive ? 'card-interactive cursor-pointer' : ''} ${className}`}>
      {children}
    </div>
  )
}

export function StatCard({ label, value, icon, accent = 'brand', hint }:
  { label: string; value: ReactNode; icon?: ReactNode; accent?: string; hint?: string }) {
  const tints: Record<string, string> = {
    brand: 'bg-brand-50 text-brand-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    amber: 'bg-amber-50 text-amber-600',
    rose: 'bg-rose-50 text-rose-600',
    sky: 'bg-sky-50 text-sky-600',
  }
  return (
    <Card className="p-5 flex items-start gap-4">
      {icon && <div className={`w-11 h-11 rounded-xl grid place-items-center ${tints[accent] || tints.brand}`}>{icon}</div>}
      <div className="min-w-0">
        <p className="muted text-xs font-semibold uppercase tracking-wide">{label}</p>
        <p className="stat text-2xl font-extrabold mt-1 leading-none">{value}</p>
        {hint && <p className="muted text-xs mt-1">{hint}</p>}
      </div>
    </Card>
  )
}

export function EmptyState({ icon, title, hint, action }:
  { icon?: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <Card className="p-12 text-center">
      {icon && <div className="w-14 h-14 mx-auto rounded-2xl bg-slate-50 grid place-items-center text-slate-300 mb-4">{icon}</div>}
      <h3 className="font-bold text-lg">{title}</h3>
      {hint && <p className="muted text-sm mt-1 max-w-sm mx-auto">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </Card>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-slate-100 ${className}`} />
}
