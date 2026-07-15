import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Employees from './pages/Employees'
import Tasks from './pages/Tasks'
import KnowledgeBase from './pages/KnowledgeBase'
import Analytics from './pages/Analytics'
import Escalations from './pages/Escalations'
import ConversationLogs from './pages/ConversationLogs'
import Settings from './pages/Settings'
import SOPs from './pages/SOPs'
import SOPDepartment from './pages/SOPDepartment'
import SOPManage from './pages/SOPManage'
import { initDarkMode } from './api/client'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  useEffect(() => { initDarkMode() }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="employees" element={<Employees />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="knowledge-base" element={<KnowledgeBase />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="escalations" element={<Escalations />} />
          <Route path="conversations" element={<ConversationLogs />} />
          <Route path="settings" element={<Settings />} />
          <Route path="sops" element={<SOPs />} />
          <Route path="sops/department/:department" element={<SOPDepartment />} />
          <Route path="sops/manage" element={<SOPManage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
