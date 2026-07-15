/* Task edit modal — full field editing for admin from dashboard */
import { useState, useEffect } from 'react'
import { api } from '../api/client'
import { X } from 'lucide-react'

const STATUS_OPTIONS = ['pending', 'in_progress', 'done', 'blocked', 'escalated']

interface Employee { id: string; name: string; department: string }

interface Task {
  id: string; title: string; status: string; priority: string;
  assigned_to_id: string; assigned_by_id?: string;
  due_date: string | null; description?: string;
  requires_attachment?: boolean; sla_enabled?: boolean;
}

interface Props {
  task: Task
  employees: Employee[]
  onClose: () => void
  onSaved: () => void
}

export default function EditTaskModal({ task, employees, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description || '')
  const [status, setStatus] = useState(task.status)
  const [priority, setPriority] = useState(task.priority)
  const [dueDate, setDueDate] = useState(task.due_date ? task.due_date.slice(0, 10) : '')
  const [assignedTo, setAssignedTo] = useState(task.assigned_to_id)
  const [requiresAttachment, setRequiresAttachment] = useState(task.requires_attachment || false)
  const [slaEnabled, setSlaEnabled] = useState(task.sla_enabled !== false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const payload: any = {}
      if (title !== task.title) payload.title = title
      if (description !== (task.description || '')) payload.description = description
      if (status !== task.status) payload.status = status
      if (priority !== task.priority) payload.priority = priority
      if (assignedTo !== task.assigned_to_id) payload.assigned_to_id = assignedTo
      if (requiresAttachment !== (task.requires_attachment || false)) payload.requires_attachment = requiresAttachment
      if (slaEnabled !== (task.sla_enabled !== false)) payload.sla_enabled = slaEnabled

      // Due date handling
      if (dueDate !== (task.due_date ? task.due_date.slice(0, 10) : '')) {
        if (dueDate) {
          payload.due_date = new Date(dueDate + 'T00:00:00').toISOString()
        } else {
          payload.clear_due_date = true
        }
      }

      if (Object.keys(payload).length === 0) {
        onClose()
        return
      }

      await api.updateTask(task.id, payload)
      onSaved()
      onClose()
    } catch (err) {
      setError('Failed to save: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-slate-900/40 backdrop-blur-sm" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="card p-6 w-full max-w-md shadow-pop animate-fade-in">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">Edit task</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={18} /></button>
        </div>

        {error && <p className="mb-3 text-sm text-rose-600 bg-rose-50 rounded-lg px-3 py-2">{error}</p>}

        <div className="space-y-3">
          <div><label className="label">Title</label>
            <input className="field" value={title} onChange={e => setTitle(e.target.value)} /></div>
          <div><label className="label">Description</label>
            <textarea className="field" rows={2} value={description} onChange={e => setDescription(e.target.value)} /></div>

          <div className="grid grid-cols-2 gap-2">
            <div><label className="label">Status</label>
              <select className="field capitalize" value={status} onChange={e => setStatus(e.target.value)}>
                {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select></div>
            <div><label className="label">Priority</label>
              <select className="field" value={priority} onChange={e => setPriority(e.target.value)}>
                <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
              </select></div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div><label className="label">Assignee</label>
              <select className="field" value={assignedTo} onChange={e => setAssignedTo(e.target.value)}>
                <option value="">Select…</option>
                {employees.map(e => <option key={e.id} value={e.id}>{e.name} · {e.department}</option>)}
              </select></div>
            <div><label className="label">Due date</label>
              <input className="field" type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} /></div>
          </div>

          <label className="flex items-center gap-2.5 text-sm cursor-pointer">
            <input type="checkbox" className="w-4 h-4 rounded accent-brand-600" checked={requiresAttachment} onChange={e => setRequiresAttachment(e.target.checked)} />
            Requires photo proof on completion
          </label>
          <label className="flex items-center gap-2.5 text-sm cursor-pointer">
            <input type="checkbox" className="w-4 h-4 rounded accent-brand-600" checked={slaEnabled} onChange={e => setSlaEnabled(e.target.checked)} />
            Escalate if not started on time (SLA)
          </label>
        </div>

        <div className="flex gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost flex-1">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="btn-primary flex-1">{saving ? 'Saving…' : 'Save changes'}</button>
        </div>
      </div>
    </div>
  )
}
