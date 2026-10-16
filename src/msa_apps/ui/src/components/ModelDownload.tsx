import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { fetchSetupJob, retrySetup } from '../api/setup'
import { ProgressBar, SplashShell } from './splash'

interface ModelDownloadProps {
  onReady: () => void
}

function formatEta(seconds: number): string {
  if (seconds < 60) return 'Less than a minute remaining'
  const minutes = Math.ceil(seconds / 60)
  if (minutes < 60) return `About ${minutes} minutes remaining`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return `About ${hours}h${remainder ? ` ${remainder}m` : ''} remaining`
}

export function ModelDownload({ onReady }: ModelDownloadProps) {
  const [retrying, setRetrying] = useState(false)
  const { data, isError, refetch } = useQuery({
    queryKey: ['setup-job'],
    queryFn: fetchSetupJob,
    refetchInterval: (query) => {
      const status = query.state.data?.job?.status
      return status === 'completed' || status === 'failed' ? false : 1000
    },
    staleTime: 0,
  })

  const job = data?.job

  useEffect(() => {
    if (data?.ready && job?.status === 'completed') onReady()
  }, [data?.ready, job?.status, onReady])

  const retry = async () => {
    setRetrying(true)
    try {
      await retrySetup()
      await refetch()
    } finally {
      setRetrying(false)
    }
  }

  const failed = isError || job?.status === 'failed'
  const pct = job?.progress_percent ?? 0
  const eta = job?.eta_seconds

  return (
    <SplashShell icon={<Download size={22} className="shrink-0 text-sky-400" aria-hidden />}>
      <p className="text-base font-medium text-slate-100">Setting up Media Search Agent</p>
      <p className="mt-1 text-sm text-slate-400">Please keep the app open until setup finishes.</p>

      <ProgressBar
        pct={pct}
        rightLabel={eta == null ? 'Calculating time remaining…' : formatEta(eta)}
      />

      {job && (
        <p className="mt-2 text-xs text-slate-500">
          {(job.downloaded_bytes / 1024 ** 2).toFixed(0)} MB of {(job.total_bytes / 1024 ** 3).toFixed(1)} GB
        </p>
      )}

      {failed ? (
        <div className="mt-5 grid gap-2">
          <p className="text-sm text-red-300">Setup paused because the download was interrupted.</p>
          <button
            type="button"
            onClick={() => void retry()}
            disabled={retrying}
            className="w-full rounded-xl border border-red-500/40 bg-red-900/20 px-4 py-2.5 text-sm font-medium text-red-300 hover:bg-red-900/30 disabled:opacity-60"
          >
            {retrying ? 'Resuming…' : 'Resume setup'}
          </button>
        </div>
      ) : (
        <p className="mt-5 text-xs text-slate-600">
          You can close the app. Setup will resume from this job next time.
        </p>
      )}
    </SplashShell>
  )
}
