import { useState } from 'react'
import { api } from '../api/client'
import { Upload, Search, FileText } from 'lucide-react'
import { PageHeader, Card } from '../components/ui'

export default function KnowledgeBase() {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [uploading, setUploading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [results, setResults] = useState<any[]>([])

  const handleUpload = async () => {
    if (!file || !title) return alert('Select a file and enter a title.')
    setUploading(true)
    try { const r = await api.uploadKB(file, title); alert(`Indexed ${r.chars} characters.`); setFile(null); setTitle('') }
    catch (err) { alert('Upload failed. ' + err) }
    setUploading(false)
  }
  const handleSearch = async () => {
    if (!searchQuery) return
    try { setResults(await api.searchKB(searchQuery)) } catch (err) { alert('Search failed. ' + err) }
  }

  return (
    <div>
      <PageHeader title="Knowledge base" subtitle="Documents the bot can answer questions from." />

      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3"><Upload size={16} className="text-brand-600" /><h2 className="font-bold">Upload a document</h2></div>
          <label className="label">Title</label>
          <input className="field mb-3" placeholder="e.g. Hygiene policy" value={title} onChange={e => setTitle(e.target.value)} />
          <label className="label">File (PDF or TXT)</label>
          <label className="card card-interactive cursor-pointer flex items-center gap-3 p-4 mb-4">
            <FileText size={18} className="muted" />
            <span className="text-sm truncate">{file ? file.name : 'Choose a file…'}</span>
            <input type="file" accept=".pdf,.txt" onChange={e => setFile(e.target.files?.[0] || null)} className="hidden" />
          </label>
          <button onClick={handleUpload} disabled={uploading} className="btn-primary w-full">{uploading ? 'Indexing…' : 'Upload & index'}</button>
        </Card>

        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3"><Search size={16} className="text-brand-600" /><h2 className="font-bold">Search</h2></div>
          <div className="flex gap-2 mb-4">
            <input className="field" placeholder="Search the knowledge base…" value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSearch()} />
            <button onClick={handleSearch} className="btn-ghost">Search</button>
          </div>
          <div className="divide-y divide-[var(--border)]">
            {results.map(r => (
              <div key={r.id} className="py-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold">{r.title}</p>
                  {r.similarity != null && <span className="badge bg-emerald-50 text-emerald-700 tabular">{(r.similarity * 100).toFixed(0)}%</span>}
                </div>
                <p className="muted text-sm mt-1 line-clamp-3">{r.content}</p>
              </div>
            ))}
            {results.length === 0 && searchQuery && <p className="muted text-sm py-3">No results found.</p>}
            {results.length === 0 && !searchQuery && <p className="muted text-sm py-3">Type a query to search indexed documents.</p>}
          </div>
        </Card>
      </div>
    </div>
  )
}
