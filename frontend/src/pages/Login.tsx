import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Lock, User } from 'lucide-react'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      const res = await api.login(username, password)
      localStorage.setItem('token', res.access_token)
      navigate('/')
    } catch { setError('Invalid username or password.') }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-[100dvh] grid lg:grid-cols-2 bg-[var(--bg-app)]">
      {/* Brand panel */}
      <div className="hidden lg:flex flex-col justify-between p-12 bg-brand-600 text-white relative overflow-hidden">
        <div className="absolute -top-24 -right-24 w-96 h-96 rounded-full bg-white/10 blur-2xl" />
        <div className="absolute bottom-0 -left-20 w-80 h-80 rounded-full bg-brand-800/40 blur-2xl" />
        <div className="relative flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-white/15 grid place-items-center text-2xl">🍰</div>
          <span className="font-extrabold text-lg tracking-tight">Crusty</span>
        </div>
        <div className="relative">
          <h2 className="text-3xl font-extrabold leading-tight tracking-tight">Run your kitchen on WhatsApp.</h2>
          <p className="text-white/70 mt-3 max-w-sm">Assign tasks, track SOPs, and collect photo proof — all from the chats your team already uses.</p>
        </div>
        <p className="relative text-white/50 text-sm">Operations console</p>
      </div>

      {/* Form */}
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="lg:hidden flex items-center gap-2.5 mb-8">
            <div className="w-10 h-10 rounded-xl bg-brand-600 text-white grid place-items-center text-xl">🍰</div>
            <span className="font-extrabold tracking-tight">Crusty</span>
          </div>
          <h1 className="page-title">Welcome back</h1>
          <p className="muted text-sm mt-1 mb-6">Sign in to the operations console.</p>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="label">Username</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 muted" />
                <input className="field pl-9" value={username} onChange={e => setUsername(e.target.value)} placeholder="admin" autoFocus />
              </div>
            </div>
            <div>
              <label className="label">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 muted" />
                <input className="field pl-9" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
              </div>
            </div>
            {error && <p className="text-sm text-rose-600 bg-rose-50 rounded-lg px-3 py-2">{error}</p>}
            <button type="submit" disabled={loading} className="btn-primary w-full">{loading ? 'Signing in…' : 'Sign in'}</button>
          </form>
        </div>
      </div>
    </div>
  )
}
