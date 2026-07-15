import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Megaphone, Activity, Smartphone } from 'lucide-react'
import { PageHeader, Card } from '../components/ui'

export default function Dashboard() {
  const [stats, setStats] = useState({ employees: 0, pending: 0, completed: 0, escalated: 0, status: 'checking' })
  const [openwaStatus, setOpenWAStatus] = useState<{ connected: boolean; configured: boolean } | null>(null)
  const [departments, setDepartments] = useState<string[]>([])
  const [deepHealth, setDeepHealth] = useState<{ database?: string; redis?: string } | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    const load = async () => {
      const [statsResult, healthResult, openwaResult, deptResult, deepResult] = await Promise.allSettled([
        api.getInternalStats(), api.getHealth(), api.getOpenWAStatus(),
        api.getInternalDepartments(), api.getDeepHealth(),
      ])
      const s = statsResult.status === 'fulfilled' ? statsResult.value : {}
      setStats({
        employees: s.total_employees || 0,
        pending: s.pending_tasks || 0,
        completed: s.completed_tasks || 0,
        escalated: s.escalated_tasks || 0,
        status: healthResult.status === 'fulfilled' ? 'ok' : 'error',
      })
      setOpenWAStatus(openwaResult.status === 'fulfilled' ? openwaResult.value : null)
      setDepartments(deptResult.status === 'fulfilled' ? deptResult.value.departments : [])
      setDeepHealth(deepResult.status === 'fulfilled' ? deepResult.value : null)
      setLoaded(true)
    }
    load()
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [])

  const Svc = ({ label, value }: { label: string; value?: string }) => {
    const ok = value === 'ok'
    return (
      <div className="flex items-center justify-between py-2 border-b border-[var(--border)] last:border-0">
        <span className="text-sm">{label}</span>
        <span className={`badge ${ok ? 'bg-emerald-50 text-emerald-700' : !value ? 'bg-slate-100 text-slate-500' : 'bg-rose-50 text-rose-700'}`}>
          <span className="w-1.5 h-1.5 rounded-full bg-current" /> {!value ? 'Unknown' : ok ? 'Connected' : value}
        </span>
      </div>
    )
  }

  const live = openwaStatus?.connected
  return (
    <div>
      <PageHeader title="Dashboard" subtitle="Live overview of your team, tasks and bot health." />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        {[
          { label: 'Employees', value: stats.employees, rule: 'bg-brand-400' },
          { label: 'Pending', value: stats.pending, rule: 'bg-amber-400' },
          { label: 'Completed', value: stats.completed, rule: 'bg-emerald-400' },
          { label: 'Escalated', value: stats.escalated, rule: 'bg-rose-400' },
        ].map(s => (
          <Card key={s.label} className="relative overflow-hidden px-4 py-3">
            <span className={`absolute inset-x-0 top-0 h-0.5 ${s.rule}`} />
            <p className="muted text-[11px] font-semibold uppercase tracking-wide">{s.label}</p>
            <p className="stat text-3xl font-extrabold leading-none mt-1.5 tabular">
              {loaded ? s.value : <span className="inline-block w-10 h-7 rounded bg-slate-100 dark:bg-slate-800 animate-pulse align-middle" />}
            </p>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* WhatsApp + system status */}
        <Card className="p-5 lg:col-span-1">
          <div className="flex items-center gap-2 mb-3">
            <Smartphone size={16} className="muted" />
            <h2 className="font-bold">WhatsApp gateway</h2>
          </div>
          <div className={`badge ${live ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${live ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`} />
            {live ? 'Connected · live' : openwaStatus?.configured === false ? 'Dev mode' : 'Disconnected'}
          </div>
          <div className="flex items-center gap-2 mt-5 mb-3">
            <Activity size={16} className="muted" /><h2 className="font-bold">System</h2>
          </div>
          <Svc label="Backend API" value={stats.status === 'ok' ? 'ok' : 'down'} />
          <Svc label="PostgreSQL" value={deepHealth?.database} />
          <Svc label="Redis" value={deepHealth?.redis} />
        </Card>

        {/* Broadcast */}
        <Card className="p-5 lg:col-span-2">
          <div className="flex items-center gap-2 mb-3">
            <Megaphone size={16} className="text-brand-600" />
            <h2 className="font-bold">Broadcast a message</h2>
          </div>
          <form onSubmit={async (e) => {
            e.preventDefault()
            const target = e.target as HTMLFormElement
            const msg = (target.elements.namedItem('message') as HTMLTextAreaElement).value
            const dept = (target.elements.namedItem('department') as HTMLSelectElement).value
            try { const res = await api.broadcast(msg, dept); alert(`Broadcast sent to ${res.sent} employees.`); target.reset() }
            catch (err) { alert('Broadcast failed. ' + err) }
          }}>
            <textarea name="message" required rows={4} placeholder="Type a message to send to a department or everyone…" className="field mb-3" />
            <div className="flex flex-col sm:flex-row gap-2">
              <select name="department" className="field sm:max-w-xs">
                <option value="all">All departments</option>
                {departments.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
              <button type="submit" className="btn-primary sm:ml-auto"><Megaphone size={16} /> Send broadcast</button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  )
}
