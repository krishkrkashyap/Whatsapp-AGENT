import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { TrendingUp, Trophy, PieChart } from 'lucide-react'
import { PageHeader, Card } from '../components/ui'

interface Overview {
  total_tasks: number; pending_tasks: number; completed_tasks: number;
  escalated_tasks: number; total_employees: number; total_messages: number;
  open_escalations: number; completion_rate: number; avg_resolution_hours: number;
  missed_tasks?: number; employees_on_leave?: number;
}

const iso = (d: Date) => d.toISOString().slice(0, 10)

export default function Analytics() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [deptData, setDeptData] = useState<any[]>([])
  const [priorityData, setPriorityData] = useState<any[]>([])
  const [trend, setTrend] = useState<any[]>([])
  const [performers, setPerformers] = useState<any[]>([])
  const [start, setStart] = useState(iso(new Date(Date.now() - 30 * 864e5)))
  const [end, setEnd] = useState(iso(new Date()))
  const [exporting, setExporting] = useState(false)

  const preset = (days: number) => {
    setStart(iso(new Date(Date.now() - days * 864e5)))
    setEnd(iso(new Date()))
  }
  const exportReport = async () => {
    setExporting(true)
    try { await api.exportReport(start, end) }
    catch (e: any) { alert(e.message || 'Export failed') }
    finally { setExporting(false) }
  }

  useEffect(() => {
    Promise.allSettled([
      api.getAnalyticsOverview(start, end), api.getTasksByDepartment(start, end), api.getTasksByPriority(start, end),
      api.getDailyTrend(14, start, end), api.getTopPerformers(start, end),
    ]).then(([o, d, p, t, perf]) => {
      if (o.status === 'fulfilled') setOverview(o.value)
      if (d.status === 'fulfilled') setDeptData(d.value)
      if (p.status === 'fulfilled') setPriorityData(p.value)
      if (t.status === 'fulfilled') setTrend(t.value)
      if (perf.status === 'fulfilled') setPerformers(perf.value)
    })
  }, [start, end])

  const maxTrend = Math.max(...trend.map(t => Math.max(t.created, t.completed)), 1)
  const medal = ['bg-amber-400', 'bg-slate-300', 'bg-amber-700']

  return (
    <div>
      <PageHeader title="Analytics" subtitle="How the team and the bot are performing." />

      <Card className="p-3 mb-4 flex flex-wrap items-end gap-3">
        <div className="flex items-center gap-1 bg-slate-50 dark:bg-slate-800/60 rounded-lg p-1">
          {([['Today', 0], ['7d', 7], ['30d', 30], ['90d', 90]] as [string, number][]).map(([label, d]) => {
            const active = start === iso(new Date(Date.now() - d * 864e5)) && end === iso(new Date())
            return (
              <button key={label} onClick={() => preset(d)}
                className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition ${active ? 'bg-[var(--bg-card)] shadow-card text-brand-700' : 'muted hover:text-slate-900'}`}>{label}</button>
            )
          })}
        </div>
        <label className="label mb-0 flex flex-col gap-1">From
          <input type="date" value={start} max={end} onChange={e => setStart(e.target.value)} className="field w-auto tabular" />
        </label>
        <label className="label mb-0 flex flex-col gap-1">To
          <input type="date" value={end} min={start} onChange={e => setEnd(e.target.value)} className="field w-auto tabular" />
        </label>
        <button onClick={exportReport} disabled={exporting} className="btn-primary ml-auto">
          {exporting ? 'Exporting…' : 'Export report (.xlsx)'}
        </button>
      </Card>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3 mb-4">
        {[
          { label: 'Completion', value: overview ? `${overview.completion_rate}%` : null, rule: 'bg-emerald-400' },
          { label: 'Avg resolution', value: overview ? `${overview.avg_resolution_hours}h` : null, rule: 'bg-brand-400' },
          { label: 'Missed (SOP)', value: overview?.missed_tasks ?? null, rule: 'bg-rose-400' },
          { label: 'On leave', value: overview?.employees_on_leave ?? null, rule: 'bg-amber-400' },
          { label: 'Messages', value: overview?.total_messages ?? null, rule: 'bg-sky-400' },
          { label: 'Open escal.', value: overview?.open_escalations ?? null, rule: 'bg-rose-400' },
          { label: 'Total tasks', value: overview?.total_tasks ?? null, rule: 'bg-brand-400' },
        ].map(s => (
          <Card key={s.label} className="relative overflow-hidden px-4 py-3">
            <span className={`absolute inset-x-0 top-0 h-0.5 ${s.rule}`} />
            <p className="muted text-[11px] font-semibold uppercase tracking-wide truncate">{s.label}</p>
            <p className="stat text-2xl font-extrabold leading-none mt-1.5 tabular">
              {overview ? s.value : <span className="inline-block w-9 h-6 rounded bg-slate-100 dark:bg-slate-800 animate-pulse align-middle" />}
            </p>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <h2 className="font-bold mb-4 flex items-center gap-2"><TrendingUp size={16} className="text-brand-600" /> Daily trend</h2>
          {trend.length > 0 ? (
            <div className="space-y-1.5">
              {trend.map((d, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="w-12 muted shrink-0 tabular">{d.date.slice(5)}</span>
                  <div className="flex-1 flex gap-1">
                    <div className="bg-brand-400 rounded h-3.5" style={{ width: `${(d.created / maxTrend) * 100}%`, minWidth: d.created > 0 ? '4px' : 0 }} />
                    <div className="bg-emerald-400 rounded h-3.5" style={{ width: `${(d.completed / maxTrend) * 100}%`, minWidth: d.completed > 0 ? '4px' : 0 }} />
                  </div>
                  <span className="w-12 text-right muted tabular">{d.created}/{d.completed}</span>
                </div>
              ))}
              <div className="flex gap-4 mt-3 text-xs muted">
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 bg-brand-400 rounded inline-block" /> Created</span>
                <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 bg-emerald-400 rounded inline-block" /> Completed</span>
              </div>
            </div>
          ) : <p className="muted text-sm">No data yet.</p>}
        </Card>

        <Card className="p-5">
          <h2 className="font-bold mb-4 flex items-center gap-2"><Trophy size={16} className="text-amber-500" /> Top performers</h2>
          {performers.length > 0 ? (
            <div className="space-y-2.5">
              {performers.map((p, i) => (
                <div key={i} className="flex items-center gap-3">
                  <span className={`w-7 h-7 rounded-lg grid place-items-center text-xs font-bold text-white ${medal[i] || 'bg-slate-200 text-slate-500'}`}>{i + 1}</span>
                  <div className="flex-1 min-w-0"><p className="font-semibold text-sm truncate">{p.name}</p><p className="muted text-xs truncate">{p.department}</p></div>
                  <span className="text-sm font-bold text-emerald-600 tabular">{p.completed}</span>
                </div>
              ))}
            </div>
          ) : <p className="muted text-sm">No completed tasks yet.</p>}
        </Card>

        <Card className="p-5">
          <h2 className="font-bold mb-4 flex items-center gap-2"><PieChart size={16} className="text-brand-600" /> By department</h2>
          {deptData.length > 0 ? (
            <div className="space-y-3">
              {deptData.map((d, i) => (
                <div key={i}>
                  <div className="flex justify-between text-sm mb-1"><span className="truncate">{d.department}</span><span className="muted tabular">{d.done}/{d.total}</span></div>
                  <div className="w-full bg-slate-100 rounded-full h-2.5"><div className="bg-emerald-500 h-2.5 rounded-full transition-all" style={{ width: `${d.total > 0 ? (d.done / d.total * 100) : 0}%` }} /></div>
                </div>
              ))}
            </div>
          ) : <p className="muted text-sm">No data yet.</p>}
        </Card>

        <Card className="p-5">
          <h2 className="font-bold mb-4">By priority</h2>
          {priorityData.length > 0 ? (
            <div className="flex gap-6 items-end h-40 px-2">
              {priorityData.map((d, i) => {
                const maxP = Math.max(...priorityData.map(x => x.count), 1)
                const colors: Record<string, string> = { high: 'bg-rose-500', medium: 'bg-amber-500', low: 'bg-emerald-500' }
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-2">
                    <span className="text-sm font-bold tabular">{d.count}</span>
                    <div className={`w-full ${colors[d.priority] || 'bg-slate-400'} rounded-t-lg transition-all`} style={{ height: `${(d.count / maxP) * 100}%`, minHeight: 8 }} />
                    <span className="text-xs muted capitalize">{d.priority}</span>
                  </div>
                )
              })}
            </div>
          ) : <p className="muted text-sm">No data yet.</p>}
        </Card>
      </div>
    </div>
  )
}
