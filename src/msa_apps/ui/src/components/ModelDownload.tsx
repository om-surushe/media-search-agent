import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { fetchSetupStatus, retrySetup, type SetupStatus, type ModelState, type ModelInfo } from '../api/setup'
import { useSetupWS } from '../hooks/useSetupWS'
import { SplashShell, ProgressBar, formatElapsed } from './splash'

/** First-run setup progress after the user explicitly starts setup. */

interface Props {
  /** Called when the models are ready (all done, or the user chose to continue with failures). */
  onReady: () => void
  /** The overall first-run start (ms); shared with StartupGate so the elapsed clock never resets. */
  startedAtMs: number
  /** Model list from StartupGate's `/api/setup/status` check — avoids a refetch and a flash. */
  initialModels: ModelInfo[]
}

export function ModelDownload({ onReady, startedAtMs, initialModels }: Props) {
  // Reuse the list StartupGate already fetched; only hit the network if it couldn't (empty list).
  const { data, isError } = useQuery<SetupStatus>({
    queryKey: ['setup/status'],
    queryFn: fetchSetupStatus,
    retry: 2,
    retryDelay: 1000,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    // Poll setup status as a backstop to /ws/setup, stopping once it reports ready (Codex P2). The
    // WS drives the live per-model checklist, but it can disconnect or never send `complete` while
    // the background downloader finishes — and in the normal path the seeded initialData + staleTime
    // would otherwise pin `data.ready` at false forever. Polling lets the authoritative `ready:true`
    // eventually surface and reveal the app regardless of WS health.
    refetchInterval: (query) => (query.state.data?.ready ? false : 3000),
    initialData: initialModels.length ? { ready: false, models: initialModels } : undefined,
  })
  const { models: wsModels, complete } = useSetupWS()
  const [continued, setContinued] = useState(false)

  const [elapsedMs, setElapsedMs] = useState(() => Math.max(0, Date.now() - startedAtMs))
  useEffect(() => {
    const id = setInterval(() => setElapsedMs(Math.max(0, Date.now() - startedAtMs)), 1000)
    return () => clearInterval(id)
  }, [startedAtMs])

  const models = data?.models ?? initialModels
  const rows = models.map((info) => {
    const live = wsModels?.[info.id]
    const status: ModelState = live?.status ?? (info.present ? 'done' : 'pending')
    return {
      ...info,
      status,
      error: live?.error ?? null,
      downloadedBytes: live?.downloaded_bytes ?? 0,
      totalBytes: live?.total_bytes ?? 0,
      filename: live?.filename ?? null,
    }
  })
  // Error state comes from the checklist rows AND the raw WS states. The second term matters in the
  // fallback path where StartupGate's /api/setup/status check failed → `initialModels` is empty →
  // `rows` is empty and can't reflect a failure; without it, a `complete` carrying model errors
  // would slip past the retry/continue UI and auto-reveal the app (Codex P2).
  const wsHasErrors = wsModels
    ? Object.entries(wsModels).some(([id, model]) => id !== 'captioning' && model.status === 'error')
    : false
  const hasErrors = rows.some((r) => r.status === 'error') || wsHasErrors
  // Reveal when EITHER /ws/setup reports `complete` OR the authoritative /api/setup/status says the
  // model files are already on disk (`ready: true`). The HTTP signal matters in the fallback path
  // (Codex P2): StartupGate got here because its first status check failed, but a later successful
  // refetch can confirm readiness — the app must not stay stuck just because /ws/setup closed and
  // never sent `complete`.
  const allDone = !hasErrors && (complete || data?.ready === true)

  // Fallback path (Codex P2): StartupGate reached here with empty `initialModels` because its
  // /api/setup/status check failed; if this component's own retried refetch ALSO fails we have no
  // model metadata to render. In the same backend-config failure /ws/setup typically closes without
  // ever sending `complete`, so without this the splash would hang forever on "Downloading AI models"
  // with no error or recourse. Surface the failure (with Retry + Continue) once the retries exhaust.
  const statusFailed = isError && models.length === 0 && !allDone
  const showFailureUI = (hasErrors && complete) || statusFailed

  // Reveal the app once every model is ready — or when the user accepts running with failures.
  useEffect(() => {
    if (allDone || continued) onReady()
  }, [allDone, continued, onReady])

  const totalSize = models.reduce((sum, model) => sum + model.size_mb, 0) || 1
  const completedSize = rows.reduce((sum, model) => {
    if (model.status === 'done') return sum + model.size_mb
    if (model.status === 'downloading' && model.totalBytes > 0) {
      return sum + model.size_mb * Math.min(model.downloadedBytes / model.totalBytes, 1)
    }
    return sum
  }, 0)
  const setupProgress = Math.min(completedSize / totalSize, 1)
  const pct = setupProgress * 100
  const remainingMs = setupProgress > 0.01
    ? elapsedMs * (1 - setupProgress) / setupProgress
    : null

  // Retry: actually restart the download on the backend (start_if_needed) BEFORE reloading — a plain
  // reload only re-subscribes to the manager's held complete/error state. The reload then gives a
  // fresh /ws/setup that streams the restarted run. Best-effort: reload even if the POST fails, since
  // the fresh mount re-checks /api/setup/status regardless.
  const onRetry = async () => {
    try {
      await retrySetup()
    } catch {
      /* best effort — the reload re-checks status */
    }
    window.location.reload()
  }

  return (
    <SplashShell icon={<Download size={22} className="shrink-0 text-sky-400" aria-hidden />}>
      <p className="text-base font-medium text-slate-100">Setting up Media Search Agent</p>
      <p className="mt-1 text-sm text-slate-400">Please keep the app open until setup finishes.</p>

      <ProgressBar
        pct={pct}
        rightLabel={remainingMs === null ? 'Estimating time…' : `About ${formatElapsed(remainingMs)} remaining`}
      />

      {showFailureUI ? (
        <div className="mt-5 grid gap-2">
          <p className="text-sm text-red-300">Setup couldn’t finish. Check your connection and try again.</p>
          <button
            type="button"
            onClick={onRetry}
            className="w-full rounded-xl border border-red-500/40 bg-red-900/20 px-4 py-2.5 text-sm font-medium text-red-300 hover:bg-red-900/30"
          >
            Try setup again
          </button>
          <button
            type="button"
            onClick={() => setContinued(true)}
            className="w-full rounded-xl border border-slate-600/50 bg-slate-800/40 px-4 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-800/70"
          >
            Continue anyway
          </button>
          <p className="text-center text-xs text-slate-500">
            Some features may not work until setup finishes.
          </p>
        </div>
      ) : (
        <p className="mt-5 text-xs text-slate-600">
          This one-time setup lets the app work offline afterward.
        </p>
      )}
    </SplashShell>
  )
}
