import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { Plus, Edit2, Trash2, Play, PauseCircle, Clock, Users, AlertTriangle, FolderOpen, X, Paperclip } from 'lucide-react'
import { PageHeader, Card, EmptyState } from '../components/ui'

interface SOP {
  id: string
  title: string
  description: string | null
  department: string
  frequency: string
  days_of_week: number | null
  day_of_month: number | null
  start_time: string
  end_time: string | null
  interval_hours: number | null
  assigned_to_id: string
  assigned_to_name: string
  admin_id: string
  admin_name: string
  requires_attachment: boolean
  attachment_checklist: string | null
  notify_before_min: number
  notify_after_min: number
  admin_notify_after_min: number
  priority: string
  status: string
}

export default function SOPManage() {
  const navigate = useNavigate()
  const [sops, setSOPs] = useState<SOP[]>([])
  const [employees, setEmployees] = useState<any[]>([])
  const [departments, setDepartments] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editSOP, setEditSOP] = useState<SOP | null>(null)
  const [form, setForm] = useState<any>({})
  const [importModal, setImportModal] = useState(false)
  const [importData, setImportData] = useState('')
  const [selectedDept, setSelectedDept] = useState<string>('all')
  const [searchParams, setSearchParams] = useSearchParams()

  const load = () => {
    setLoading(true)
    Promise.all([
      api.getSOPs(),
      api.getSOPEmployees(),
      api.getDepartments(),
    ])
      .then(([sopsData, empsData, deptData]) => {
        setSOPs(sopsData)
        setEmployees(empsData)
        // api.getDepartments() returns { departments: string[], stats }, not an array
        setDepartments(deptData.departments || [])
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const filtered = selectedDept === 'all' ? sops : sops.filter(s => s.department === selectedDept)

  const openCreate = (dept?: string) => {
    setEditSOP(null)
    setForm({
      title: '',
      description: '',
      department: dept || (selectedDept !== 'all' ? selectedDept : ''),
      frequency: 'daily',
      days_of_week: 0,
      day_of_month: 1,
      interval_hours: 1,
      start_time: '09:00',
      end_time: '',
      assigned_to_id: '',
      admin_id: '',
      requires_attachment: false,
      attachment_checklist: [] as string[],
      notify_before_min: 5,
      notify_after_min: 5,
      admin_notify_after_min: 15,
      priority: 'medium',
    })
    setShowForm(true)
  }

  const openEdit = (sop: SOP) => {
    setEditSOP(sop)
    setForm({
      title: sop.title,
      description: sop.description || '',
      department: sop.department,
      frequency: sop.frequency,
      days_of_week: sop.days_of_week ?? 0,
      day_of_month: sop.day_of_month ?? 1,
      interval_hours: sop.interval_hours ?? 1,
      start_time: sop.start_time,
      end_time: sop.end_time || '',
      assigned_to_id: sop.assigned_to_id || '',
      admin_id: sop.admin_id || '',
      requires_attachment: sop.requires_attachment,
      attachment_checklist: (() => {
        try { const a = JSON.parse(sop.attachment_checklist || '[]'); return Array.isArray(a) ? a : [] }
        catch { return [] }
      })(),
      notify_before_min: sop.notify_before_min,
      notify_after_min: sop.notify_after_min,
      admin_notify_after_min: sop.admin_notify_after_min,
      priority: sop.priority,
      status: sop.status,
    })
    setShowForm(true)
  }

  // Deep-link: /sops/manage?edit=<id> opens that SOP's editor; ?create=1&dept=…
  // opens a new form pre-scoped to the department. Runs once SOPs have loaded.
  useEffect(() => {
    if (loading) return
    const editId = searchParams.get('edit')
    const createDept = searchParams.get('create') ? (searchParams.get('dept') || '') : null
    if (editId) {
      const sop = sops.find(s => s.id === editId)
      if (sop) { openEdit(sop); setSearchParams({}, { replace: true }) }
    } else if (createDept !== null) {
      if (createDept) setSelectedDept(createDept)
      openCreate(createDept || undefined); setSearchParams({}, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, sops])

  const save = async () => {
    try {
      const payload = { ...form }
      // Convert empty strings to null for optional fields
      if (!payload.end_time) payload.end_time = null
      if (!payload.description) payload.description = null
      if (!payload.admin_id) payload.admin_id = null

      // Only send the scheduling field relevant to the chosen frequency; null
      // out the others so stale values don't mislead the scheduler.
      if (payload.frequency === 'weekly') {
        if (!payload.days_of_week) { alert('Pick at least one day for a weekly SOP'); return }
        payload.day_of_month = null
        payload.interval_hours = null
      } else if (payload.frequency === 'monthly') {
        const dom = Number(payload.day_of_month)
        if (!dom || dom < 1 || dom > 31) { alert('Day of month must be between 1 and 31'); return }
        payload.day_of_month = dom
        payload.days_of_week = null
        payload.interval_hours = null
      } else if (payload.frequency === 'hourly') {
        const n = Number(payload.interval_hours)
        if (!n || n <= 0 || n > 24) { alert('"Every N hours" must be between 1 and 24'); return }
        payload.interval_hours = n
        payload.days_of_week = null
        payload.day_of_month = null
      } else {
        // daily / weekday: single fire at start_time, no interval
        payload.days_of_week = null
        payload.day_of_month = null
        payload.interval_hours = null
      }

      // Checklist: drop blanks; send JSON string or null when empty.
      const items = (payload.attachment_checklist || [])
        .map((s: string) => (s || '').trim()).filter(Boolean)
      payload.attachment_checklist = items.length ? JSON.stringify(items) : null

      if (editSOP) {
        await api.updateSOP(editSOP.id, payload)
      } else {
        await api.createSOP(payload)
      }
      setShowForm(false)
      load()
    } catch (err) {
      alert('Save failed: ' + err)
    }
  }

  const remove = async (id: string) => {
    if (!confirm('Delete this SOP?')) return
    try {
      await api.deleteSOP(id)
      load()
    } catch (err) {
      alert('Delete failed: ' + err)
    }
  }

  const toggleStatus = async (sop: SOP) => {
    try {
      const newStatus = sop.status === 'active' ? 'paused' : 'active'
      await api.updateSOP(sop.id, { status: newStatus })
      load()
    } catch (err) {
      alert('Toggle failed: ' + err)
    }
  }

  const handleImport = async () => {
    try {
      const items = JSON.parse(importData)
      const result = await api.importSOPs(items)
      alert(`Imported ${result.created} SOPs. Errors: ${result.errors.length}`)
      setImportModal(false)
      load()
    } catch (err) {
      alert('Import failed: ' + err)
    }
  }

  // Weekday bitmask: bit 0=Mon ... 6=Sun (matches backend _should_run_today)
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const toggleDay = (bit: number) =>
    setForm((f: any) => ({ ...f, days_of_week: (f.days_of_week || 0) ^ (1 << bit) }))

  const freqLabel = (f: string) => {
    const map: Record<string, string> = { daily: 'Daily', hourly: 'Hourly', weekly: 'Weekly', monthly: 'Monthly', weekday: 'Weekdays' }
    return map[f] || f
  }

  const priorityColor = (p: string) => {
    const map: Record<string, string> = { high: 'bg-rose-50 text-rose-700', medium: 'bg-amber-50 text-amber-700', low: 'bg-emerald-50 text-emerald-700' }
    return map[p] || 'bg-slate-100 text-slate-600'
  }

  return (
    <div>
      <PageHeader title="Manage SOPs" subtitle={`${sops.length} SOPs across ${departments.length} departments`}
        actions={
          <>
            <select value={selectedDept} onChange={e => setSelectedDept(e.target.value)} className="field w-auto">
              <option value="all">All Departments</option>
              {departments.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
            <button onClick={() => setImportModal(true)} className="btn-ghost">Import JSON</button>
            <button onClick={() => openCreate()} className="btn-primary"><Plus size={16} /> Add SOP</button>
          </>
        } />

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => <Card key={i} className="h-24 animate-pulse bg-slate-50 dark:bg-slate-800/40"><span /></Card>)}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={<FolderOpen size={26} />}
          title={`No SOPs ${selectedDept !== 'all' ? `in ${selectedDept}` : 'yet'}`}
          hint="Create your first SOP or import from a JSON file."
          action={
            <div className="flex gap-2 justify-center">
              <button onClick={() => openCreate()} className="btn-primary">Create SOP</button>
              <button onClick={() => setImportModal(true)} className="btn-ghost">Import JSON</button>
            </div>
          } />
      ) : (
        <div className="space-y-3">
          {filtered.map((sop) => (
            <Card key={sop.id} className="p-5 border-l-4 border-brand-400">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <h3 className="font-semibold text-lg">{sop.title}</h3>
                    <span className="badge bg-slate-100 text-slate-600">{freqLabel(sop.frequency)}</span>
                    <span className={`badge ${priorityColor(sop.priority)}`}>{sop.priority}</span>
                    <span className="badge bg-brand-50 text-brand-700">{sop.department}</span>
                    <span className={`badge ${sop.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                      {sop.status}
                    </span>
                  </div>
                  {sop.description && <p className="text-sm muted mb-2 truncate">{sop.description}</p>}
                  <div className="flex flex-wrap gap-4 text-sm muted">
                    <span className="flex items-center gap-1.5 tabular"><Clock size={14} /> {sop.start_time}{sop.end_time ? ` - ${sop.end_time}` : ''}</span>
                    <span className="flex items-center gap-1.5"><Users size={14} /> {sop.assigned_to_name}</span>
                    <span className="flex items-center gap-1.5"><AlertTriangle size={14} /> Admin: {sop.admin_name}</span>
                  </div>
                  <div className="flex flex-wrap gap-4 mt-1.5 text-xs muted tabular">
                    <span>Notify {sop.notify_before_min}min before</span>
                    <span>Check {sop.notify_after_min}min after</span>
                    <span>Escalate after {sop.admin_notify_after_min}min</span>
                    {sop.requires_attachment && <span className="text-brand-600 inline-flex items-center gap-1"><Paperclip size={12} /> Attachment</span>}
                  </div>
                </div>
                <div className="flex items-center gap-0.5 ml-4 shrink-0">
                  <button onClick={() => toggleStatus(sop)} className="p-2 rounded-lg text-slate-400 hover:bg-slate-100" title={sop.status === 'active' ? 'Pause' : 'Activate'}>
                    {sop.status === 'active' ? <PauseCircle size={18} className="text-amber-500" /> : <Play size={18} className="text-emerald-500" />}
                  </button>
                  <button onClick={() => openEdit(sop)} className="p-2 rounded-lg text-slate-400 hover:text-brand-600 hover:bg-brand-50"><Edit2 size={16} /></button>
                  <button onClick={() => remove(sop.id)} className="p-2 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50"><Trash2 size={16} /></button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-slate-900/40 backdrop-blur-sm" onClick={() => setShowForm(false)}>
          <div className="card p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-pop animate-fade-in" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold">{editSOP ? 'Edit SOP' : 'Create SOP'}</h2>
              <button onClick={() => setShowForm(false)} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={18} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="label">Title *</label>
                <input type="text" value={form.title} onChange={e => setForm({...form, title: e.target.value})}
                  className="field" />
              </div>
              <div>
                <label className="label">Description</label>
                <textarea value={form.description} onChange={e => setForm({...form, description: e.target.value})}
                  className="field" rows={2} />
              </div>
              <div>
                <label className="label">Department *</label>
                <select value={form.department} onChange={e => setForm({...form, department: e.target.value})}
                  className="field">
                  <option value="">Select...</option>
                  {departments.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Frequency</label>
                  <select value={form.frequency} onChange={e => setForm({...form, frequency: e.target.value})}
                    className="field">
                    <option value="daily">Daily</option>
                    <option value="hourly">Hourly</option>
                    <option value="weekday">Weekdays (Mon-Fri)</option>
                    <option value="weekly">Weekly</option>
                    <option value="monthly">Monthly</option>
                  </select>
                </div>
                <div>
                  <label className="label">Priority</label>
                  <select value={form.priority} onChange={e => setForm({...form, priority: e.target.value})}
                    className="field">
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </div>
              </div>
              {form.frequency === 'weekly' && (
                <div>
                  <label className="label">Days of week *</label>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {DAYS.map((d, bit) => {
                      const on = ((form.days_of_week || 0) & (1 << bit)) !== 0
                      return (
                        <button type="button" key={d} onClick={() => toggleDay(bit)}
                          className={`px-2.5 py-1 rounded-md text-xs font-semibold border transition ${on ? 'bg-brand-600 text-white border-brand-600' : 'muted border-[var(--border)] hover:bg-slate-50'}`}>
                          {d}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
              {form.frequency === 'monthly' && (
                <div>
                  <label className="label">Day of month * (1–31)</label>
                  <input type="number" min="1" max="31" value={form.day_of_month ?? 1}
                    onChange={e => setForm({ ...form, day_of_month: parseInt(e.target.value) || 1 })}
                    className="field" />
                </div>
              )}
              {form.frequency === 'hourly' && (
                <div>
                  <label className="label">Every N hours * (1–24)</label>
                  <input type="number" min="1" max="24" value={form.interval_hours ?? 1}
                    onChange={e => setForm({ ...form, interval_hours: parseInt(e.target.value) || 1 })}
                    className="field" />
                  <p className="text-xs text-gray-500 mt-1">
                    Fires every {form.interval_hours || 1}h from Start Time to End Time each day.
                    Set an End Time below (else runs until 23:59).
                  </p>
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Start Time *</label>
                  <input type="time" value={form.start_time} onChange={e => setForm({...form, start_time: e.target.value})}
                    className="field" />
                </div>
                <div>
                  <label className="label">End Time</label>
                  <input type="time" value={form.end_time} onChange={e => setForm({...form, end_time: e.target.value})}
                    className="field" />
                </div>
              </div>
              <div>
                <label className="label">Assigned Employee *</label>
                <select value={form.assigned_to_id} onChange={e => setForm({...form, assigned_to_id: e.target.value})}
                  className="field">
                  <option value="">Select...</option>
                  {[...employees]
                    .sort((a, b) => {
                      // SOP's own department first, then by department, then name —
                      // but never HIDE an employee, so a cross-department assignee
                      // (e.g. assigned from another section) stays selectable.
                      const ad = a.department === form.department ? 0 : 1
                      const bd = b.department === form.department ? 0 : 1
                      return ad - bd
                        || (a.department || '').localeCompare(b.department || '')
                        || (a.name || '').localeCompare(b.name || '')
                    })
                    .map(emp => (
                      <option key={emp.id} value={emp.id}>
                        {emp.name} — {emp.role} · {emp.department}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <label className="label">Admin (for escalation)</label>
                <select value={form.admin_id} onChange={e => setForm({...form, admin_id: e.target.value})}
                  className="field">
                  <option value="">Select...</option>
                  {employees.filter(e => e.is_admin).map(emp => (
                    <option key={emp.id} value={emp.id}>{emp.name}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="label">Notify Before (min)</label>
                  <input type="number" value={form.notify_before_min} onChange={e => setForm({...form, notify_before_min: parseInt(e.target.value) || 0})}
                    className="field" min="0" />
                </div>
                <div>
                  <label className="label">Check After (min)</label>
                  <input type="number" value={form.notify_after_min} onChange={e => setForm({...form, notify_after_min: parseInt(e.target.value) || 0})}
                    className="field" min="0" />
                </div>
                <div>
                  <label className="label">Escalate After (min)</label>
                  <input type="number" value={form.admin_notify_after_min} onChange={e => setForm({...form, admin_notify_after_min: parseInt(e.target.value) || 0})}
                    className="field" min="0" />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.requires_attachment} onChange={e => setForm({...form, requires_attachment: e.target.checked})} />
                Requires photo attachment
              </label>
              <div>
                <label className="label">Number of photos required to complete</label>
                <input
                  type="number" min={0}
                  value={(form.attachment_checklist || []).length}
                  onChange={e => setForm((f: any) => {
                    const n = Math.max(0, parseInt(e.target.value) || 0)
                    const cur = f.attachment_checklist || []
                    const arr = Array.from({ length: n }, (_, i) => cur[i] ?? `Photo ${i + 1}`)
                    return { ...f, attachment_checklist: arr, requires_attachment: n > 0 ? true : f.requires_attachment }
                  })}
                  className="field" />
                <p className="text-xs text-gray-400 mb-1">Staff must send this many photos to complete the task, one at a time. Rename each below (optional).</p>
              </div>
              <div>
                <label className="label">Photo checklist (one per item)</label>
                <p className="text-xs text-gray-400 mb-1">Each item = one required photo, collected in order. Leave empty for a single optional photo.</p>
                {(form.attachment_checklist || []).map((item: string, i: number) => (
                  <div key={i} className="flex gap-2 mb-1">
                    <input value={item}
                      onChange={e => setForm((f: any) => {
                        const arr = [...(f.attachment_checklist || [])]; arr[i] = e.target.value
                        return { ...f, attachment_checklist: arr }
                      })}
                      placeholder={`Item ${i + 1} (e.g. Cold Room)`}
                      className="flex-1 border rounded-lg p-2 text-sm" />
                    <button type="button"
                      onClick={() => setForm((f: any) => ({
                        ...f, attachment_checklist: (f.attachment_checklist || []).filter((_: string, j: number) => j !== i)
                      }))}
                      className="px-2 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50"><X size={16} /></button>
                  </div>
                ))}
                <button type="button"
                  onClick={() => setForm((f: any) => ({ ...f, attachment_checklist: [...(f.attachment_checklist || []), ''] }))}
                  className="text-sm text-brand-600 hover:underline mt-1">+ Add checklist item</button>
              </div>
              <div className="flex gap-2 pt-2">
                <button onClick={() => setShowForm(false)} className="btn-ghost flex-1">Cancel</button>
                <button onClick={save} className="btn-primary flex-1">{editSOP ? 'Update' : 'Create'}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Import Modal */}
      {importModal && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-slate-900/40 backdrop-blur-sm" onClick={() => setImportModal(false)}>
          <div className="card p-6 w-full max-w-2xl shadow-pop animate-fade-in" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-bold">Import SOPs (JSON)</h2>
              <button onClick={() => setImportModal(false)} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={18} /></button>
            </div>
            <p className="text-sm muted mb-4">
              Paste a JSON array of SOP objects. Required: title, department, start_time, assigned_to_id.
            </p>
            <textarea
              value={importData}
              onChange={e => setImportData(e.target.value)}
              className="field font-mono"
              rows={10}
              placeholder='[{"title":"Daily Report","department":"Factory Operations","start_time":"12:00","assigned_to_id":"EMP_ID","frequency":"daily"}]'
            />
            <div className="flex gap-2 mt-4">
              <button onClick={() => setImportModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleImport} className="btn-primary flex-1">Import</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
