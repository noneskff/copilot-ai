import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import client from '../api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Report {
  repo_id: string
  repo_name: string
  generated_at: string
  health: {
    before: number | null
    after: number
    improvement: number | null
  }
  issues: {
    total: number
    fixed: number
    remaining: number
    fix_rate_pct: number
    severity_breakdown: Record<string, { total: number; fixed: number }>
    category_breakdown: Record<string, number>
  }
  fixes: {
    total_jobs: number
    succeeded: number
    failed: number
    diff_preview: string | null
  }
  tests: {
    passed?: boolean
    tests_total?: number
    tests_passed?: number
    tests_failed?: number
    ran_at?: string
  }
  fixed_issue_list: IssueRef[]
  open_issue_list: IssueRef[]
}

interface IssueRef {
  id: string
  title: string
  severity: string
  category: string
  file_path: string | null
  line_number: number | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-800',
  high:     'bg-orange-100 text-orange-800',
  medium:   'bg-yellow-100 text-yellow-800',
  low:      'bg-blue-100 text-blue-800',
}

function SeverityBadge({ severity }: { severity: string }) {
  const cls = SEVERITY_STYLES[severity] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase ${cls}`}>
      {severity}
    </span>
  )
}

function ScoreGauge({ score, label }: { score: number | null; label: string }) {
  if (score == null) return (
    <div className="text-center">
      <p className="text-3xl font-bold text-gray-400">—</p>
      <p className="text-xs text-gray-400 mt-1">{label}</p>
    </div>
  )
  const color = score >= 80 ? 'text-green-600' : score >= 60 ? 'text-yellow-600' : 'text-red-600'
  const ring  = score >= 80 ? 'border-green-400' : score >= 60 ? 'border-yellow-400' : 'border-red-400'
  return (
    <div className="text-center">
      <div className={`mx-auto flex items-center justify-center w-20 h-20 rounded-full border-4 ${ring}`}>
        <span className={`text-2xl font-bold ${color}`}>{score}</span>
      </div>
      <p className="text-xs text-gray-500 mt-2">{label}</p>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ReportPage() {
  const { repoId } = useParams<{ repoId: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadReport = useCallback(async () => {
    if (!repoId) return
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get(`/repo/${repoId}/report`)
      setReport(resp.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to load report.')
    } finally {
      setLoading(false)
    }
  }, [repoId])

  useEffect(() => { loadReport() }, [loadReport])

  const handleRunTests = async () => {
    if (!repoId) return
    try {
      await client.post(`/repo/${repoId}/run-tests`)
      // Reload report after a short delay to pick up new test run
      setTimeout(loadReport, 3000)
    } catch {
      // ignore
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <span className="h-8 w-8 rounded-full border-4 border-blue-500 border-t-transparent animate-spin block mx-auto" />
          <p className="mt-3 text-gray-600">Generating report…</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-xl border border-red-200 p-8 max-w-md text-center">
          <p className="text-red-600 font-medium">{error}</p>
          <button onClick={() => navigate(-1)} className="mt-4 text-blue-600 hover:underline text-sm">← Go back</button>
        </div>
      </div>
    )
  }

  if (!report) return null

  const improvement = report.health.improvement
  const improvementLabel = improvement == null ? null
    : improvement > 0 ? `+${improvement} pts`
    : improvement === 0 ? 'No change'
    : `${improvement} pts`

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Nav */}
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate(`/analysis/${repoId}`)}
          className="text-gray-400 hover:text-gray-700 text-sm mr-1">← Back to Analysis</button>
        <span className="text-xl font-bold text-gray-900">CodePilot</span>
        <span className="text-xl font-bold text-blue-600">AI</span>
        <span className="ml-2 text-sm text-gray-500 font-mono">{report.repo_name}</span>
        <span className="ml-auto text-xs text-gray-400 bg-blue-50 border border-blue-200 rounded px-2 py-0.5">
          IBM Bob Shell
        </span>
      </nav>

      <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Before / After Report</h1>
            <p className="text-sm text-gray-400 mt-1">
              Generated {new Date(report.generated_at).toLocaleString()}
            </p>
          </div>
          <button
            onClick={loadReport}
            className="text-sm text-blue-600 hover:underline"
          >
            ↻ Refresh
          </button>
        </div>

        {/* Health score comparison */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-6">Health Score</h2>
          <div className="flex items-center justify-around">
            <ScoreGauge score={report.health.before} label="Before" />
            <div className="text-center">
              {improvementLabel && (
                <span className={`text-lg font-bold ${
                  (improvement ?? 0) > 0 ? 'text-green-600' :
                  (improvement ?? 0) < 0 ? 'text-red-600' : 'text-gray-500'
                }`}>
                  {improvementLabel}
                </span>
              )}
              <p className="text-xs text-gray-400 mt-1">improvement</p>
              <div className="my-3 text-2xl text-gray-300">→</div>
            </div>
            <ScoreGauge score={report.health.after} label="After" />
          </div>
        </div>

        {/* Issue summary grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Total Issues', value: report.issues.total },
            { label: 'Fixed', value: report.issues.fixed },
            { label: 'Remaining', value: report.issues.remaining },
            { label: 'Fix Rate', value: `${report.issues.fix_rate_pct}%` },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white border border-gray-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-gray-900">{value}</p>
              <p className="text-xs text-gray-500 mt-1">{label}</p>
            </div>
          ))}
        </div>

        {/* Severity breakdown */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Severity Breakdown</h2>
          <div className="space-y-3">
            {(['critical', 'high', 'medium', 'low'] as const).map(sev => {
              const bd = report.issues.severity_breakdown[sev]
              if (!bd || bd.total === 0) return null
              const pct = Math.round((bd.fixed / bd.total) * 100)
              return (
                <div key={sev} className="flex items-center gap-3">
                  <SeverityBadge severity={sev} />
                  <div className="flex-1">
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>{bd.fixed} / {bd.total} fixed</span>
                      <span>{pct}%</span>
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${pct === 100 ? 'bg-green-500' : 'bg-blue-500'}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Test results */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-gray-800">Test Suite</h2>
            <button
              onClick={handleRunTests}
              className="text-sm bg-blue-600 hover:bg-blue-700 text-white font-medium
                px-3 py-1.5 rounded-lg transition-colors"
            >
              ▶ Run Tests
            </button>
          </div>
          {report.tests && Object.keys(report.tests).length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Result', value: report.tests.passed ? '✅ Pass' : '❌ Fail' },
                { label: 'Total', value: String(report.tests.tests_total ?? '—') },
                { label: 'Passed', value: String(report.tests.tests_passed ?? '—') },
                { label: 'Failed', value: String(report.tests.tests_failed ?? '—') },
              ].map(({ label, value }) => (
                <div key={label} className="bg-gray-50 rounded-lg p-3 text-center">
                  <p className="text-sm font-semibold text-gray-800">{value}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{label}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400">No test runs yet. Click "Run Tests" to execute the test suite.</p>
          )}
        </div>

        {/* Fix jobs summary */}
        {report.fixes.total_jobs > 0 && (
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-base font-semibold text-gray-800 mb-4">Fix Jobs</h2>
            <div className="grid grid-cols-3 gap-3 mb-4">
              {[
                { label: 'Total', value: report.fixes.total_jobs },
                { label: 'Succeeded', value: report.fixes.succeeded },
                { label: 'Failed', value: report.fixes.failed },
              ].map(({ label, value }) => (
                <div key={label} className="bg-gray-50 rounded-lg p-3 text-center">
                  <p className="text-xl font-bold text-gray-800">{value}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{label}</p>
                </div>
              ))}
            </div>
            {report.fixes.diff_preview && (
              <details>
                <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700">
                  View combined diff
                </summary>
                <pre className="mt-2 text-xs bg-gray-900 text-green-300 rounded p-3
                  overflow-x-auto font-mono max-h-64">
                  {report.fixes.diff_preview}
                </pre>
              </details>
            )}
          </div>
        )}

        {/* Fixed issues */}
        {report.fixed_issue_list.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-base font-semibold text-gray-800 mb-4">
              ✅ Fixed Issues ({report.fixed_issue_list.length})
            </h2>
            <div className="space-y-2">
              {report.fixed_issue_list.map(issue => (
                <div key={issue.id}
                  className="flex items-center gap-3 p-3 bg-green-50 border border-green-100 rounded-lg">
                  <SeverityBadge severity={issue.severity} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{issue.title}</p>
                    {issue.file_path && (
                      <p className="text-xs text-gray-400 font-mono">
                        {issue.file_path}{issue.line_number ? `:${issue.line_number}` : ''}
                      </p>
                    )}
                  </div>
                  <span className="text-green-600 text-sm">✓</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Remaining issues */}
        {report.open_issue_list.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-base font-semibold text-gray-800 mb-4">
              ⚠️ Remaining Issues ({report.open_issue_list.length})
            </h2>
            <div className="space-y-2">
              {report.open_issue_list.map(issue => (
                <div key={issue.id}
                  className="flex items-center gap-3 p-3 bg-gray-50 border border-gray-100 rounded-lg">
                  <SeverityBadge severity={issue.severity} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{issue.title}</p>
                    {issue.file_path && (
                      <p className="text-xs text-gray-400 font-mono">
                        {issue.file_path}{issue.line_number ? `:${issue.line_number}` : ''}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => navigate(`/analysis/${repoId}`)}
                    className="text-xs text-blue-600 hover:underline whitespace-nowrap"
                  >
                    Fix →
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
