import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Users, CheckSquare, BookOpen, LogOut, BarChart3,
  AlertTriangle, MessageCircle, Settings, ClipboardList, Menu, X,
} from 'lucide-react'
import { logout } from '../api/client'

const groups: { heading: string; links: { to: string; label: string; icon: any }[] }[] = [
  {
    heading: 'Overview',
    links: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/analytics', label: 'Analytics', icon: BarChart3 },
    ],
  },
  {
    heading: 'Operations',
    links: [
      { to: '/tasks', label: 'Tasks', icon: CheckSquare },
      { to: '/sops', label: 'SOPs', icon: ClipboardList },
      { to: '/escalations', label: 'Escalations', icon: AlertTriangle },
    ],
  },
  {
    heading: 'People & Knowledge',
    links: [
      { to: '/employees', label: 'Employees', icon: Users },
      { to: '/conversations', label: 'Conversations', icon: MessageCircle },
      { to: '/knowledge-base', label: 'Knowledge Base', icon: BookOpen },
    ],
  },
]

export default function Sidebar() {
  const [mobileOpen, setMobileOpen] = useState(false)

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition ${
      isActive
        ? 'bg-brand-50 text-brand-700'
        : 'text-slate-500 hover:text-slate-900 hover:bg-slate-50'
    }`

  const nav = (
    <>
      <div className="h-16 px-5 flex items-center gap-2.5 border-b border-[var(--border)]">
        <div className="w-9 h-9 rounded-xl bg-brand-600 text-white grid place-items-center text-lg shadow-card">🍰</div>
        <div className="leading-tight">
          <div className="font-extrabold tracking-tight">Crusty</div>
          <div className="text-[11px] muted -mt-0.5">Operations console</div>
        </div>
        <button onClick={() => setMobileOpen(false)} className="lg:hidden ml-auto p-1.5 rounded-lg hover:bg-slate-100">
          <X size={18} />
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
        {groups.map(g => (
          <div key={g.heading}>
            <p className="px-3 mb-1.5 text-[10px] font-bold uppercase tracking-wider muted">{g.heading}</p>
            <div className="space-y-0.5">
              {g.links.map(l => (
                <NavLink key={l.to} to={l.to} end={l.to === '/'} onClick={() => setMobileOpen(false)} className={linkClass}>
                  {({ isActive }) => (
                    <>
                      {isActive && <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r bg-brand-600" />}
                      <l.icon size={18} strokeWidth={2} />
                      {l.label}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="p-3 border-t border-[var(--border)]">
        <NavLink to="/settings" onClick={() => setMobileOpen(false)} className={linkClass}>
          <Settings size={18} /> Settings
        </NavLink>
        <button onClick={logout}
          className="w-full mt-0.5 flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-slate-500 hover:text-rose-600 hover:bg-rose-50 transition">
          <LogOut size={18} /> Sign out
        </button>
      </div>
    </>
  )

  return (
    <>
      <button onClick={() => setMobileOpen(true)}
        className="lg:hidden fixed top-3 left-3 z-50 p-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-card">
        <Menu size={18} />
      </button>

      {mobileOpen && <div className="lg:hidden fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-40" onClick={() => setMobileOpen(false)} />}

      <aside className={`
        fixed lg:static inset-y-0 left-0 z-50 w-64 flex flex-col
        bg-[var(--bg-card)] border-r border-[var(--border)]
        transform transition-transform duration-300
        ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
      `}>
        {nav}
      </aside>
    </>
  )
}
