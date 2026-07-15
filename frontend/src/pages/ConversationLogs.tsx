import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ArrowDown, ArrowUp, MessageCircle } from 'lucide-react'
import { PageHeader, Card, EmptyState, fmtDateTime } from '../components/ui'

interface ConvLog {
  id: string; task_id: string | null; employee_id: string;
  employee_name: string; message_text: string; direction: string;
  message_type: string; language: string | null; created_at: string;
}

export default function ConversationLogs() {
  const [logs, setLogs] = useState<ConvLog[]>([])
  const [employees, setEmployees] = useState<any[]>([])
  const [selectedEmp, setSelectedEmp] = useState('')
  const [auditLogs, setAuditLogs] = useState<any[]>([])
  const [tab, setTab] = useState<'conversations' | 'audit'>('conversations')
  const [loading, setLoading] = useState(true)

  useEffect(() => { api.getEmployees().then(setEmployees).catch(() => {}) }, [])
  useEffect(() => {
    setLoading(true)
    const p = tab === 'conversations'
      ? api.getConversations(selectedEmp || undefined).then(setLogs)
      : api.getAuditLogs().then(setAuditLogs)
    p.catch(() => {}).finally(() => setLoading(false))
  }, [selectedEmp, tab])

  const typeColor = (t: string) => ({
    assignment: 'bg-sky-50 text-sky-700', reply: 'bg-emerald-50 text-emerald-700',
    trouble: 'bg-rose-50 text-rose-700', followup: 'bg-amber-50 text-amber-700',
    escalation: 'bg-rose-50 text-rose-700', help: 'bg-slate-100 text-slate-600',
  } as Record<string, string>)[t] || 'bg-slate-100 text-slate-600'

  return (
    <div>
      <PageHeader title="Conversations" subtitle="Every message in and out, plus the admin audit trail."
        actions={
          <div className="flex items-center gap-1 bg-slate-50 dark:bg-slate-800/60 rounded-lg p-1">
            {(['conversations', 'audit'] as const).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold capitalize transition ${tab === t ? 'bg-[var(--bg-card)] shadow-card text-brand-700' : 'muted hover:text-slate-900'}`}>
                {t === 'audit' ? 'Audit trail' : 'Conversations'}
              </button>
            ))}
          </div>
        } />

      {tab === 'conversations' ? (
        <>
          <Card className="p-3 mb-4 flex gap-3 items-center">
            <select value={selectedEmp} onChange={e => setSelectedEmp(e.target.value)} className="field w-auto">
              <option value="">All employees</option>
              {employees.map((e: any) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
            <span className="muted text-sm ml-auto tabular">{logs.length} messages</span>
          </Card>
          <div className="space-y-2">
            {loading && Array.from({ length: 5 }).map((_, i) => (
              <Card key={`sk-${i}`} className="h-16 animate-pulse bg-slate-50 dark:bg-slate-800/40"><span /></Card>
            ))}
            {!loading && logs.map(l => (
              <Card key={l.id} className="p-4 flex items-start gap-3">
                <div className={`w-7 h-7 rounded-lg grid place-items-center shrink-0 ${l.direction === 'inbound' ? 'bg-sky-50 text-sky-600' : 'bg-emerald-50 text-emerald-600'}`}>
                  {l.direction === 'inbound' ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="font-semibold text-sm">{l.employee_name}</span>
                    <span className={`badge ${typeColor(l.message_type)} capitalize`}>{l.message_type}</span>
                    {l.language && <span className="muted text-xs">{l.language}</span>}
                    <span className="muted text-xs ml-auto tabular">{fmtDateTime(l.created_at)}</span>
                  </div>
                  <p className="text-sm break-words">{l.message_text}</p>
                </div>
              </Card>
            ))}
            {!loading && logs.length === 0 && <EmptyState icon={<MessageCircle size={26} />} title="No conversations yet" hint="Messages between the bot and your team will appear here." />}
          </div>
        </>
      ) : (
        <div className="space-y-2">
          {loading && Array.from({ length: 5 }).map((_, i) => (
            <Card key={`sk-${i}`} className="h-16 animate-pulse bg-slate-50 dark:bg-slate-800/40"><span /></Card>
          ))}
          {!loading && auditLogs.map((l: any) => (
            <Card key={l.id} className="p-4">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm">{l.actor_name || 'System'}</span>
                  <span className="badge bg-brand-50 text-brand-700">{l.action}</span>
                </div>
                <span className="muted text-xs tabular">{fmtDateTime(l.created_at)}</span>
              </div>
              <p className="muted text-xs">{l.resource_type} {l.resource_id ? `#${l.resource_id.slice(0, 8)}` : ''}{l.details && ` · ${JSON.stringify(l.details).slice(0, 100)}`}</p>
            </Card>
          ))}
          {!loading && auditLogs.length === 0 && <EmptyState icon={<MessageCircle size={26} />} title="No audit logs yet" />}
        </div>
      )}
    </div>
  )
}
