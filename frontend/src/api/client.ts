const BASE = '/api'

async function fetchJSON(url: string, options?: RequestInit) {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = { ...(options?.headers as Record<string, string> || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (!(options?.body instanceof FormData)) headers['Content-Type'] = 'application/json'

  const res = await fetch(url, { ...options, headers })
  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    // Surface the backend's error detail instead of a cryptic "HTTP 400".
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* non-JSON error body */ }
    throw new Error(detail)
  }
  return res.json()
}

const rangeQS = (start?: string, end?: string) =>
  start && end ? `?start=${start}&end=${end}` : ''

export const api = {
  // Auth
  login: (username: string, password: string) =>
    fetchJSON(`${BASE}/auth/login`, { method: 'POST', body: JSON.stringify({ username, password }) }),

  // Employees
  getEmployees: () => fetchJSON(`${BASE}/employees/`),
  getAllEmployees: () => fetchJSON(`${BASE}/employees/all`),
  createEmployee: (data: { name: string; department: string; role: string; whatsapp_number: string; is_admin: boolean }) =>
    fetchJSON(`${BASE}/employees/`, { method: 'POST', body: JSON.stringify(data) }),
  updateEmployee: (id: string, data: any) =>
    fetchJSON(`${BASE}/employees/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteEmployee: (id: string) =>
    fetchJSON(`${BASE}/employees/${id}`, { method: 'DELETE' }),
  deactivateEmployee: (id: string) =>
    fetchJSON(`${BASE}/employees/${id}/deactivate`, { method: 'POST' }),
  activateEmployee: (id: string) =>
    fetchJSON(`${BASE}/employees/${id}/activate`, { method: 'POST' }),
  importEmployees: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetchJSON(`${BASE}/employees/import`, { method: 'POST', body: form })
  },
  getDepartments: () => fetchJSON(`${BASE}/employees/departments`),
  getPendingRegistrations: () => fetchJSON(`${BASE}/employees/registrations/pending`),
  approveRegistration: (id: string) =>
    fetchJSON(`${BASE}/employees/registrations/${id}/approve`, { method: 'POST' }),
  rejectRegistration: (id: string) =>
    fetchJSON(`${BASE}/employees/registrations/${id}/reject`, { method: 'POST' }),

  // Tasks
  getTasks: (status?: string) => fetchJSON(`${BASE}/tasks/${status ? '?status=' + status : ''}`),
  getPendingTasks: () => fetchJSON(`${BASE}/tasks/pending`),
  getTaskStats: () => fetchJSON(`${BASE}/tasks/stats`),
  assignTask: (data: any) =>
    fetchJSON(`${BASE}/tasks/assign`, { method: 'POST', body: JSON.stringify(data) }),
  bulkAssign: (data: any) =>
    fetchJSON(`${BASE}/tasks/bulk-assign`, { method: 'POST', body: JSON.stringify(data) }),
  updateTaskStatus: (taskId: string, status: string) =>
    fetchJSON(`${BASE}/tasks/${taskId}/status`, { method: 'PUT', body: JSON.stringify({ status }) }),
  updateTask: (taskId: string, data: any) =>
    fetchJSON(`${BASE}/tasks/${taskId}`, { method: 'PUT', body: JSON.stringify(data) }),

  exportTasks: async () => {
    const res = await fetch(`${BASE}/tasks/export`, {
      headers: { Authorization: `Bearer ${getToken()}` }
    })
    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'tasks_export.csv'
    a.click()
    window.URL.revokeObjectURL(url)
  },

  // Knowledge Base
  searchKB: async (query: string) => {
    const form = new FormData()
    form.append('query', query)
    return fetchJSON(`${BASE}/kb/search`, { method: 'POST', body: form })
  },
  uploadKB: (file: File, title: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    return fetchJSON(`${BASE}/kb/upload`, { method: 'POST', body: form })
  },

  // Analytics (F-8)
  getAnalyticsOverview: (start?: string, end?: string) => fetchJSON(`${BASE}/analytics/overview${rangeQS(start, end)}`),
  getTasksByDepartment: (start?: string, end?: string) => fetchJSON(`${BASE}/analytics/tasks-by-department${rangeQS(start, end)}`),
  getTasksByPriority: (start?: string, end?: string) => fetchJSON(`${BASE}/analytics/tasks-by-priority${rangeQS(start, end)}`),
  getDailyTrend: (days = 14, start?: string, end?: string) => fetchJSON(`${BASE}/analytics/daily-trend?days=${days}${start ? `&start=${start}&end=${end}` : ''}`),
  getTopPerformers: (start?: string, end?: string) => fetchJSON(`${BASE}/analytics/top-performers${rangeQS(start, end)}`),
  exportReport: async (start: string, end: string) => {
    const res = await fetch(`${BASE}/analytics/report.xlsx?start=${start}&end=${end}`, {
      headers: { Authorization: `Bearer ${getToken()}` }
    })
    if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`)
    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `bot_report_${start}_to_${end}.xlsx`
    a.click()
    window.URL.revokeObjectURL(url)
  },

  // Escalations (F-7)
  getEscalations: (status?: string) =>
    fetchJSON(`${BASE}/escalations/${status ? '?status=' + status : ''}`),
  resolveEscalation: (id: string) =>
    fetchJSON(`${BASE}/escalations/${id}/resolve`, { method: 'POST' }),

  // Logs (F-6 + F-14)
  getConversations: (employeeId?: string) =>
    fetchJSON(`${BASE}/logs/conversations${employeeId ? '?employee_id=' + employeeId : ''}`),
  getAuditLogs: () => fetchJSON(`${BASE}/logs/audit`),

  // System
  getHealth: () => fetchJSON('/health'),
  getDeepHealth: () => fetchJSON('/health/deep'),
  getOpenWAStatus: () => fetchJSON(`${BASE}/openwa/status`),
  setupOpenWASession: () =>
    fetchJSON(`${BASE}/openwa/setup-session`, { method: 'POST' }),
  getOpenWASessionStatus: () => fetchJSON(`${BASE}/openwa/session-status`),
  connectOpenWA: () => fetchJSON(`${BASE}/openwa/connect`, { method: 'POST' }),
  getOpenWAQR: () => fetchJSON(`${BASE}/openwa/qr`),
  disconnectOpenWA: () => fetchJSON(`${BASE}/openwa/disconnect`, { method: 'POST' }),
  getInternalStats: () => fetchJSON('/internal/stats'),
  getInternalDepartments: () => fetchJSON('/internal/departments'),
  broadcast: (message: string, department: string) =>
    fetchJSON('/internal/broadcast', { method: 'POST', body: JSON.stringify({ message, department }) }),

  // SOPs
  getSOPDepartments: () => fetchJSON(`${BASE}/sops/departments`),
  getSOPs: (department?: string) => fetchJSON(`${BASE}/sops${department ? '?department=' + encodeURIComponent(department) : ''}`),
  getSOP: (id: string) => fetchJSON(`${BASE}/sops/${id}`),
  createSOP: (data: any) =>
    fetchJSON(`${BASE}/sops`, { method: 'POST', body: JSON.stringify(data) }),
  updateSOP: (id: string, data: any) =>
    fetchJSON(`${BASE}/sops/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  bulkSOPStatus: (data: { status: string; paused_until?: string | null; departments?: string[]; sop_ids?: string[] }) =>
    fetchJSON(`${BASE}/sops/bulk-status`, { method: 'POST', body: JSON.stringify(data) }),
  deleteSOP: (id: string) =>
    fetchJSON(`${BASE}/sops/${id}`, { method: 'DELETE' }),
  importSOPs: (items: any[]) =>
    fetchJSON(`${BASE}/sops/import`, { method: 'POST', body: JSON.stringify(items) }),
  getSOPExecutions: (sopId: string) => fetchJSON(`${BASE}/sops/${sopId}/executions`),
  getSOPEmployees: () => fetchJSON(`${BASE}/sops/employees/list`),

  // Settings
  getSettings: () => fetchJSON(`${BASE}/settings/`),
  updateSetting: (key: string, value: string) =>
    fetchJSON(`${BASE}/settings/${key}`, { method: 'PUT', body: JSON.stringify({ value }) }),

  // Department Configs (SLA + Daily Reminders) — note hyphen in path matches FastAPI router prefix
  getDepartmentConfigs: () => fetchJSON(`${BASE}/department-configs/`),
  updateDepartmentConfig: (department: string, data: any) =>
    fetchJSON(`${BASE}/department-configs/${encodeURIComponent(department)}`, { method: 'PUT', body: JSON.stringify(data) }),
}

export function getToken() {
  return localStorage.getItem('token')
}

export function isLoggedIn() {
  return !!getToken()
}

export function logout() {
  localStorage.removeItem('token')
  window.location.href = '/login'
}

// F-16: Dark mode
export function getDarkMode(): boolean {
  return localStorage.getItem('darkMode') === 'true'
}

export function setDarkMode(enabled: boolean) {
  localStorage.setItem('darkMode', String(enabled))
  document.documentElement.classList.toggle('dark', enabled)
}

export function initDarkMode() {
  const dark = getDarkMode()
  document.documentElement.classList.toggle('dark', dark)
}
