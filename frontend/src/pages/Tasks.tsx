import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Search, Plus, Users, X, RefreshCw, Paperclip, CalendarClock,
  CheckCircle2, CircleAlert, Clock, ListTodo,
} from 'lucide-react'
import EditTaskModal from '../components/EditTaskModal'
import {
  PageHeader, Card, EmptyState, StatusBadge, PriorityBadge, fmtDateTime, fmtRelative,
} from '../components/ui'

interface Task {
  id: string; title: string; status: string; priority: string;
  assigned_to_id: string; assigned_by_id?: string; due_date: string | null;
  completed_at: string | null; created_at: string; assigned_at?: string;
  description?: string; requires_attachment?: boolean;
}
interface Employee { id: string; name: string; department: string; is_admin?: boolean }

const STATUS_FILTERS = ['all', 'pending', 'in_progress', 'done', 'escalated', 'blocked']

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'
}

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [stats, setStats] = useState<{ open: number; done: number; escalated: number; missed: number } | null>(null)
  const [filter, setFilter] = useState('all')
  const [priorityFilter, setPriorityFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAssignModal, setShowAssignModal] = useState(false)
  const [showBulkModal, setShowBulkModal] = useState(false)
  const [editTask, setEditTask] = useState<Task | null>(null)
  const [employees, setEmployees] = useState<Employee[]>([])
  const [assignForm, setAssignForm] = useState({
    title: '', description: '', priority: 'medium', assigned_to_id: '',
    due_date: '', requires_attachment: false, sla_enabled: true,
    follow_up_enabled: false, follow_up_interval: 30, follow_up_unit: 'min',
  })
  const [bulkForm, setBulkForm] = useState({
    title: '', description: '', priority: 'medium', assigned_to_ids: [] as string[],
    due_date: '', requires_attachment: false,
  })
  const [empMap, setEmpMap] = useState<Record<string, string>>({})

  const loadTasks = async () => {
    setRefreshing(true)
    try {
      const [data, s] = await Promise.all([
        api.getTasks(filter !== 'all' ? filter : undefined),
        api.getTaskStats().catch(() => null),
      ])
      setTasks(data)
      if (s) setStats(s)
      setError(null)
    } catch (e: any) {
      setError(e?.message || 'Could not load tasks')
    } finally { setRefreshing(false); setLoaded(true) }
  }

  useEffect(() => { loadTasks() }, [filter])
  useEffect(() => {
    api.getEmployees().then((emps: Employee[]) => {
      setEmployees(emps)
      const map: Record<string, string> = {}
      emps.forEach(e => { map[e.id] = e.name })
      setEmpMap(map)
    })
  }, [])
  useEffect(() => { const i = setInterval(loadTasks, 30000); return () => clearInterval(i) }, [filter])

  const filtered = tasks.filter(t => {
    if (priorityFilter !== 'all' && t.priority !== priorityFilter) return false
    if (search && !t.title.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  // Whole-DB counts from /tasks/stats — not the latest-100 page (which made
  // Completed read 0). Falls back to the loaded page until stats arrive.
  const counts = stats ?? {
    open: tasks.filter(t => ['pending', 'in_progress'].includes(t.status)).length,
    done: tasks.filter(t => t.status === 'done').length,
    escalated: tasks.filter(t => t.status === 'escalated').length,
    missed: tasks.filter(t => t.status === 'missed').length,
  }

  const nameFor = (id?: string) => (id ? empMap[id] || id.slice(0, 8) : '—')

  const handleAssign = async () => {
    if (!assignForm.title || !assignForm.assigned_to_id) { alert('Title and assignee are required.'); return }
    const firstAdmin = employees.find(e => e.is_admin) || employees.find(e => e.id)
    let followUpHours: number | null = null
    let followUpType = 'none'
    if (assignForm.follow_up_enabled) {
      followUpType = 'periodic'
      followUpHours = assignForm.follow_up_unit === 'min' ? assignForm.follow_up_interval / 60 : assignForm.follow_up_interval
    }
    try {
      await api.assignTask({
        ...assignForm,
        assigned_by_id: firstAdmin?.id || assignForm.assigned_to_id,
        follow_up_type: followUpType, follow_up_interval_hours: followUpHours,
      })
      setShowAssignModal(false)
      setAssignForm({ title: '', description: '', priority: 'medium', assigned_to_id: '', due_date: '', requires_attachment: false, sla_enabled: true, follow_up_enabled: false, follow_up_interval: 30, follow_up_unit: 'min' })
      loadTasks()
    } catch (err) { alert('Could not assign the task. ' + err) }
  }

  const handleBulkAssign = async () => {
    if (!bulkForm.title || bulkForm.assigned_to_ids.length === 0) { alert('Title and at least one assignee are required.'); return }
    const firstAdmin = employees.find(e => e.is_admin) || employees.find(e => e.id)
    try {
      const res = await api.bulkAssign({ ...bulkForm, assigned_by_id: firstAdmin?.id || '' })
      setShowBulkModal(false)
      setBulkForm({ title: '', description: '', priority: 'medium', assigned_to_ids: [], due_date: '', requires_attachment: false })
      loadTasks()
      alert(`Assigned to ${res.assigned} employees.`)
    } catch (err) { alert('Bulk assign failed. ' + err) }
  }

  return (
    <div>
      <PageHeader
        title="Tasks"
        subtitle="Everything assigned across the team, live from WhatsApp."
        actions={
          <>
            <button onClick={() => setShowAssignModal(true)} className="btn-primary"><Plus size={16} /> Assign</button>
            <button onClick={() => setShowBulkModal(true)} className="btn-ghost"><Users size={16} /> Bulk</button>
            <button onClick={() => api.exportTasks()} className="btn-ghost">Export</button>
            <button onClick={loadTasks} disabled={refreshing} className="btn-ghost">
              <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            </button>
          </>
        }
      />

      {/* Summary — compact, number-forward tiles with a status-tinted top rule */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        {[
          { label: 'Open', value: counts.open, rule: 'bg-sky-400' },
          { label: 'Completed', value: counts.done, rule: 'bg-emerald-400' },
          { label: 'Missed', value: (counts as any).missed ?? 0, rule: 'bg-amber-400' },
          { label: 'Escalated', value: counts.escalated, rule: 'bg-rose-400' },
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

      {error && (
        <Card className="mb-4 px-4 py-3 flex items-center justify-between gap-3 border-rose-200 bg-rose-50 text-rose-700">
          <span className="text-sm font-medium">{error}</span>
          <button onClick={loadTasks} className="btn-ghost text-rose-700 border-rose-200">Retry</button>
        </Card>
      )}

      {/* Filters */}
      <Card className="p-3 mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 muted" />
          <input className="field pl-9" placeholder="Search tasks…" value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <div className="flex items-center gap-1 bg-slate-50 rounded-lg p-1">
          {STATUS_FILTERS.map(s => (
            <button key={s} onClick={() => setFilter(s)}
              className={`px-2.5 py-1.5 rounded-md text-xs font-semibold capitalize transition ${
                filter === s ? 'bg-[var(--bg-card)] shadow-card text-brand-700' : 'muted hover:text-slate-900'
              }`}>
              {s === 'all' ? 'All' : s.replace('_', ' ')}
            </button>
          ))}
        </div>
        <select value={priorityFilter} onChange={e => setPriorityFilter(e.target.value)} className="field w-auto">
          <option value="all">All priority</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <span className="muted text-sm ml-auto tabular">{filtered.length} of {tasks.length}</span>
      </Card>

      {/* Task list */}
      <div className="grid gap-2">
        {!loaded && Array.from({ length: 6 }).map((_, i) => (
          <Card key={`sk-${i}`} className="px-4 py-3 flex items-center gap-3">
            <div className="w-9 h-9 shrink-0 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-1/3 rounded bg-slate-100 dark:bg-slate-800 animate-pulse" />
              <div className="h-2.5 w-2/3 rounded bg-slate-100 dark:bg-slate-800 animate-pulse" />
            </div>
          </Card>
        ))}

        {loaded && filtered.map(t => (
          <Card key={t.id} interactive onClick={() => setEditTask(t)} className="px-4 py-3">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 shrink-0 rounded-lg bg-brand-50 text-brand-700 grid place-items-center text-xs font-bold">
                {initials(nameFor(t.assigned_to_id))}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-semibold truncate leading-snug">{t.title}</p>
                    {t.description && <p className="muted text-sm truncate mt-0.5">{t.description}</p>}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <StatusBadge status={t.status} />
                    <PriorityBadge priority={t.priority} />
                  </div>
                </div>

                {/* meta row */}
                <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 mt-1.5 text-xs muted">
                  <span className="inline-flex items-center gap-1.5">
                    <Users size={13} /> {nameFor(t.assigned_to_id)}
                    {t.assigned_by_id && <span className="text-slate-300">·</span>}
                    {t.assigned_by_id && <span>by {nameFor(t.assigned_by_id)}</span>}
                  </span>
                  <span className="inline-flex items-center gap-1.5 tabular">
                    <CalendarClock size={13} /> {fmtDateTime(t.assigned_at || t.created_at)}
                  </span>
                  {t.due_date && (
                    <span className="inline-flex items-center gap-1.5 tabular"><Clock size={13} /> Due {fmtDateTime(t.due_date)}</span>
                  )}
                  {t.completed_at && (
                    <span className="inline-flex items-center gap-1.5 tabular text-emerald-600">
                      <CheckCircle2 size={13} /> {fmtRelative(t.completed_at)}
                    </span>
                  )}
                  {t.requires_attachment && (
                    <span className="inline-flex items-center gap-1 text-amber-600"><Paperclip size={12} /> Photo proof</span>
                  )}
                </div>
              </div>
            </div>
          </Card>
        ))}

        {loaded && filtered.length === 0 && (
          <EmptyState
            icon={<ListTodo size={26} />}
            title={tasks.length === 0 ? 'No tasks yet' : 'Nothing matches those filters'}
            hint={tasks.length === 0 ? 'Assign a task from WhatsApp or with the Assign button above.' : 'Try clearing the search or status filter.'}
            action={tasks.length === 0 ? <button onClick={() => setShowAssignModal(true)} className="btn-primary"><Plus size={16} /> Assign a task</button> : undefined}
          />
        )}
      </div>

      {/* Assign modal */}
      {showAssignModal && (
        <Modal title="Assign task" onClose={() => setShowAssignModal(false)}>
          <div className="space-y-3">
            <input className="field" placeholder="Task title" value={assignForm.title} onChange={e => setAssignForm(f => ({ ...f, title: e.target.value }))} />
            <textarea className="field" placeholder="Description (optional)" rows={2} value={assignForm.description} onChange={e => setAssignForm(f => ({ ...f, description: e.target.value }))} />
            <select className="field" value={assignForm.assigned_to_id} onChange={e => setAssignForm(f => ({ ...f, assigned_to_id: e.target.value }))}>
              <option value="">Select employee…</option>
              {employees.map(e => <option key={e.id} value={e.id}>{e.name} · {e.department}</option>)}
            </select>
            <div className="grid grid-cols-2 gap-2">
              <select className="field" value={assignForm.priority} onChange={e => setAssignForm(f => ({ ...f, priority: e.target.value }))}>
                <option value="low">Low priority</option>
                <option value="medium">Medium priority</option>
                <option value="high">High priority</option>
              </select>
              <input className="field" type="date" value={assignForm.due_date} onChange={e => setAssignForm(f => ({ ...f, due_date: e.target.value }))} />
            </div>
            <Check label="Requires photo proof on completion" checked={assignForm.requires_attachment} onChange={v => setAssignForm(f => ({ ...f, requires_attachment: v }))} />
            <Check label="Escalate if not started on time (SLA)" checked={assignForm.sla_enabled} onChange={v => setAssignForm(f => ({ ...f, sla_enabled: v }))} />
            <div className="border-t border-[var(--border)] pt-3">
              <Check label="Periodic follow-up reminders" checked={assignForm.follow_up_enabled} onChange={v => setAssignForm(f => ({ ...f, follow_up_enabled: v }))} />
              {assignForm.follow_up_enabled && (
                <div className="flex items-center gap-2 mt-2 ml-6">
                  <span className="muted text-sm">Every</span>
                  <input type="number" min={1} className="field w-20 text-center" value={assignForm.follow_up_interval} onChange={e => setAssignForm(f => ({ ...f, follow_up_interval: parseInt(e.target.value) || 1 }))} />
                  <select className="field w-auto" value={assignForm.follow_up_unit} onChange={e => setAssignForm(f => ({ ...f, follow_up_unit: e.target.value }))}>
                    <option value="min">minutes</option>
                    <option value="hour">hours</option>
                  </select>
                </div>
              )}
            </div>
          </div>
          <div className="flex gap-2 mt-5">
            <button onClick={() => setShowAssignModal(false)} className="btn-ghost flex-1">Cancel</button>
            <button onClick={handleAssign} className="btn-primary flex-1">Assign &amp; notify</button>
          </div>
        </Modal>
      )}

      {/* Bulk modal */}
      {showBulkModal && (
        <Modal title="Bulk assign" onClose={() => setShowBulkModal(false)} wide>
          <div className="space-y-3">
            <input className="field" placeholder="Task title" value={bulkForm.title} onChange={e => setBulkForm(f => ({ ...f, title: e.target.value }))} />
            <textarea className="field" placeholder="Description (optional)" rows={2} value={bulkForm.description} onChange={e => setBulkForm(f => ({ ...f, description: e.target.value }))} />
            <div>
              <p className="label">Assign to ({bulkForm.assigned_to_ids.length} selected)</p>
              <div className="max-h-44 overflow-y-auto card p-2 space-y-0.5">
                {employees.map(e => (
                  <label key={e.id} className="flex items-center gap-2 text-sm p-1.5 rounded-md hover:bg-slate-50 cursor-pointer">
                    <input type="checkbox" checked={bulkForm.assigned_to_ids.includes(e.id)}
                      onChange={ev => setBulkForm(f => ({ ...f, assigned_to_ids: ev.target.checked ? [...f.assigned_to_ids, e.id] : f.assigned_to_ids.filter(id => id !== e.id) }))} />
                    {e.name} <span className="muted">· {e.department}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <select className="field" value={bulkForm.priority} onChange={e => setBulkForm(f => ({ ...f, priority: e.target.value }))}>
                <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
              </select>
              <input className="field" type="date" value={bulkForm.due_date} onChange={e => setBulkForm(f => ({ ...f, due_date: e.target.value }))} />
            </div>
            <Check label="Requires photo proof on completion" checked={bulkForm.requires_attachment} onChange={v => setBulkForm(f => ({ ...f, requires_attachment: v }))} />
          </div>
          <div className="flex gap-2 mt-5">
            <button onClick={() => setShowBulkModal(false)} className="btn-ghost flex-1">Cancel</button>
            <button onClick={handleBulkAssign} className="btn-primary flex-1">Assign to {bulkForm.assigned_to_ids.length}</button>
          </div>
        </Modal>
      )}

      {editTask && (
        <EditTaskModal task={editTask} employees={employees} onClose={() => setEditTask(null)} onSaved={loadTasks} />
      )}
    </div>
  )
}

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-slate-900/40 backdrop-blur-sm" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className={`card p-6 w-full ${wide ? 'max-w-lg' : 'max-w-md'} shadow-pop animate-fade-in`}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">{title}</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2.5 text-sm cursor-pointer select-none">
      <input type="checkbox" className="w-4 h-4 rounded accent-brand-600" checked={checked} onChange={e => onChange(e.target.checked)} />
      {label}
    </label>
  )
}
