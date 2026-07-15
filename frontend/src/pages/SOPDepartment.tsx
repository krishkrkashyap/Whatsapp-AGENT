import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { ArrowLeft, Plus, Edit2, Trash2, Play, PauseCircle, Clock, Users, AlertTriangle, X, Paperclip } from 'lucide-react'
import { Card, EmptyState } from '../components/ui'

interface SOP {
  id: string
  title: string
  description: string | null
  department: string
  frequency: string
  start_time: string
  end_time: string | null
  assigned_to_id: string
  assigned_to_name: string
  admin_id: string
  admin_name: string
  requires_attachment: boolean
  notify_before_min: number
  notify_after_min: number
  admin_notify_after_min: number
  priority: string
  status: string
}

export default function SOPDepartment() {
  const { department } = useParams()
  const deptName = decodeURIComponent(department || '')
  const navigate = useNavigate()
  const [sops, setSOPs] = useState<SOP[]>([])
  const [loading, setLoading] = useState(true)
  const [importModal, setImportModal] = useState(false)
  const [importData, setImportData] = useState('')

  const load = () => {
    setLoading(true)
    api.getSOPs(deptName)
      .then(setSOPs)
      .catch(console.error)
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [deptName])

  // Create/Edit route to the canonical SOP manager (the inline form here was a
  // drifted duplicate missing schedule fields). Pass the SOP id / department so
  // the manager opens the RIGHT editor instead of the full list.
  const openCreate = () => navigate(`/sops/manage?create=1&dept=${encodeURIComponent(deptName)}`)
  const openEdit = (sop: SOP) => navigate(`/sops/manage?edit=${sop.id}`)

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
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/sops')} className="btn-ghost px-2.5"><ArrowLeft size={18} /></button>
        <div>
          <h1 className="page-title">{deptName}</h1>
          <p className="muted text-sm tabular">{sops.length} SOPs</p>
        </div>
        <div className="ml-auto flex gap-2">
          <button onClick={() => setImportModal(true)} className="btn-ghost">Import</button>
          <button onClick={openCreate} className="btn-primary"><Plus size={16} /> Add SOP</button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => <Card key={i} className="h-24 animate-pulse bg-slate-50 dark:bg-slate-800/40"><span /></Card>)}
        </div>
      ) : sops.length === 0 ? (
        <EmptyState icon={<Clock size={26} />} title="No SOPs in this department"
          hint="Add one, or import from the SOP manager."
          action={<button onClick={openCreate} className="btn-primary mx-auto"><Plus size={16} /> Add SOP</button>} />
      ) : (
        <div className="space-y-3">
          {sops.map((sop) => (
            <Card key={sop.id} className="p-5 border-l-4 border-brand-400">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <h3 className="font-semibold text-lg">{sop.title}</h3>
                    <span className="badge bg-slate-100 text-slate-600">{freqLabel(sop.frequency)}</span>
                    <span className={`badge ${priorityColor(sop.priority)}`}>{sop.priority}</span>
                    <span className={`badge ${sop.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                      {sop.status}
                    </span>
                  </div>
                  {sop.description && <p className="text-sm muted mb-2">{sop.description}</p>}
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

      {/* Import Modal */}
      {importModal && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-slate-900/40 backdrop-blur-sm" onClick={() => setImportModal(false)}>
          <div className="card p-6 w-full max-w-2xl shadow-pop animate-fade-in" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-bold">Import SOPs (JSON)</h2>
              <button onClick={() => setImportModal(false)} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={18} /></button>
            </div>
            <p className="text-sm muted mb-4">
              Paste a JSON array of SOP objects. Fields: title, department, start_time, assigned_to_id (employee ID), frequency, priority, etc.
            </p>
            <textarea
              value={importData}
              onChange={e => setImportData(e.target.value)}
              className="field font-mono"
              rows={10}
              placeholder='[{"title":"Daily Production Report","department":"Bakery Chef","start_time":"12:00","assigned_to_id":"EMPLOYEE_ID","frequency":"daily","priority":"medium"}]'
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
