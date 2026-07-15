import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { ClipboardList, Users, Plus, Factory, Power, X } from 'lucide-react'
import { PageHeader, Card, EmptyState } from '../components/ui'

interface Department {
  department: string
  count: number
  active_count: number
}

// Group departments under a single outer card. A department matches a group by
// explicit name or by prefix. Anything unmatched renders as its own group.
const GROUPS: { name: string; departments?: string[]; prefix?: string }[] = [
  { name: 'Thol Factory', prefix: 'Thol Factory - ' },
  { name: 'Prahladnagar Outlet', prefix: 'Prahladnagar - ' },
]

interface Group { name: string; depts: Department[]; active: number }

function buildGroups(depts: Department[]): Group[] {
  const groups: Group[] = []
  const byName = new Map<string, Group>()
  const ensure = (name: string) => {
    let g = byName.get(name)
    if (!g) { g = { name, depts: [], active: 0 }; byName.set(name, g); groups.push(g) }
    return g
  }
  for (const d of depts) {
    const cfg = GROUPS.find(
      (g) => g.departments?.includes(d.department) || (g.prefix && d.department.startsWith(g.prefix)),
    )
    const g = ensure(cfg ? cfg.name : d.department)
    g.depts.push(d)
    g.active += d.active_count
  }
  return groups
}

// Strip a group prefix for a cleaner inner label.
function deptLabel(dept: string): string {
  for (const g of GROUPS) {
    if (g.prefix && dept.startsWith(g.prefix)) return dept.slice(g.prefix.length)
  }
  return dept
}

export default function SOPs() {
  const [departments, setDepartments] = useState<Department[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  // Pause modal target: the departments to switch off + a human label.
  const [pauseTarget, setPauseTarget] = useState<{ departments: string[]; label: string } | null>(null)
  const [untilInput, setUntilInput] = useState('')
  const navigate = useNavigate()

  const reload = () =>
    api.getSOPDepartments().then(setDepartments).catch(console.error)

  useEffect(() => {
    reload().finally(() => setLoading(false))
  }, [])

  const resume = async (departments: string[]) => {
    setBusy(true)
    try {
      await api.bulkSOPStatus({ status: 'active', departments })
      await reload()
    } catch (e) { alert('Failed: ' + e) } finally { setBusy(false) }
  }

  const openPause = (departments: string[], label: string) => {
    setUntilInput('')
    setPauseTarget({ departments, label })
  }

  const confirmPause = async () => {
    if (!pauseTarget) return
    setBusy(true)
    try {
      // datetime-local has no timezone; treat as local and send ISO.
      const iso = untilInput ? new Date(untilInput).toISOString() : null
      await api.bulkSOPStatus({ status: 'paused', paused_until: iso, departments: pauseTarget.departments })
      setPauseTarget(null)
      await reload()
    } catch (e) { alert('Failed: ' + e) } finally { setBusy(false) }
  }

  const groups = buildGroups(departments)

  // Reusable on/off control. `on` = something is active (so the action is "turn off").
  const PowerBtn = ({ on, onClick, title }: { on: boolean; onClick: (e: any) => void; title: string }) => (
    <button
      onClick={onClick}
      disabled={busy}
      title={title}
      className={`p-1.5 rounded-md border transition disabled:opacity-50 ${
        on ? 'text-emerald-600 border-emerald-200 hover:bg-emerald-50'
           : 'text-rose-500 border-rose-200 hover:bg-rose-50'
      }`}
    >
      <Power size={16} />
    </button>
  )

  return (
    <div>
      <PageHeader title="SOPs" subtitle="Standard operating procedures, grouped by site & department."
        actions={<button onClick={() => navigate('/sops/manage')} className="btn-primary"><Plus size={16} /> Manage SOPs</button>} />

      {loading ? (
        <div className="space-y-6">
          {Array.from({ length: 2 }).map((_, i) => (
            <Card key={i} className="p-6">
              <div className="h-5 w-40 rounded bg-slate-100 dark:bg-slate-800 animate-pulse mb-4" />
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {Array.from({ length: 3 }).map((_, j) => <div key={j} className="h-20 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />)}
              </div>
            </Card>
          ))}
        </div>
      ) : departments.length === 0 ? (
        <EmptyState icon={<ClipboardList size={26} />} title="No SOPs yet"
          hint="Import SOPs from your Excel file to get started."
          action={<button onClick={() => navigate('/sops/manage')} className="btn-primary mx-auto">Create SOPs</button>} />
      ) : (
        <div className="space-y-6">
          {groups.map((group) => {
            const total = group.depts.reduce((n, d) => n + d.count, 0)
            const groupOn = group.active > 0
            const groupDepts = group.depts.map((d) => d.department)
            // A single ungrouped department keeps the old flat card look.
            const isSingle = group.depts.length === 1 && group.depts[0].department === group.name
            if (isSingle) {
              const dept = group.depts[0]
              const on = dept.active_count > 0
              return (
                <Card key={group.name} className="p-6 max-w-sm">
                  <div className="flex items-center justify-between mb-3">
                    <div className="w-10 h-10 bg-brand-50 rounded-lg flex items-center justify-center">
                      <Users size={20} className="text-brand-600" />
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`badge ${on ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
                        {on ? `${dept.active_count} active` : 'off'}
                      </span>
                      <PowerBtn on={on} title={on ? 'Pause all' : 'Resume all'}
                        onClick={(e) => { e.stopPropagation(); on ? openPause([dept.department], dept.department) : resume([dept.department]) }} />
                    </div>
                  </div>
                  <div onClick={() => navigate(`/sops/department/${encodeURIComponent(dept.department)}`)} className="cursor-pointer">
                    <h3 className="font-semibold text-lg">{dept.department}</h3>
                    <p className="text-sm muted">{dept.count} SOPs total</p>
                  </div>
                </Card>
              )
            }
            return (
              <Card key={group.name} className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 bg-brand-600 rounded-lg flex items-center justify-center">
                      <Factory size={22} className="text-white" />
                    </div>
                    <div>
                      <h2 className="font-bold text-lg leading-tight">{group.name}</h2>
                      <p className="text-xs muted tabular">
                        {group.depts.length} sections · {total} SOPs · {group.active} active
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs muted hidden sm:inline">{groupOn ? 'Turn whole group off' : 'Turn whole group on'}</span>
                    <PowerBtn on={groupOn} title={groupOn ? `Pause all in ${group.name}` : `Resume all in ${group.name}`}
                      onClick={() => groupOn ? openPause(groupDepts, group.name) : resume(groupDepts)} />
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {group.depts.map((dept) => {
                    const on = dept.active_count > 0
                    return (
                      <div
                        key={dept.department}
                        className="rounded-lg p-4 border border-[var(--border)] bg-[var(--bg-app)] hover:bg-[var(--bg-card)] hover:border-brand-200 hover:shadow-card transition"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="w-8 h-8 bg-brand-50 rounded-md flex items-center justify-center">
                            <Users size={16} className="text-brand-600" />
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className={`badge ${on ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
                              {on ? `${dept.active_count} active` : 'off'}
                            </span>
                            <PowerBtn on={on} title={on ? 'Pause section' : 'Resume section'}
                              onClick={(e) => { e.stopPropagation(); on ? openPause([dept.department], deptLabel(dept.department)) : resume([dept.department]) }} />
                          </div>
                        </div>
                        <div onClick={() => navigate(`/sops/department/${encodeURIComponent(dept.department)}`)} className="cursor-pointer">
                          <h3 className="font-semibold text-sm">{deptLabel(dept.department)}</h3>
                          <p className="text-xs muted">{dept.count} SOPs total</p>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {pauseTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-slate-900/40 backdrop-blur-sm"
             onClick={() => setPauseTarget(null)}>
          <div className="card p-6 w-full max-w-sm shadow-pop animate-fade-in" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-1">
              <h3 className="font-bold text-lg">Turn off: {pauseTarget.label}</h3>
              <button onClick={() => setPauseTarget(null)} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={18} /></button>
            </div>
            <p className="text-sm muted mb-4">
              Pauses all SOPs in this {pauseTarget.departments.length > 1 ? 'group' : 'section'}.
              They send no reminders while off.
            </p>
            <label className="label">Resume on (optional)</label>
            <input type="datetime-local" value={untilInput} onChange={(e) => setUntilInput(e.target.value)} className="field tabular" />
            <p className="text-xs muted mt-1.5">
              Leave blank to keep off until you turn it back on manually. Set a date/time to auto-resume.
            </p>
            <div className="flex gap-2 mt-5">
              <button onClick={() => setPauseTarget(null)} disabled={busy} className="btn-ghost flex-1">Cancel</button>
              <button onClick={confirmPause} disabled={busy} className="btn-danger flex-1">
                {busy ? 'Turning off…' : (untilInput ? 'Pause until date' : 'Pause')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
