import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadCommercialModel, fetchCommercialModelCatalog, type CommercialModel } from '../api/setup'

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GiB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function progressLabel(model: CommercialModel): string {
  const state = model.state
  if (state.status === 'verifying') return 'Checking downloaded weights…'
  if (state.status === 'downloading') {
    const filename = state.filename ? ` · ${state.filename}` : ''
    const totalBytes = state.total_bytes ?? 0
    if (totalBytes > 0) {
      return `${formatBytes(state.downloaded_bytes ?? 0)} of ${formatBytes(totalBytes)}${filename}`
    }
    return `Downloading${filename}`
  }
  if (state.status === 'done' || model.installed) return 'Installed and verified'
  if (state.status === 'error') return state.error ?? 'Download failed'
  return 'Not installed'
}

export function CommercialModelCatalog() {
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const query = useQuery({
    queryKey: ['commercial-model-catalog'],
    queryFn: fetchCommercialModelCatalog,
    refetchInterval: (current) => current.state.data?.models?.some(
      model => model.state.status === 'downloading' || model.state.status === 'verifying',
    ) ? 1000 : false,
  })

  async function install(model: CommercialModel) {
    const proceed = window.confirm(
      `${model.label} is not commercially cleared. Download it for local evaluation only?\n\n` +
      `Source: ${model.source}\nTarget: ${model.path}\nSize: ${formatBytes(model.size_bytes)}`,
    )
    if (!proceed) return
    setBusyId(model.id)
    setActionError('')
    try {
      await downloadCommercialModel(model.id)
      await query.refetch()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusyId(null)
    }
  }

  if (query.isPending) return <p className="text-sm text-zinc-500">Loading model catalog…</p>
  if (query.isError) return <p role="alert" className="text-sm text-red-600">Could not load model catalog: {String(query.error)}</p>
  const catalog = query.data
  if (!catalog || !Array.isArray(catalog.models) || !catalog.hardware) {
    return <p role="alert" className="text-sm text-red-600">Model catalog response is invalid.</p>
  }

  return <section className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
    <div>
      <h2 className="font-medium">Local model catalog</h2>
      <p className="mt-1 text-sm text-zinc-500">
        Models download on demand to the app-managed paths below. Hardware recommendations are advisory;
        they do not change the active index model. Upstream license claims are not legal clearance.
      </p>
      <p className="mt-2 text-xs text-zinc-500">
        This machine: {catalog.hardware.os} · {catalog.hardware.architecture} · {catalog.hardware.ram_gb ?? 'unknown'} GB RAM · {catalog.hardware.accelerator}
      </p>
    </div>

    {actionError && <p role="alert" className="text-sm text-red-600">{actionError}</p>}

    <ul className="space-y-3">
      {catalog.models.map(model => {
        const state = model.state
        const inProgress = state.status === 'downloading' || state.status === 'verifying'
        const transferPct = state.total_bytes
          ? Math.min(100, Math.floor(((state.downloaded_bytes ?? 0) / state.total_bytes) * 100))
          : undefined
        return <li key={model.id} className="rounded border border-zinc-200 p-3 dark:border-zinc-700">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium">{model.label}</h3>
              <p className="text-xs text-zinc-500">{model.task} · {formatBytes(model.size_bytes)} · {model.min_ram_gb} GB RAM target</p>
            </div>
            <span className="text-xs text-amber-700 dark:text-amber-400">
              {model.clearance === 'conditional' ? 'Conditional — review required' : 'Not commercially cleared'}
            </span>
          </div>

          <p className="mt-2 text-xs text-zinc-500">Upstream license claim: {model.license_claim}</p>
          <a className="text-xs text-blue-600 underline" href={model.license_evidence} target="_blank" rel="noreferrer">
            Review upstream evidence
          </a>
          <p className="mt-1 text-xs text-zinc-500">Adapter: {model.adapter_status}</p>
          {model.recommended_for_task && model.hardware_fit && (
            <p className="mt-1 text-xs text-emerald-700 dark:text-emerald-400">Smallest hardware-fit candidate for this task (advisory)</p>
          )}
          <p className="mt-1 break-all font-mono text-[11px] text-zinc-500">{model.path}</p>
          <p className={`mt-2 text-xs ${state.status === 'error' ? 'text-red-600' : 'text-zinc-500'}`}>
            {progressLabel(model)}
          </p>
          {inProgress && (
            <progress
              className="mt-1 h-2 w-full accent-blue-600"
              max={state.total_bytes || undefined}
              value={state.total_bytes ? state.downloaded_bytes : undefined}
              aria-label={`${model.label} download progress`}
              aria-valuetext={transferPct === undefined ? progressLabel(model) : `${transferPct}%`}
            />
          )}
          {model.access_note && <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">{model.access_note}</p>}
          {model.downloadable && !model.installed && state.status !== 'done' && (
            <button
              type="button"
              disabled={Boolean(busyId) || inProgress}
              onClick={() => void install(model)}
              className="mt-2 rounded bg-blue-600 px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              {busyId === model.id ? 'Starting…' : state.status === 'error' ? 'Retry evaluation download' : 'Download for evaluation'}
            </button>
          )}
        </li>
      })}
    </ul>
  </section>
}
