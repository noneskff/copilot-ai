import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import client from '../api/client'
import { createJobSocket } from '../api/websocket'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Issue {
  id: string
  repo_id: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  category: 'bug' | 'code_quality' | 'security' | 'missing_test'
  title: string
  description: string
  file_path: string | null
  line_number: number | null
  evidence: string | null
  suggested_fix: string | null
  confidence: number | null
  root_cause: { root_cause?: string; fix_strategy?: string } | null
  fix_plan: { steps?: string[]; files_to_change?: string[]; risk_level?: string } | null
  status: string
  detected_at: string
}

interface AnalysisStatus {
  repo_id: string
  status: string
  job_id: string | null
  total_issues: number
  health_score: number | null
  severity_counts: Record<string, number>
  category_counts: Record<string, number>
}

interface RepoInfo {
  name: string
  tech_stack: string | null
}

interface FixJobState {
  job_id: string
  issue_id: string
  status: string
  output_lines: string[]
  diff: string | null
  error: string | null
}

// ─── Sub-components ──────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  high:     'bg-orange-100 text-orange-800 border-orange-200',
  medium:   'bg-yellow-100 text-yellow-800 border-yellow-200',
  low:      'bg-blue-100 text-blue-800 border-blue-200',
}

const CATEGORY_LABELS: Record<string, string> = {
  bug:          'Bug',
  code_quality: 'Code Quality',
  security:     'Security',
  missing_test: 'Missing Test',
}

const CATEGORY_ICONS: Record<string, string> = {
  bug: '🐛', code_quality: '✏️', security: '🔒', missing_test: '🧪',
}

function SeverityBadge({ severity }: { severity: string }) {
  const cls = SEVERITY_STYLES[severity] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-semibold uppercase ${cls}`}>
      {severity}
    </span>
  )
}

function ProgressBar({ pct, message }: { pct: number; message: string }) {
  return (
    <div className="w-full">
      <div className="flex justify-between text-sm text-gray-600 mb-1">
        <span>{message}</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 transition-all duration-500 rounded-full"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function IssueCard({
  issue,
  fixJob,
  onSelect,
  onApprove,
}: {
  issue: Issue
  fixJob: FixJobState | undefined
  onSelect: (i: Issue) => void
  onApprove: (i: Issue) => void
}) {
  const isFixed = issue.status === 'fixed' || fixJob?.status === 'succeeded'
  const isApproved = issue.status === 'approved'
  const isRunning = fixJob?.status === 'running'

  return (
    <div className={`bg-white border rounded-lg p-4 transition-all ${
      isFixed ? 'border-green-200 opacity-75' : 'border-gray-200 hover:border-blue-200 hover:shadow-sm'
    }`}>
      <div className="flex items-start gap-3">
        <span className="text-xl mt-0.5">{CATEGORY_ICONS[issue.category] ?? '⚠️'}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <SeverityBadge severity={issue.severity} />
            <span className="text-xs text-gray-500">{CATEGORY_LABELS[issue.category]}</span>
            {isFixed && (
              <span className="text-xs text-green-700 bg-green-100 border border-green-200 rounded px-1.5 py-0.5">
                ✅ Fixed
              </span>
            )}
            {isRunning && (
              <span className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded px-1.5 py-0.5 flex items-center gap-1">
                <span className="h-2 w-2 rounded-full border border-blue-500 border-t-transparent animate-spin" />
                Bob fixing…
              </span>
            )}
          </div>
          <button
            onClick={() => onSelect(issue)}
            className="mt-1 w-full text-left font-medium text-gray-900 hover:text-blue-700 truncate"
          >
            {issue.title}
          </button>
          {issue.file_path && (
            <p className="text-xs text-gray-500 mt-0.5 font-mono truncate">
              {issue.file_path}{issue.line_number ? `:${issue.line_number}` : ''}
            </p>
          )}
          <p className="text-sm text-gray-600 mt-1 line-clamp-2">{issue.description}</p>
        </div>

        {/* Approve button — only show if not fixed/running */}
        {!isFixed && !isRunning && !isApproved && (
          <button
            onClick={(e) => { e.stopPropagation(); onApprove(issue) }}
            className="flex-shrink-0 text-xs bg-blue-600 hover:bg-blue-700 text-white
              font-medium px-3 py-1.5 rounded-lg transition-colors"
          >
            🤖 Fix
          </button>
        )}
        {isApproved && !isRunning && (
          <span className="flex-shrink-0 text-xs text-gray-400 bg-gray-50 border border-gray-200 rounded px-2 py-1">
            Approved
          </span>
        )}
      </div>

      {issue.evidence && (
        <pre className="mt-2 text-xs bg-gray-50 border border-gray-100 rounded p-2 overflow-x-auto text-gray-700 font-mono">
          {issue.evidence}
        </pre>
      )}

      {/* Show Bob output inline while running */}
      {fixJob && fixJob.output_lines.length > 0 && (
        <div className="mt-2 bg-gray-900 rounded p-2 max-h-32 overflow-y-auto">
          {fixJob.output_lines.map((line, i) => (
            <div key={i} className="text-xs font-mono text-green-300">{line}</div>
          ))}
        </div>
      )}

      {/* Show diff when succeeded */}
      {fixJob?.status === 'succeeded' && fixJob.diff && (
        <details className="mt-2">
          <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
            View diff
          </summary>
          <pre className="mt-1 text-xs bg-gray-900 text-green-300 rounded p-2 overflow-x-auto font-mono max-h-48">
            {fixJob.diff}
          </pre>
        </details>
      )}
    </div>
  )
}

function IssueDetailPanel({
  issue,
  onClose,
  onApprove,
}: {
  issue: Issue
  onClose: () => void
  onApprove: (i: Issue) => void
}) {
  const [planLoading, setPlanLoading] = useState(false)
  const [plan, setPlan] = useState<Issue['fix_plan']>(issue.fix_plan)

  const handleGeneratePlan = async () => {
    setPlanLoading(true)
    try {
      const resp = await client.post(`/issues/${issue.id}/plan`)
      setPlan(resp.data.plan)
    } catch {
      // ignore
    } finally {
      setPlanLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
         onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[85vh] overflow-y-auto"
           onClick={e => e.stopPropagation()}>
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <SeverityBadge severity={issue.severity} />
            <span className="text-sm text-gray-500">{CATEGORY_LABELS[issue.category]}</span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="p-5 space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">{issue.title}</h2>

          {issue.file_path && (
            <div className="text-sm font-mono bg-gray-50 border border-gray-200 rounded px-3 py-2 text-gray-700">
              📄 {issue.file_path}{issue.line_number ? ` : line ${issue.line_number}` : ''}
            </div>
          )}

          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Description</p>
            <p className="text-sm text-gray-700">{issue.description}</p>
          </div>

          {issue.evidence && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Evidence</p>
              <pre className="text-xs bg-gray-900 text-green-300 rounded p-3 overflow-x-auto font-mono">
                {issue.evidence}
              </pre>
            </div>
          )}

          {issue.root_cause?.root_cause && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Root Cause (IBM Bob)</p>
              <p className="text-sm text-gray-700 bg-blue-50 border border-blue-100 rounded p-3">
                {issue.root_cause.root_cause}
              </p>
            </div>
          )}

          {issue.suggested_fix && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Suggested Fix</p>
              <p className="text-sm text-gray-700 bg-green-50 border border-green-100 rounded p-3">
                {issue.suggested_fix}
              </p>
            </div>
          )}

          {/* Fix Plan */}
          {plan ? (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Fix Plan</p>
              <ol className="list-decimal list-inside space-y-1">
                {plan.steps?.map((step, i) => (
                  <li key={i} className="text-sm text-gray-700">{step}</li>
                ))}
              </ol>
              {plan.risk_level && (
                <p className="mt-2 text-xs text-gray-500">
                  Risk level: <span className="font-medium capitalize">{plan.risk_level}</span>
                </p>
              )}
            </div>
          ) : (
            <button
              onClick={handleGeneratePlan}
              disabled={planLoading}
              className="w-full py-2 border border-blue-300 text-blue-600 text-sm font-medium
                rounded-lg hover:bg-blue-50 transition-colors disabled:opacity-50"
            >
              {planLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
                  Generating plan…
                </span>
              ) : '📋 Generate Fix Plan (IBM Bob)'}
            </button>
          )}

          {issue.confidence != null && (
            <p className="text-xs text-gray-400">
              Confidence: {Math.round(issue.confidence * 100)}%
            </p>
          )}

          {issue.status !== 'fixed' && (
            <button
              onClick={() => { onApprove(issue); onClose() }}
              className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm
                font-semibold rounded-lg transition-colors"
            >
              🤖 Approve & Fix with IBM Bob
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AnalysisPage() {
  const { repoId } = useParams<{ repoId: string }>()
  const navigate = useNavigate()

  const [repoInfo, setRepoInfo] = useState<RepoInfo | null>(null)
  const [status, setStatus] = useState<AnalysisStatus | null>(null)
  const [issues, setIssues] = useState<Issue[]>([])
  const [progress, setProgress] = useState<{ pct: number; message: string }>({ pct: 0, message: 'Initializing…' })
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Fix jobs keyed by issue_id
  const [fixJobs, setFixJobs] = useState<Record<string, FixJobState>>({})

  // Filters
  const [filterSeverity, setFilterSeverity] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterFile, setFilterFile] = useState('')

  const wsRef = useRef<WebSocket | null>(null)
  const fixWsRefs = useRef<Record<string, WebSocket>>({})
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Load repo info ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!repoId) return
    client.get(`/repo/${repoId}`).then(r => {
      setRepoInfo({ name: r.data.name, tech_stack: r.data.tech_stack })
    }).catch(() => {})
  }, [repoId])

  // ── Start analysis ──────────────────────────────────────────────────────
  const startAnalysis = useCallback(async () => {
    if (!repoId) return
    setIsAnalyzing(true)
    setIssues([])
    setError(null)
    setProgress({ pct: 5, message: 'Starting analysis…' })

    try {
      const res = await client.post(`/repo/${repoId}/analyze`)
      const jobId = res.data.job_id

      wsRef.current = createJobSocket(jobId, (data) => {
        if (data.event === 'progress') {
          setProgress({ pct: data.pct as number, message: data.message as string })
        } else if (data.event === 'issue_found') {
          setIssues(prev => [...prev, data.issue as Issue])
        } else if (data.event === 'done') {
          setProgress({ pct: 100, message: 'Analysis complete!' })
          setIsAnalyzing(false)
          loadStatus()
        } else if (data.event === 'error') {
          setError(data.message as string)
          setIsAnalyzing(false)
        }
      })

      pollRef.current = setInterval(() => {
        client.get(`/repo/${repoId}/analysis-status`).then(r => {
          setStatus(r.data)
          if (r.data.status === 'ready' && r.data.total_issues > 0 && issues.length === 0) {
            loadIssues()
          }
          if (r.data.status !== 'analyzing') {
            clearInterval(pollRef.current!)
            setIsAnalyzing(false)
          }
        })
      }, 2000)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to start analysis.')
      setIsAnalyzing(false)
    }
  }, [repoId])

  const loadStatus = useCallback(async () => {
    if (!repoId) return
    const r = await client.get(`/repo/${repoId}/analysis-status`)
    setStatus(r.data)
  }, [repoId])

  const loadIssues = useCallback(async () => {
    if (!repoId) return
    const params: Record<string, string> = { repo_id: repoId }
    if (filterSeverity) params.severity = filterSeverity
    if (filterCategory) params.category = filterCategory
    if (filterFile) params.file_path = filterFile
    const r = await client.get('/issues', { params })
    setIssues(r.data)
  }, [repoId, filterSeverity, filterCategory, filterFile])

  useEffect(() => {
    if (!isAnalyzing && issues.length > 0) loadIssues()
  }, [filterSeverity, filterCategory, filterFile])

  useEffect(() => {
    if (repoId) startAnalysis()
    return () => {
      wsRef.current?.close()
      Object.values(fixWsRefs.current).forEach(ws => ws.close())
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  // ── Fix approval ────────────────────────────────────────────────────────
  const handleApprove = useCallback(async (issue: Issue) => {
    try {
      // Generate plan if not already done
      if (!issue.fix_plan) {
        await client.post(`/issues/${issue.id}/plan`)
      }

      // Approve the fix
      const approveResp = await client.post(`/issues/${issue.id}/approve`)
      const { job_id } = approveResp.data

      // Initialize fix job state
      setFixJobs(prev => ({
        ...prev,
        [issue.id]: { job_id, issue_id: issue.id, status: 'pending', output_lines: [], diff: null, error: null },
      }))

      // Update issue status locally
      setIssues(prev => prev.map(i => i.id === issue.id ? { ...i, status: 'approved' } : i))

      // Subscribe to fix WS stream
      const ws = createJobSocket(job_id, (data) => {
        if (data.event === 'bob_output') {
          setFixJobs(prev => ({
            ...prev,
            [issue.id]: {
              ...prev[issue.id],
              status: 'running',
              output_lines: [...(prev[issue.id]?.output_lines ?? []), data.line as string],
            },
          }))
        } else if (data.event === 'fix_complete') {
          setFixJobs(prev => ({
            ...prev,
            [issue.id]: { ...prev[issue.id], status: 'succeeded', diff: data.diff as string },
          }))
          setIssues(prev => prev.map(i => i.id === issue.id ? { ...i, status: 'fixed' } : i))
          ws.close()
        } else if (data.event === 'fix_failed') {
          setFixJobs(prev => ({
            ...prev,
            [issue.id]: {
              ...prev[issue.id],
              status: 'failed',
              error: data.message as string,
            },
          }))
          ws.close()
        }
      })
      fixWsRefs.current[job_id] = ws

      // Execute the fix
      await client.post(`/fix/${job_id}/execute`)

    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to start fix.')
    }
  }, [])

  // ── Derived data ────────────────────────────────────────────────────────
  const uniqueFiles = [...new Set(issues.map(i => i.file_path).filter(Boolean))] as string[]
  const fixedCount = issues.filter(i => i.status === 'fixed').length

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav */}
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/')}
          className="text-gray-400 hover:text-gray-700 text-sm mr-1">← Back</button>
        <span className="text-xl font-bold text-gray-900">CodePilot</span>
        <span className="text-xl font-bold text-blue-600">AI</span>
        {repoInfo && (
          <span className="ml-2 text-sm text-gray-500 font-mono">{repoInfo.name}</span>
        )}
        <span className="ml-auto flex gap-2">
          {fixedCount > 0 && !isAnalyzing && (
            <button
              onClick={() => navigate(`/report/${repoId}`)}
              className="text-xs bg-green-600 hover:bg-green-700 text-white font-medium
                px-3 py-1.5 rounded-lg transition-colors"
            >
              📊 View Report
            </button>
          )}
          <span className="text-xs text-gray-400 bg-blue-50 border border-blue-200 rounded px-2 py-0.5 self-center">
            IBM Bob Shell
          </span>
        </span>
      </nav>

      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">
          Analysis Results
          {repoInfo && <span className="ml-2 text-gray-400 text-lg font-normal">— {repoInfo.name}</span>}
        </h1>

        {/* Progress */}
        {isAnalyzing && (
          <div className="bg-white border border-gray-200 rounded-xl p-5 mb-6">
            <div className="flex items-center gap-3 mb-4">
              <span className="h-5 w-5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
              <span className="text-sm font-medium text-blue-700">IBM Bob is analyzing your repository…</span>
            </div>
            <ProgressBar pct={progress.pct} message={progress.message} />
            {issues.length > 0 && (
              <p className="text-sm text-gray-500 mt-3">{issues.length} issues found so far…</p>
            )}
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6 text-sm text-red-700">
            {error}
            <button onClick={startAnalysis} className="ml-3 text-blue-600 hover:underline">Retry</button>
          </div>
        )}

        {/* Summary cards */}
        {(status || issues.length > 0) && !isAnalyzing && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            {[
              { label: 'Total Issues', value: String(status?.total_issues ?? issues.length) },
              { label: 'Critical / High', value: String((status?.severity_counts?.critical ?? 0) + (status?.severity_counts?.high ?? 0)) },
              { label: 'Fixed', value: String(fixedCount) },
              { label: 'Health Score', value: status?.health_score != null ? String(status.health_score) : '—' },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white border border-gray-200 rounded-xl p-4 text-center">
                <p className="text-2xl font-bold text-gray-900">{value}</p>
                <p className="text-xs text-gray-500 mt-1">{label}</p>
              </div>
            ))}
          </div>
        )}

        {/* Severity breakdown */}
        {!isAnalyzing && issues.length > 0 && (
          <div className="flex gap-3 flex-wrap mb-6">
            {(['critical', 'high', 'medium', 'low'] as const).map(sev => {
              const count = issues.filter(i => i.severity === sev).length
              if (count === 0) return null
              return (
                <button
                  key={sev}
                  onClick={() => setFilterSeverity(filterSeverity === sev ? '' : sev)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                    filterSeverity === sev ? SEVERITY_STYLES[sev] : 'bg-white border-gray-200 text-gray-600 hover:border-gray-400'
                  }`}
                >
                  {sev} ({count})
                </button>
              )
            })}
          </div>
        )}

        {/* Filter bar */}
        {!isAnalyzing && issues.length > 0 && (
          <div className="flex gap-3 mb-5 flex-wrap">
            <select
              value={filterCategory}
              onChange={e => setFilterCategory(e.target.value)}
              className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 bg-white"
            >
              <option value="">All Categories</option>
              {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <select
              value={filterFile}
              onChange={e => setFilterFile(e.target.value)}
              className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 bg-white font-mono"
            >
              <option value="">All Files</option>
              {uniqueFiles.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
            {(filterSeverity || filterCategory || filterFile) && (
              <button
                onClick={() => { setFilterSeverity(''); setFilterCategory(''); setFilterFile('') }}
                className="text-sm text-gray-500 hover:text-gray-700 underline"
              >
                Clear filters
              </button>
            )}
          </div>
        )}

        {/* Issue list */}
        {issues.length > 0 ? (
          <div className="space-y-3">
            {issues
              .filter(i =>
                (!filterSeverity || i.severity === filterSeverity) &&
                (!filterCategory || i.category === filterCategory) &&
                (!filterFile || i.file_path === filterFile)
              )
              .map(issue => (
                <IssueCard
                  key={issue.id}
                  issue={issue}
                  fixJob={fixJobs[issue.id]}
                  onSelect={setSelectedIssue}
                  onApprove={handleApprove}
                />
              ))}
          </div>
        ) : !isAnalyzing ? (
          <div className="text-center py-16 bg-white border border-gray-200 rounded-xl">
            <p className="text-4xl mb-3">🎉</p>
            <p className="text-lg font-semibold text-gray-800">No issues found!</p>
            <p className="text-sm text-gray-500 mt-1">This repository passed all checks.</p>
          </div>
        ) : null}
      </div>

      {/* Issue detail modal */}
      {selectedIssue && (
        <IssueDetailPanel
          issue={selectedIssue}
          onClose={() => setSelectedIssue(null)}
          onApprove={(i) => { handleApprove(i); setSelectedIssue(null) }}
        />
      )}
    </div>
  )
}
