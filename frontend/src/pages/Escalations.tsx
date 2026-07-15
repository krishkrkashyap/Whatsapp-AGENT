import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { AlertTriangle, CheckCircle, Clock, ShieldCheck } from 'lucide-react'
import { PageHeader, Card, EmptyState, fmtDateTime } from '../components/ui'

interface Escalation {
  id: string; task_id: string | null; employee_id: string;
  employee_name: string; original_query: string;
  bot_attempted_solution: string | null; status: string;
  assigned_to_id: string | null; resolved_at: string | null; created_at: string;
}

export default function Escalations() {
  const [tickets, setTickets] = useState<Escalation[]>([])
  const [filter, setFilter] = useState('all')
  const [loaded, setLoaded] = useState(false)

  const load = () => api.getEscalations(filter !== 'all' ? filter : undefined).then(setTickets).catch(() => {}).finally(() => setLoaded(true))
  useEffect(() => { load() }, [filter])

  const handleResolve = async (id: string) => { try { await api.resolveEscalation(id); load() } catch (e) { alert('Failed. ' + e) } }

  const icon = (s: string) => s === 'open'
    ? <AlertTriangle className="w-5 h-5 text-rose-500" />
    : s === 'in_progress' ? <Clock className="w-5 h-5 text-amber-500" /> : <CheckCircle className="w-5 h-5 text-emerald-500" />
  const badge = (s: string) => ({ open: 'bg-rose-50 text-rose-700', in_progress: 'bg-amber-50 text-amber-700', resolved: 'bg-emerald-50 text-emerald-700' } as Record<string, string>)[s] || 'bg-slate-100 text-slate-600'

  return (
    <div>
      <PageHeader title="Escalations" subtitle="Help requests the bot couldn't resolve."
        actions={
          <div className="flex items-center gap-1 bg-slate-50 dark:bg-slate-800/60 rounded-lg p-1">
            {['all', 'open', 'in_progress', 'resolved'].map(s => (
              <button key={s} onClick={() => setFilter(s)}
                className={`px-2.5 py-1.5 rounded-md text-xs font-semibold capitalize transition ${filter === s ? 'bg-[var(--bg-card)] shadow-card text-brand-700' : 'muted hover:text-slate-900'}`}>
                {s.replace('_', ' ')}
              </button>
            ))}
          </div>
        } />

      <div className="grid gap-3">
        {!loaded && Array.from({ length: 4 }).map((_, i) => (
          <Card key={`sk-${i}`} className="h-24 animate-pulse bg-slate-50 dark:bg-slate-800/40"><span /></Card>
        ))}
        {loaded && tickets.map(t => (
          <Card key={t.id} className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3 min-w-0">
                <div className="mt-0.5">{icon(t.status)}</div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold">{t.employee_name}</span>
                    <span className={`badge ${badge(t.status)} capitalize`}>{t.status.replace('_', ' ')}</span>
                  </div>
                  <p className="text-sm">{t.original_query}</p>
                  {t.bot_attempted_solution && <p className="muted text-xs mt-1">Bot tried: {t.bot_attempted_solution.slice(0, 120)}…</p>}
                  <p className="muted text-xs mt-2 tabular">Ticket #{t.id.slice(0, 8)} · {fmtDateTime(t.created_at)}</p>
                </div>
              </div>
              {t.status !== 'resolved' && (
                <button onClick={() => handleResolve(t.id)} className="btn-primary shrink-0"><ShieldCheck size={16} /> Resolve</button>
              )}
            </div>
          </Card>
        ))}
        {loaded && tickets.length === 0 && (
          <EmptyState icon={<ShieldCheck size={26} />} title={filter === 'all' ? 'No escalations' : `No ${filter} tickets`} hint="When the bot can't help someone, the ticket lands here." />
        )}
      </div>
    </div>
  )
}
