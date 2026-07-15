/* F-16: Settings page with dark mode toggle + SLA & Daily Reminder config */
import { useState, useEffect } from 'react'
import { getDarkMode, setDarkMode, api } from '../api/client'
import { Settings as SettingsIcon, Moon, Sun, Server, Shield, Bell, QrCode, RefreshCw, Power } from 'lucide-react'
import { PageHeader } from '../components/ui'

interface DeptConfig {
  department: string; sla_enabled: boolean; reminder_time: string | null;
  last_reminder_date: string | null;
}

export default function Settings() {
  const [dark, setDark] = useState(getDarkMode())
  const [health, setHealth] = useState<any>(null)
  const [openwa, setOpenWA] = useState<any>(null)
  const [settings, setSettings] = useState<any[]>([])
  const [deptConfigs, setDeptConfigs] = useState<DeptConfig[]>([])
  const [deptEdit, setDeptEdit] = useState<Record<string, Partial<DeptConfig>>>({})
  const [qr, setQr] = useState<string>('')
  const [connecting, setConnecting] = useState(false)
  const [sessStatus, setSessStatus] = useState<string | null>(null)

  useEffect(() => {
    api.getHealth().then(setHealth).catch(() => {})
    api.getOpenWAStatus().then((s) => { setOpenWA(s); setSessStatus(s?.session_status || null) }).catch(() => {})
    api.getSettings().then(setSettings).catch(() => {})
    api.getDepartmentConfigs().then(setDeptConfigs).catch(() => {})
    // Keep the connection status live so a reconnect (initializing -> ready)
    // reflects on its own — the session stays linked, no manual refresh needed.
    const iv = setInterval(() => {
      api.getOpenWAStatus().then((s) => { setOpenWA(s); setSessStatus(s?.session_status || null) }).catch(() => {})
    }, 10000)
    return () => clearInterval(iv)
  }, [])

  const refreshOpenWA = () =>
    api.getOpenWAStatus().then((s) => { setOpenWA(s); setSessStatus(s?.session_status || null) }).catch(() => {})

  // Poll the QR/status until the phone links (status 'ready') or we time out.
  const pollQR = () => {
    let tries = 0
    const iv = setInterval(async () => {
      tries++
      try {
        const r = await api.getOpenWAQR()
        setSessStatus(r.status)
        setQr(r.status === 'ready' ? '' : (r.qr_code || ''))
        if (r.status === 'ready') { clearInterval(iv); refreshOpenWA() }
      } catch { /* keep polling */ }
      if (tries > 40) clearInterval(iv)   // ~2 minutes
    }, 3000)
  }

  const handleConnect = async () => {
    setConnecting(true)
    try {
      const r = await api.connectOpenWA()
      setSessStatus(r.status)
      setQr(r.status === 'ready' ? '' : (r.qr_code || ''))
      if (r.status !== 'ready') pollQR()
      else refreshOpenWA()
    } catch (e) {
      alert('Connect failed: ' + e)
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    if (!confirm('Disconnect the WhatsApp session? The bot will stop sending and receiving messages until you reconnect.')) return
    try {
      await api.disconnectOpenWA()
      setQr('')
      refreshOpenWA()
    } catch (e) {
      alert('Disconnect failed: ' + e)
    }
  }

  const liveStatus = sessStatus || openwa?.session_status || null
  const isReady = liveStatus === 'ready'
  // A linked number means the phone was paired and auth persists — so a non-ready
  // status is a transient RECONNECT, not a logout. Only treat it as logged-out
  // (show the QR flow) when no number is linked.
  const linkedNumber = openwa?.phone || null
  const reconnecting = !!linkedNumber && !isReady

  const toggleDark = () => {
    const next = !dark
    setDark(next)
    setDarkMode(next)
  }

  const handleToggleSetting = async (key: string, currentValue: string) => {
    const newValue = currentValue === 'true' ? 'false' : 'true'
    try {
      await api.updateSetting(key, newValue)
      setSettings(settings.map(s => s.key === key ? { ...s, value: newValue } : s))
    } catch (err) {
      alert('Failed to update setting: ' + err)
    }
  }

  const handleSaveValue = async (key: string, value: string) => {
    try {
      await api.updateSetting(key, value)
    } catch (err) {
      alert('Failed to update setting: ' + err)
    }
  }

  const handleSaveDeptConfig = async (dept: string) => {
    const edit = deptEdit[dept]
    if (!edit) return
    try {
      const body: any = {}
      if (edit.sla_enabled !== undefined) body.sla_enabled = edit.sla_enabled
      if (edit.reminder_time !== undefined) body.reminder_time = edit.reminder_time || null
      const updated = await api.updateDepartmentConfig(dept, body)
      setDeptConfigs(prev => prev.map(c => c.department === dept ? updated : c))
      setDeptEdit(prev => { const n = { ...prev }; delete n[dept]; return n })
    } catch (err) {
      alert('Failed to update department config: ' + err)
    }
  }

  return (
    <div>
      <PageHeader title="Settings" subtitle="Appearance, bot behavior, connection and system health." />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Appearance */}
        <div className="card p-6">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            {dark ? <Moon className="w-5 h-5" /> : <Sun className="w-5 h-5" />} Appearance
          </h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Dark Mode</p>
              <p className="text-sm muted">Toggle dark theme across the dashboard</p>
            </div>
            <button onClick={toggleDark}
              className={`relative w-14 h-7 rounded-full transition-colors ${dark ? 'bg-brand-600' : 'bg-gray-300'}`}>
              <span className={`absolute top-0.5 left-0.5 w-6 h-6 bg-white rounded-full shadow transition-transform ${dark ? 'translate-x-7' : ''}`}></span>
            </button>
          </div>
        </div>

        {/* System Behavior (Escalation) */}
        <div className="card p-6">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <SettingsIcon className="w-5 h-5" /> Behavior
          </h2>
          <div className="space-y-4">
            {settings.map(s => {
              const title = s.key.split('_').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
              const isBool = s.value === 'true' || s.value === 'false'
              const isTrue = s.value === 'true'
              return (
                <div key={s.key} className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-medium">{title}</p>
                    <p className="text-xs muted max-w-[220px]">{s.description}</p>
                  </div>
                  {isBool ? (
                    <button onClick={() => handleToggleSetting(s.key, s.value)}
                      className={`relative w-12 h-6 rounded-full transition-colors shrink-0 ${isTrue ? 'bg-brand-600' : 'bg-gray-300'}`}>
                      <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${isTrue ? 'translate-x-6' : ''}`}></span>
                    </button>
                  ) : (
                    <div className="flex items-center gap-2 shrink-0">
                      <input type="text" value={s.value}
                        onChange={e => setSettings(settings.map(x => x.key === s.key ? { ...x, value: e.target.value } : x))}
                        className="field w-16 text-right tabular" />
                      <button onClick={() => handleSaveValue(s.key, s.value)} className="btn-subtle">Save</button>
                    </div>
                  )}
                </div>
              )
            })}
            {settings.length === 0 && <p className="text-sm muted">Loading settings...</p>}
          </div>
        </div>

        {/* SLA & Daily Reminders */}
        <div className="card p-6 lg:col-span-2">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Bell className="w-5 h-5" /> SLA & Daily Reminders
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left muted">
                  <th className="py-2 pr-4 font-semibold">Department</th>
                  <th className="py-2 pr-4">SLA Enabled</th>
                  <th className="py-2 pr-4">Daily Reminder</th>
                  <th className="py-2 pr-4">Reminder Time (HH:MM)</th>
                  <th className="py-2 pr-4">Last Sent</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {deptConfigs.map(cfg => {
                  const edit = deptEdit[cfg.department] || {}
                  const sla = edit.sla_enabled !== undefined ? edit.sla_enabled : cfg.sla_enabled
                  const reminderTime = edit.reminder_time !== undefined ? edit.reminder_time : (cfg.reminder_time || '')
                  const hasChanges = deptEdit[cfg.department] !== undefined
                  const handleField = (field: string, value: any) =>
                    setDeptEdit(prev => ({ ...prev, [cfg.department]: { ...prev[cfg.department], [field]: value } }))
                  return (
                    <tr key={cfg.department} className="border-b border-[var(--border)] hover:bg-[var(--bg-app)] transition">
                      <td className="py-2 pr-4 font-medium">{cfg.department}</td>
                      <td className="py-2 pr-4">
                        <button onClick={() => handleField('sla_enabled', !sla)}
                          className={`relative w-10 h-5 rounded-full transition-colors ${sla ? 'bg-brand-600' : 'bg-gray-300'}`}>
                          <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${sla ? 'translate-x-5' : ''}`}></span>
                        </button>
                      </td>
                      <td className="py-2 pr-4">
                        <button onClick={() => handleField('reminder_time', reminderTime ? null : '09:00')}
                          className={`relative w-10 h-5 rounded-full transition-colors ${reminderTime ? 'bg-brand-600' : 'bg-gray-300'}`}>
                          <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${reminderTime ? 'translate-x-5' : ''}`}></span>
                        </button>
                      </td>
                      <td className="py-2 pr-4">
                        <input type="time" value={reminderTime || ''}
                          onChange={e => handleField('reminder_time', e.target.value || null)}
                          disabled={!reminderTime}
                          className="field w-28 tabular disabled:opacity-40" />
                      </td>
                      <td className="py-2 pr-4 text-xs muted">{cfg.last_reminder_date || '—'}</td>
                      <td className="py-2">
                        {hasChanges ? (
                          <button onClick={() => handleSaveDeptConfig(cfg.department)} className="btn-subtle">Save</button>
                        ) : (
                          <span className="text-xs muted">Saved</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
                {deptConfigs.length === 0 && (
                  <tr><td colSpan={6} className="py-4 text-center muted">Loading department configs...</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="text-xs muted mt-3">
            Global SLA master toggle is in <strong>Behavior</strong> card above. Per-department SLA toggles override the global value.
            Daily reminder sends one WhatsApp message per employee listing all pending manual tasks at the configured time.
          </p>
        </div>

        {/* WhatsApp Connection */}
        <div className="card p-6">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <QrCode className="w-5 h-5" /> WhatsApp Connection
          </h2>
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-sm">Session</span>
              <span className={`text-sm font-bold ${isReady ? 'text-emerald-600' : openwa?.configured === false ? 'muted' : 'text-amber-600'}`}>
                {openwa?.configured === false ? 'DEV Mode'
                  : isReady ? '● Connected'
                  : reconnecting ? '● Reconnecting…'
                  : (liveStatus || 'Not connected')}
              </span>
            </div>
            {linkedNumber && (
              <div className="flex justify-between items-center">
                <span className="text-sm">Number</span>
                <span className="text-sm muted font-mono">{linkedNumber}</span>
              </div>
            )}

            {qr ? (
              <div className="flex flex-col items-center gap-2 py-2">
                <img src={qr} alt="WhatsApp QR code" className="w-56 h-56 border rounded-lg bg-white" />
                <p className="text-xs muted text-center">
                  WhatsApp → <strong>Linked devices</strong> → <strong>Link a device</strong>, then scan. Refreshes automatically.
                </p>
              </div>
            ) : reconnecting ? (
              <p className="text-xs text-amber-600">
                Still linked as <strong>{linkedNumber}</strong> — reconnecting automatically. No need to scan the QR again.
              </p>
            ) : (
              <p className="text-xs muted">
                {isReady ? 'Phone linked and ready.' : 'Click Connect to generate a QR code and link a phone.'}
              </p>
            )}

            <div className="flex gap-2 pt-1">
              <button onClick={handleConnect} disabled={connecting || openwa?.configured === false} className="btn-primary flex-1">
                <QrCode className="w-4 h-4" />
                {connecting ? 'Connecting…' : reconnecting ? 'Reconnect now' : isReady ? 'Reconnect' : 'Connect / Show QR'}
              </button>
              <button onClick={refreshOpenWA} title="Refresh status" className="btn-ghost px-3"><RefreshCw className="w-4 h-4" /></button>
              {isReady && (
                <button onClick={handleDisconnect} title="Disconnect" className="btn-ghost px-3 text-rose-600 border-rose-200 hover:bg-rose-50"><Power className="w-4 h-4" /></button>
              )}
            </div>
            {openwa?.configured === false && (
              <p className="text-xs muted">Set <code>OPENWA_API_KEY</code> in the backend env to enable.</p>
            )}
          </div>
        </div>

        {/* System Health */}
        <div className="card p-6">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Server className="w-5 h-5" /> System Health
          </h2>
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-sm">Backend API</span>
              <span className={`text-sm font-bold ${health?.status === 'ok' ? 'text-emerald-600' : 'text-red-600'}`}>
                {health?.status === 'ok' ? '● Connected' : '● Disconnected'}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm">Version</span>
              <span className="text-sm muted">{health?.version || 'unknown'}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm">WhatsApp Gateway</span>
              <span className={`text-sm font-bold ${openwa?.connected ? 'text-emerald-600' : 'text-amber-600'}`}>
                {openwa?.connected ? 'OpenWA ● Connected' : openwa?.configured === false ? 'DEV Mode' : '● Disconnected'}
              </span>
            </div>
            {openwa?.session_status && (
              <div className="flex justify-between items-center">
                <span className="text-sm">Session Status</span>
                <span className="text-sm muted font-mono">{openwa.session_status}</span>
              </div>
            )}
            {openwa?.session_id && (
              <div className="flex justify-between items-center">
                <span className="text-sm">Session ID</span>
                <span className="text-sm muted font-mono">{openwa.session_id.slice(0, 8)}...</span>
              </div>
            )}
          </div>
        </div>

        {/* Security Info */}
        <div className="card p-6">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Shield className="w-5 h-5" /> Security
          </h2>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span>Authentication</span>
              <span className="text-emerald-600 font-bold">JWT Active</span>
            </div>
            <div className="flex justify-between">
              <span>Session Duration</span>
              <span className="muted">24 hours</span>
            </div>
            <div className="flex justify-between">
              <span>Audit Trail</span>
              <span className="text-emerald-600 font-bold">Enabled</span>
            </div>
            <p className="text-xs muted mt-3 p-3 bg-gray-50 rounded-lg">
              ⚠️ For production, change the default admin password and SECRET_KEY in your .env file.
              Never commit secrets to version control.
            </p>
          </div>
        </div>

        {/* About */}
        <div className="card p-6">
          <h2 className="font-semibold mb-4">About WhatsApp Agent</h2>
          <div className="text-sm text-gray-600 space-y-2">
            <p>Internal employee task management system for ~500 staff via WhatsApp.</p>
            <p>Features: Task assignment, multi-language NLU, RAG knowledge base, automated escalation, analytics, and more.</p>
            <p className="text-xs muted">Built with FastAPI + React + PostgreSQL (pgvector) + OpenWA</p>
          </div>
        </div>
      </div>
    </div>
  )
}
