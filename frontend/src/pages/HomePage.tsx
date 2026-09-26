import { useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'

// ─── Types ──────────────────────────────────────────────────────────────────

interface RepoResponse {
  repo_id: string
  name: string
  status: string
  source_url: string | null
  tech_stack: string | null
  test_framework: string | null
  file_count: number | null
  total_size_bytes: number | null
  language_counts: Record<string, number> | null
  file_tree: FileNode | null
  local_path: string
}

interface FileNode {
  type: 'file' | 'dir'
  name: string
  size?: number
  language?: string
  children?: FileNode[]
}

// ─── Small components ────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    cloning:    'bg-yellow-100 text-yellow-800',
    extracting: 'bg-yellow-100 text-yellow-800',
    scanning:   'bg-blue-100 text-blue-700',
    ready:      'bg-green-100 text-green-700',
    error:      'bg-red-100 text-red-700',
  }
  const cls = map[status] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {status === 'cloning' || status === 'extracting' || status === 'scanning'
        ? <span className="mr-1 h-1.5 w-1.5 rounded-full bg-current animate-pulse" />
        : null}
      {status}
    </span>
  )
}

function LanguageBar({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  if (total === 0) return null

  const COLORS = [
    '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
    '#06b6d4','#ec4899','#84cc16','#f97316','#6366f1',
  ]
  const sorted = Object.entries(counts).sort(([, a], [, b]) => b - a)

  return (
    <div className="mt-3">
      <div className="flex h-2 rounded-full overflow-hidden gap-px">
        {sorted.map(([lang, count], i) => (
          <div
            key={lang}
            style={{ width: `${(count / total) * 100}%`, backgroundColor: COLORS[i % COLORS.length] }}
            title={`${lang}: ${count} files`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-3 mt-2">
        {sorted.slice(0, 8).map(([lang, count], i) => (
          <span key={lang} className="flex items-center gap-1 text-xs text-gray-600">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: COLORS[i % COLORS.length] }}
            />
            {lang} <span className="text-gray-400">({Math.round((count / total) * 100)}%)</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function FileTree({ node, depth = 0 }: { node: FileNode; depth?: number }) {
  const [open, setOpen] = useState(depth < 2)
  const isDir = node.type === 'dir'

  if (isDir) {
    return (
      <div>
        <button
          onClick={() => setOpen(o => !o)}
          className="flex items-center gap-1 text-sm text-gray-700 hover:text-blue-600 py-0.5"
          style={{ paddingLeft: `${depth * 14}px` }}
        >
          <span className="text-gray-400 w-4 text-center">{open ? '▾' : '▸'}</span>
          <span className="text-gray-500">📁</span>
          <span className="font-medium">{node.name}</span>
        </button>
        {open && node.children?.map((child, i) => (
          <FileTree key={`${child.name}-${i}`} node={child} depth={depth + 1} />
        ))}
      </div>
    )
  }

  return (
    <div
      className="flex items-center gap-1 text-sm text-gray-600 py-0.5"
      style={{ paddingLeft: `${depth * 14 + 20}px` }}
    >
      <span className="text-gray-400">📄</span>
      <span>{node.name}</span>
      {node.language && (
        <span className="ml-1 text-xs text-gray-400">{node.language}</span>
      )}
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ─── Main Page ───────────────────────────────────────────────────────────────

type InputMode = 'github' | 'zip'

export default function HomePage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<InputMode>('github')
  const [githubUrl, setGithubUrl] = useState('')
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [repo, setRepo] = useState<RepoResponse | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Input validation ──────────────────────────────────────────────────────
  const isValidGithubUrl = (url: string) =>
    /^https?:\/\/github\.com\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+(\.git|\/)?$/.test(url.trim())

  // ── Polling ───────────────────────────────────────────────────────────────
  const startPolling = useCallback((repoId: string) => {
    let attempts = 0
    pollRef.current = setInterval(async () => {
      attempts++
      try {
        const res = await client.get<RepoResponse>(`/repo/${repoId}`)
        setRepo(res.data)
        if (res.data.status === 'ready' || res.data.status === 'error') {
          clearInterval(pollRef.current!)
          setLoading(false)
        }
      } catch {
        // ignore transient network errors during polling
      }
      if (attempts > 60) {          // 60 × 2s = 2 minutes max
        clearInterval(pollRef.current!)
        setLoading(false)
        setError('Repository scanning timed out.')
      }
    }, 2000)
  }, [])

  // ── Submit handlers ───────────────────────────────────────────────────────
  const handleGithubSubmit = async () => {
    const url = githubUrl.trim()
    if (!url) { setError('Please enter a GitHub URL.'); return }
    if (!isValidGithubUrl(url)) {
      setError('Invalid GitHub URL. Expected: https://github.com/owner/repo')
      return
    }
    setError(null); setLoading(true); setRepo(null)
    try {
      const res = await client.post('/repo/github', { url })
      setRepo(res.data)
      startPolling(res.data.repo_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to ingest repository. Please try again.')
      setLoading(false)
    }
  }

  const handleZipSubmit = async () => {
    if (!zipFile) { setError('Please select a ZIP file.'); return }
    setError(null); setLoading(true); setRepo(null)
    const form = new FormData()
    form.append('file', zipFile)
    try {
      const res = await client.post('/repo/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setRepo(res.data)
      startPolling(res.data.repo_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to upload ZIP. Please try again.')
      setLoading(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f?.name.toLowerCase().endsWith('.zip')) setZipFile(f)
    else setError('Please drop a .zip file.')
  }

  const handleReset = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    setRepo(null); setError(null); setLoading(false)
    setGithubUrl(''); setZipFile(null)
  }

  // ─── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav */}
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl font-bold text-gray-900">CodePilot</span>
          <span className="text-2xl font-bold text-blue-600">AI</span>
        </div>
        <span className="ml-2 text-sm text-gray-400 font-medium hidden sm:block">
          Find. Fix. Test. Verify.
        </span>
        <span className="ml-auto text-xs text-gray-400 bg-blue-50 border border-blue-200 rounded px-2 py-0.5">
          Powered by IBM Bob Shell
        </span>
      </nav>

      <div className="max-w-3xl mx-auto px-4 py-10">
        {/* Hero */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Autonomous Software Repair</h1>
          <p className="mt-2 text-gray-500">
            Submit a repository to detect bugs, security issues, and missing tests —<br />
            then let IBM Bob fix them for you.
          </p>
        </div>

        {/* Input card */}
        {!repo && (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
            {/* Mode tabs */}
            <div className="flex gap-1 mb-5 bg-gray-100 rounded-lg p-1">
              {(['github', 'zip'] as InputMode[]).map(m => (
                <button
                  key={m}
                  onClick={() => { setMode(m); setError(null) }}
                  className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                    mode === m
                      ? 'bg-white text-blue-600 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {m === 'github' ? '🔗 GitHub URL' : '📦 ZIP Upload'}
                </button>
              ))}
            </div>

            {mode === 'github' ? (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Public GitHub repository URL
                </label>
                <input
                  type="url"
                  value={githubUrl}
                  onChange={e => { setGithubUrl(e.target.value); setError(null) }}
                  onKeyDown={e => e.key === 'Enter' && handleGithubSubmit()}
                  placeholder="https://github.com/owner/repo"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm
                    focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  disabled={loading}
                />
                <p className="mt-1 text-xs text-gray-400">Only public repositories are supported.</p>
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Upload a ZIP archive
                </label>
                <div
                  onDrop={handleDrop}
                  onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                  onDragLeave={() => setDragOver(false)}
                  onClick={() => fileInputRef.current?.click()}
                  className={`flex flex-col items-center justify-center border-2 border-dashed rounded-lg
                    p-8 cursor-pointer transition-colors ${
                      dragOver
                        ? 'border-blue-400 bg-blue-50'
                        : zipFile
                        ? 'border-green-400 bg-green-50'
                        : 'border-gray-300 hover:border-gray-400'
                    }`}
                >
                  {zipFile ? (
                    <>
                      <span className="text-2xl mb-1">✅</span>
                      <p className="text-sm font-medium text-green-700">{zipFile.name}</p>
                      <p className="text-xs text-gray-400">{formatBytes(zipFile.size)}</p>
                    </>
                  ) : (
                    <>
                      <span className="text-3xl mb-2">📦</span>
                      <p className="text-sm text-gray-600">Drop a .zip file here, or click to browse</p>
                      <p className="text-xs text-gray-400 mt-1">Max 100 MB</p>
                    </>
                  )}
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip"
                  className="hidden"
                  onChange={e => {
                    const f = e.target.files?.[0]
                    if (f) { setZipFile(f); setError(null) }
                  }}
                />
                {zipFile && (
                  <button
                    onClick={e => { e.stopPropagation(); setZipFile(null) }}
                    className="mt-2 text-xs text-gray-400 hover:text-gray-600"
                  >
                    ✕ Remove file
                  </button>
                )}
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              onClick={mode === 'github' ? handleGithubSubmit : handleZipSubmit}
              disabled={loading || (mode === 'github' ? !githubUrl.trim() : !zipFile)}
              className="mt-5 w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300
                text-white font-semibold rounded-lg text-sm transition-colors"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin" />
                  Processing…
                </span>
              ) : (
                '🔍 Analyze Repository'
              )}
            </button>
          </div>
        )}

        {/* Progress / Status */}
        {loading && repo && (
          <div className="mt-4 bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center gap-3">
              <span className="h-5 w-5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
              <div>
                <p className="font-medium text-gray-900">{repo.name}</p>
                <p className="text-sm text-gray-500 capitalize">{repo.status}…</p>
              </div>
              <StatusBadge status={repo.status} />
            </div>
          </div>
        )}

        {/* Error state after submission */}
        {!loading && repo?.status === 'error' && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-xl p-5">
            <p className="font-medium text-red-700">Ingestion Failed</p>
            <p className="text-sm text-red-600 mt-1">
              The repository could not be processed. Check the URL or ZIP and try again.
            </p>
            <button
              onClick={handleReset}
              className="mt-3 text-sm text-blue-600 hover:underline"
            >
              ← Try again
            </button>
          </div>
        )}

        {/* Success — Repository summary */}
        {repo?.status === 'ready' && (
          <div className="mt-4 space-y-4">
            {/* Summary card */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">{repo.name}</h2>
                  {repo.source_url && (
                    <a
                      href={repo.source_url.replace('.git', '')}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-blue-600 hover:underline"
                    >
                      {repo.source_url.replace('.git', '')}
                    </a>
                  )}
                </div>
                <StatusBadge status={repo.status} />
              </div>

              {/* Metadata grid */}
              <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: 'Tech Stack', value: repo.tech_stack ?? '—' },
                  { label: 'Test Framework', value: repo.test_framework ?? '—' },
                  { label: 'Files', value: repo.file_count?.toString() ?? '—' },
                  { label: 'Size', value: repo.total_size_bytes != null ? formatBytes(repo.total_size_bytes) : '—' },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
                    <p className="mt-0.5 text-sm font-semibold text-gray-800 capitalize">{value}</p>
                  </div>
                ))}
              </div>

              {/* Language bar */}
              {repo.language_counts && Object.keys(repo.language_counts).length > 0 && (
                <div className="mt-4">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                    Languages
                  </p>
                  <LanguageBar counts={repo.language_counts} />
                </div>
              )}

              {/* CTA */}
              <div className="mt-5 flex gap-3">
                <button
                  className="flex-1 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm
                    font-semibold rounded-lg transition-colors"
                  onClick={() => navigate(`/analysis/${repo.repo_id}`)}
                >
                  🚀 Start Analysis
                </button>
                <button
                  onClick={handleReset}
                  className="px-4 py-2 border border-gray-300 text-gray-600 text-sm
                    rounded-lg hover:bg-gray-50 transition-colors"
                >
                  ← New Repo
                </button>
              </div>
            </div>

            {/* File tree card */}
            {repo.file_tree && (
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-700">File Tree</h3>
                  <span className="text-xs text-gray-400">{repo.file_count} files</span>
                </div>
                <div className="p-4 max-h-80 overflow-y-auto text-sm font-mono">
                  <FileTree node={repo.file_tree} depth={0} />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Feature overview (shown when no repo loaded) */}
        {!repo && !loading && (
          <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[
              { icon: '🔍', title: 'Detect', desc: 'Bugs, security issues, code quality violations, and missing tests.' },
              { icon: '🤖', title: 'Fix', desc: 'IBM Bob Shell autonomously plans and implements approved fixes.' },
              { icon: '✅', title: 'Verify', desc: 'Tests run automatically. Failures are repaired. A report is generated.' },
            ].map(({ icon, title, desc }) => (
              <div key={title} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="text-2xl mb-2">{icon}</div>
                <h3 className="font-semibold text-gray-800">{title}</h3>
                <p className="text-sm text-gray-500 mt-1">{desc}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
