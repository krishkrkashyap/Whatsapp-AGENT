import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Search, Upload, UserPlus, X, UserMinus, UserCheck, Bell, Pencil, Trash2, Users } from 'lucide-react'
import { PageHeader, Card, EmptyState } from '../components/ui'

interface Employee {
  id: string; name: string; department: string; role: string;
  whatsapp_number: string; is_admin: boolean; is_active: boolean; on_leave?: boolean;
  registered_via?: string; created_at?: string;
}
interface Registration { id: string; name: string; whatsapp_number: string; department: string; status: string; created_at: string }

const blank = { id: '', name: '', department: '', role: '', whatsapp_number: '', is_admin: false, on_leave: false }

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?'
}

export default function Employees() {
  const [employees, setEmployees] = useState<Employee[]>([])
  const [importing, setImporting] = useState(false)
  const [search, setSearch] = useState('')
  const [deptFilter, setDeptFilter] = useState('all')
  const [showAddModal, setShowAddModal] = useState(false)
  const [addForm, setAddForm] = useState({ ...blank })
  const [adding, setAdding] = useState(false)
  const [showInactive, setShowInactive] = useState(false)
  const [pendingRegs, setPendingRegs] = useState<Registration[]>([])
  const [showEditModal, setShowEditModal] = useState(false)
  const [editForm, setEditForm] = useState({ ...blank })
  const [editing, setEditing] = useState(false)

  const [loaded, setLoaded] = useState(false)
  const loadData = () => {
    const fetcher = showInactive ? api.getAllEmployees : api.getEmployees
    fetcher().then(setEmployees).catch(() => {}).finally(() => setLoaded(true))
    api.getPendingRegistrations().then(setPendingRegs).catch(() => setPendingRegs([]))
  }
  useEffect(() => { loadData() }, [showInactive])

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return
    setImporting(true)
    try { const r = await api.importEmployees(file); alert(`Imported ${r.imported} employees.`); loadData() }
    catch (err) { alert('Import failed. ' + err) } finally { setImporting(false) }
  }
  const norm = (n: string) => (n.startsWith('+') ? n : '+' + n)
  const handleAdd = async () => {
    if (!addForm.name || !addForm.department || !addForm.role || !addForm.whatsapp_number) { alert('All fields are required.'); return }
    setAdding(true)
    try { await api.createEmployee({ ...addForm, whatsapp_number: norm(addForm.whatsapp_number) }); setShowAddModal(false); setAddForm({ ...blank }); loadData() }
    catch (err) { alert('Could not add employee. ' + err) } finally { setAdding(false) }
  }
  const handleEdit = async () => {
    if (!editForm.name || !editForm.department || !editForm.role || !editForm.whatsapp_number) { alert('All fields are required.'); return }
    setEditing(true)
    try { await api.updateEmployee(editForm.id, { ...editForm, whatsapp_number: norm(editForm.whatsapp_number) }); setShowEditModal(false); loadData() }
    catch (err) { alert('Could not update. ' + err) } finally { setEditing(false) }
  }
  const handleDeactivate = async (id: string) => { if (!confirm('Deactivate this employee?')) return; try { await api.deactivateEmployee(id); loadData() } catch (e) { alert('Failed. ' + e) } }
  const handleActivate = async (id: string) => { try { await api.activateEmployee(id); loadData() } catch (e) { alert('Failed. ' + e) } }
  const handleDelete = async (id: string, name: string) => { if (!confirm(`Delete "${name}" permanently?`)) return; try { await api.deleteEmployee(id); loadData() } catch (e) { alert('Could not delete. ' + e) } }
  const handleApproveReg = async (id: string) => { try { await api.approveRegistration(id); loadData() } catch (e) { alert('Failed. ' + e) } }
  const handleRejectReg = async (id: string) => { if (!confirm('Reject this registration?')) return; try { await api.rejectRegistration(id); loadData() } catch (e) { alert('Failed. ' + e) } }

  const departments = [...new Set(employees.map(e => e.department))].sort()
  const filtered = employees.filter(e => {
    const ms = search === '' || e.name.toLowerCase().includes(search.toLowerCase()) || e.role.toLowerCase().includes(search.toLowerCase()) || e.whatsapp_number.includes(search)
    return ms && (deptFilter === 'all' || e.department === deptFilter)
  })

  return (
    <div>
      <PageHeader title="Employees" subtitle="Team roster, registrations and access."
        actions={
          <>
            <label className="btn-ghost cursor-pointer"><Upload size={16} /> {importing ? 'Importing…' : 'Import CSV'}
              <input type="file" accept=".csv" onChange={handleImport} className="hidden" /></label>
            <button onClick={() => { setAddForm({ ...blank }); setShowAddModal(true) }} className="btn-primary"><UserPlus size={16} /> Add</button>
          </>
        } />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        {[
          { label: 'Total', value: employees.length, rule: 'bg-brand-400' },
          { label: 'Active', value: employees.filter(e => e.is_active).length, rule: 'bg-emerald-400' },
          { label: 'On leave', value: employees.filter(e => e.on_leave).length, rule: 'bg-amber-400' },
          { label: 'Admins', value: employees.filter(e => e.is_admin).length, rule: 'bg-sky-400' },
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

      {pendingRegs.length > 0 && (
        <Card className="p-4 mb-4 border-amber-200 bg-amber-50/60">
          <h2 className="font-bold text-amber-800 flex items-center gap-2 mb-3"><Bell size={16} /> {pendingRegs.length} pending registration{pendingRegs.length > 1 ? 's' : ''}</h2>
          <div className="space-y-2">
            {pendingRegs.map(r => (
              <div key={r.id} className="flex items-center justify-between card p-3">
                <div><p className="font-semibold">{r.name}</p><p className="muted text-sm tabular">{r.whatsapp_number} · {new Date(r.created_at).toLocaleDateString()}</p></div>
                <div className="flex gap-2">
                  <button onClick={() => handleApproveReg(r.id)} className="btn-primary">Approve</button>
                  <button onClick={() => handleRejectReg(r.id)} className="btn-ghost">Reject</button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Filters */}
      <Card className="p-3 mb-4 flex flex-wrap gap-2 items-center">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 muted" />
          <input className="field pl-9" placeholder="Search name, role, number…" value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <select value={deptFilter} onChange={e => setDeptFilter(e.target.value)} className="field w-auto">
          <option value="all">All departments</option>
          {departments.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm muted px-2">
          <input type="checkbox" className="w-4 h-4 rounded accent-brand-600" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} /> Inactive
        </label>
        <span className="muted text-sm ml-auto tabular">{filtered.length} of {employees.length}</span>
      </Card>

      {/* Table */}
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left muted border-b border-[var(--border)]">
                <th className="font-semibold px-4 py-3">Employee</th>
                <th className="font-semibold px-4 py-3">Department</th>
                <th className="font-semibold px-4 py-3">Role</th>
                <th className="font-semibold px-4 py-3">WhatsApp</th>
                <th className="font-semibold px-4 py-3">Status</th>
                <th className="font-semibold px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(e => (
                <tr key={e.id} className={`border-b border-[var(--border)] last:border-0 hover:bg-slate-50/70 transition ${!e.is_active ? 'opacity-55' : ''}`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg bg-brand-50 text-brand-700 grid place-items-center text-xs font-bold">{initials(e.name)}</div>
                      <div>
                        <p className="font-semibold flex items-center gap-1.5">{e.name}
                          {e.is_admin && <span className="badge bg-brand-50 text-brand-700">Admin</span>}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3"><span className="badge bg-slate-100 text-slate-600">{e.department}</span></td>
                  <td className="px-4 py-3 muted">{e.role}</td>
                  <td className="px-4 py-3 tabular">{e.whatsapp_number}</td>
                  <td className="px-4 py-3">
                    {!e.is_active
                      ? <span className="badge bg-slate-100 text-slate-500"><span className="w-1.5 h-1.5 rounded-full bg-current" /> Inactive</span>
                      : e.on_leave
                        ? <span className="badge bg-amber-50 text-amber-700"><span className="w-1.5 h-1.5 rounded-full bg-current" /> On leave</span>
                        : <span className="badge bg-emerald-50 text-emerald-700"><span className="w-1.5 h-1.5 rounded-full bg-current" /> Active</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-0.5">
                      <button onClick={() => { setEditForm({ id: e.id, name: e.name, department: e.department, role: e.role, whatsapp_number: e.whatsapp_number, is_admin: e.is_admin, on_leave: !!e.on_leave }); setShowEditModal(true) }} className="p-1.5 rounded-lg text-slate-400 hover:text-brand-600 hover:bg-brand-50" title="Edit"><Pencil size={15} /></button>
                      {e.is_active
                        ? <button onClick={() => handleDeactivate(e.id)} className="p-1.5 rounded-lg text-slate-400 hover:text-amber-600 hover:bg-amber-50" title="Deactivate"><UserMinus size={15} /></button>
                        : <button onClick={() => handleActivate(e.id)} className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-600 hover:bg-emerald-50" title="Activate"><UserCheck size={15} /></button>}
                      <button onClick={() => handleDelete(e.id, e.name)} className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50" title="Delete"><Trash2 size={15} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length === 0 && (
          <div className="p-10"><EmptyState icon={<Users size={26} />} title={employees.length === 0 ? 'No employees yet' : 'No matches'} hint={employees.length === 0 ? 'Import a CSV or add your first employee.' : 'Try a different search or department.'} /></div>
        )}
      </Card>

      {(showAddModal || showEditModal) && (() => {
        const editMode = showEditModal
        const form = editMode ? editForm : addForm
        const setForm = editMode ? setEditForm : setAddForm
        const close = () => editMode ? setShowEditModal(false) : setShowAddModal(false)
        return (
          <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-slate-900/40 backdrop-blur-sm" onClick={close}>
            <div onClick={e => e.stopPropagation()} className="card p-6 w-full max-w-md shadow-pop animate-fade-in">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">{editMode ? 'Edit employee' : 'Add employee'}</h2>
                <button onClick={close} className="p-1.5 rounded-lg hover:bg-slate-100"><X size={18} /></button>
              </div>
              <div className="space-y-3">
                <div><label className="label">Name</label><input className="field" value={form.name} onChange={e => setForm((f: any) => ({ ...f, name: e.target.value }))} /></div>
                <div className="grid grid-cols-2 gap-2">
                  <div><label className="label">Department</label><input className="field" value={form.department} onChange={e => setForm((f: any) => ({ ...f, department: e.target.value }))} /></div>
                  <div><label className="label">Role</label><input className="field" value={form.role} onChange={e => setForm((f: any) => ({ ...f, role: e.target.value }))} /></div>
                </div>
                <div><label className="label">WhatsApp number</label><input className="field tabular" placeholder="+919876543210" value={form.whatsapp_number} onChange={e => setForm((f: any) => ({ ...f, whatsapp_number: e.target.value }))} /></div>
                <label className="flex items-center gap-2.5 text-sm cursor-pointer"><input type="checkbox" className="w-4 h-4 rounded accent-brand-600" checked={form.is_admin} onChange={e => setForm((f: any) => ({ ...f, is_admin: e.target.checked }))} /> Administrator</label>
                {editMode && (
                  <label className="flex items-center gap-2.5 text-sm cursor-pointer"><input type="checkbox" className="w-4 h-4 rounded accent-amber-500" checked={(form as any).on_leave} onChange={e => setForm((f: any) => ({ ...f, on_leave: e.target.checked }))} /> On leave <span className="muted text-xs">(bot sends no tasks)</span></label>
                )}
              </div>
              <div className="flex gap-2 mt-5">
                <button onClick={close} className="btn-ghost flex-1">Cancel</button>
                <button onClick={editMode ? handleEdit : handleAdd} disabled={editMode ? editing : adding} className="btn-primary flex-1">{(editMode ? editing : adding) ? 'Saving…' : editMode ? 'Save changes' : 'Add employee'}</button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
