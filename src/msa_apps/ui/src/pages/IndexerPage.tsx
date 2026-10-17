import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Play, Square, ChevronDown, ChevronUp, Image, Film, User, Users, Maximize2, Minimize2 } from 'lucide-react'
import {
  startIndexer, stopIndexer, getIndexerStatus, getIndexStats, getSources, getModelConfig,
  getIndexerSettings, saveIndexerSettings,
} from '../api/indexer'
import type { IndexerSettingsUpdate, ProcessingOrder } from '../api/indexer'
import { useIndexerWS } from '../hooks/useIndexerStatus'
import { MediaSourcesPanel } from '../components/MediaSourcesPanel'
import { cn } from '../lib/utils'

function formatElapsed(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m < 60) return `${m}m ${sec}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

function formatDuration(s: number | null | undefined): string {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)}s`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  if (m < 60) return `${m}m ${sec}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

function formatCount(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString()
}

function formatRate(s: number | null | undefined): string {
  if (s == null) return '—'
  return `${formatDuration(s)}/min`
}

function statusLabel(status: string): string {
  if (status === 'running') return 'Indexing'
  if (status === 'complete') return 'Completed'
  if (status === 'error') return 'Failed'
  if (status === 'stopped') return 'Cancelled'
  return 'Idle'
}

function activityLabel(phase: string | undefined): string {
  switch (phase) {
    case 'counting': return 'Scanning your media folders'
    case 'analyzing': return 'Checking which files need indexing'
    case 'processing': return 'Indexing photos and videos'
    case 'exporting': return 'Updating the searchable library'
    case 'export_blocked': return 'Waiting to update the searchable library'
    case 'captioning': return 'Adding photo captions'
    case 'captioning_error': return 'Photo captioning reported errors'
    case 'scene_captioning': return 'Adding video scene captions'
    case 'scene_captioning_error': return 'Video captioning reported errors'
    case 'complete': return 'Preparing the searchable library'
    case 'commit_stats': return 'Saving the run summary'
    default: return 'Processing your media files'
  }
}

function parseActivityLine(line: string | null): { timestamp: string | null; fileName: string | null; message: string } | null {
  if (!line) return null

  const timestampMatch = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})/)
  const timestamp = timestampMatch?.[1] ?? null

  const messageIdx = line.indexOf(' - ')
  const message = messageIdx >= 0 ? line.slice(messageIdx + 3).trim() : line.trim()

  const pathMatch = line.match(/'path':\s*'([^']+)'/)
  const rawPath = pathMatch?.[1] ?? null
  const fileName = rawPath
    ? rawPath.split(/[/\\]/).filter(Boolean).pop() ?? rawPath
    : null

  return { timestamp, fileName, message }
}



const STAT_ITEMS: { key: 'images' | 'videos' | 'faces' | 'people'; label: string; Icon: React.ElementType }[] = [
  { key: 'images',  label: 'Photos',  Icon: Image  },
  { key: 'videos',  label: 'Videos',  Icon: Film   },
  { key: 'faces',   label: 'Faces',   Icon: User   },
  { key: 'people',  label: 'People',  Icon: Users  },
]

type IndexerOptions = { processingOrder: ProcessingOrder }

const DEFAULT_INDEXER_OPTIONS: IndexerOptions = { processingOrder: 'default' }

function toSettingsUpdate(options: IndexerOptions): IndexerSettingsUpdate {
  return { processing_order: options.processingOrder }
}

export function IndexerPage() {
  const wsUpdate = useIndexerWS()
  const logLines   = wsUpdate?.log ?? []
  const { data: apiStatus } = useQuery({
    queryKey: ['indexer-status'],
    queryFn: getIndexerStatus,
    retry: false,
  })
  const statusInfo = wsUpdate?.status ?? apiStatus ?? null

  const [logOpen, setLogOpen] = useState(false)
  const [logExpanded, setLogExpanded] = useState(false)
  const [options, setOptions] = useState<IndexerOptions>(DEFAULT_INDEXER_OPTIONS)
  const optionsRef = useRef(options)
  const settingsLoadedRef = useRef(false)
  const logRef = useRef<HTMLDivElement>(null)
  const prevStatusRef = useRef<string | null>(null)

  const { data: indexerSettings, isSuccess: settingsLoaded, isError: settingsLoadError } = useQuery({
    queryKey: ['indexer-settings'],
    queryFn: getIndexerSettings,
    retry: false,
  })
  const { data: stats, refetch: refetchStats } = useQuery({
    queryKey: ['indexer-stats'],
    queryFn: getIndexStats,
    refetchInterval: 60_000,
  })
  const { data: sources = [] } = useQuery({
    queryKey: ['sources'],
    queryFn: getSources,
  })
  const { data: modelConfig, isLoading: modelConfigLoading, isError: modelConfigError } = useQuery({
    queryKey: ['model-config'],
    queryFn: getModelConfig,
  })

  const saveSettingsMutation = useMutation({ mutationFn: saveIndexerSettings })
  const startMutation = useMutation({
    mutationFn: (processingOrder: ProcessingOrder) => startIndexer(processingOrder),
  })
  const stopMutation  = useMutation({ mutationFn: stopIndexer  })

  useEffect(() => {
    if (indexerSettings && !settingsLoadedRef.current) {
      const loadedOptions: IndexerOptions = { processingOrder: indexerSettings.processing_order }
      optionsRef.current = loadedOptions
      setOptions(loadedOptions)
      settingsLoadedRef.current = true
    } else if (settingsLoadError) {
      settingsLoadedRef.current = true
    }
  }, [indexerSettings, settingsLoadError])

  const updateOptions = (changes: Partial<IndexerOptions>) => {
    const next = { ...optionsRef.current, ...changes }
    optionsRef.current = next
    setOptions(next)
    if (settingsLoaded || settingsLoadError) saveSettingsMutation.mutate(toSettingsUpdate(next))
  }

  // Refetch stats and reset start mutation when indexer transitions running → terminal
  useEffect(() => {
    const prev = prevStatusRef.current
    const curr = statusInfo?.status ?? null
    if (prev === 'running' && curr !== 'running') {
      if (curr === 'complete' || curr === 'stopped') refetchStats()
      startMutation.reset()
    }
    prevStatusRef.current = curr
  }, [statusInfo?.status, refetchStats, startMutation.reset])

  // Auto-scroll log to bottom when new lines arrive
  useEffect(() => {
    if (logOpen && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logLines, logOpen])

  const status    = statusInfo?.status ?? 'idle'
  const isRunning = status === 'running'
  const readOnlyMode = statusInfo?.read_only_mode ?? apiStatus?.read_only_mode ?? false
  const settingsReady = settingsLoaded || settingsLoadError
  const imageCaptionCapability = indexerSettings?.capabilities.image_captions
  const videoCaptionCapability = indexerSettings?.capabilities.video_scene_captions
  const captionsRequested = Boolean(modelConfig?.editable?.image_captions_enabled || modelConfig?.editable?.video_scene_captions_enabled)
  const runOrder = statusInfo?.summary?.processing_order

  useEffect(() => {
    if (isRunning && runOrder) {
      const next = { ...optionsRef.current, processingOrder: runOrder }
      optionsRef.current = next
      setOptions(next)
    }
  }, [isRunning, runOrder])
  const hasSources = sources.length > 0
  const elapsed   = statusInfo?.elapsed_seconds ?? null
  const filteredLines = logLines.filter(l => l.trim())
  const lastLine = filteredLines.length > 0 ? filteredLines[filteredLines.length - 1] : null
  const activityLine = parseActivityLine(lastLine)
  const summary = statusInfo?.summary ?? null
  const eta = summary?.estimated_remaining_seconds ?? null
  const currentActivity = isRunning ? activityLabel(summary?.phase) : null
  const totalFiles = summary?.total_found
  const filesWalked = summary?.files_walked
  const hasCaptionFailures = summary?.captioning != null || summary?.video_scene_captioning != null
  const captionFailures = (summary?.captioning?.failed ?? 0) + (summary?.video_scene_captioning?.failed ?? 0)
  const showSummaryGrid = (isRunning || status === 'complete') && summary && (
    summary.total_found != null ||
    summary.already_indexed != null ||
    summary.skipped != null ||
    summary.images_to_process != null ||
    summary.videos_to_process != null ||
    summary.processed_images != null ||
    summary.processed_videos != null
  )

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Indexer</h1>
      {readOnlyMode && (
        <div role="status" className="rounded-lg bg-amber-100 dark:bg-amber-950 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
          Indexing and source changes are disabled in this Search/Browse read-only session.
        </div>
      )}

      <section aria-label="Indexing status" aria-live="polite" className="rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 p-4 space-y-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={cn(
            'rounded-full px-2.5 py-1 text-sm font-semibold',
            status === 'running' && 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300',
            status === 'complete' && 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300',
            status === 'error' && 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300',
            status === 'stopped' && 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
            status === 'idle' && 'bg-zinc-100 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200',
          )}>{statusLabel(status)}</span>
          {elapsed != null && <span className="text-xs text-zinc-500 dark:text-zinc-400">{isRunning ? `${formatElapsed(elapsed)} elapsed` : `Finished in ${formatElapsed(elapsed)}`}</span>}
        </div>
        {isRunning && <p className="text-sm text-zinc-700 dark:text-zinc-200">
          <span className="font-medium">Currently:</span> {currentActivity}
          {activityLine?.fileName && <span className="ml-1 text-zinc-500">· {activityLine.fileName}</span>}
        </p>}
        {totalFiles != null && filesWalked != null && totalFiles > 0 && (
          <div className="space-y-1">
            <div className="text-sm tabular-nums text-zinc-700 dark:text-zinc-200">
              {formatCount(filesWalked)} of {formatCount(totalFiles)} files checked
            </div>
            <progress aria-label="Files checked" value={filesWalked} max={totalFiles} className="h-2 w-full accent-indigo-600" />
          </div>
        )}
        {isRunning && totalFiles != null && filesWalked == null && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{formatCount(totalFiles)} media files found</p>
        )}
        {isRunning && eta != null && <p className="text-xs text-zinc-500 dark:text-zinc-400">Estimated remaining time: about {formatDuration(eta)}</p>}
        {status === 'complete' && summary && (
          <p className="text-sm text-zinc-700 dark:text-zinc-200">
            {summary.needs_processing != null ? `${formatCount(summary.needs_processing)} files processed` : 'Indexing finished'}
            {summary.already_indexed != null && ` · ${formatCount(summary.already_indexed)} already up to date`}
          </p>
        )}
        {status === 'error' && <p className="text-sm text-red-700 dark:text-red-300">
          Indexing failed{statusInfo?.return_code != null ? ` (exit code ${statusInfo.return_code})` : ''}. Open the log below for details.
        </p>}
        {status === 'stopped' && <p className="text-sm text-amber-700 dark:text-amber-300">The indexing run was cancelled.</p>}
        {hasCaptionFailures && <p className="text-xs text-zinc-600 dark:text-zinc-300">AI caption failures: {formatCount(captionFailures)}</p>}
      </section>

      {/* Stats bar */}
      <div className="space-y-1.5">
        <div className="grid grid-cols-4 gap-3">
          {STAT_ITEMS.map(({ key, label, Icon }) => (
            <div key={key} className="bg-slate-100 dark:bg-zinc-800 rounded-lg p-3 flex flex-col gap-1">
              <div className="flex items-center gap-1.5 text-zinc-500 dark:text-zinc-400 text-xs">
                <Icon size={12} />
                {label}
              </div>
              <div className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                {stats?.[key] != null ? (stats[key] as number).toLocaleString() : '—'}
              </div>
              {key === 'videos' && stats?.total_video_duration != null && stats.total_video_duration > 0 && (
                <div className="text-xs text-zinc-500 dark:text-zinc-400 tabular-nums">
                  {formatDuration(stats.total_video_duration)}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="text-xs text-zinc-400 dark:text-zinc-500 text-right">
          {stats?.last_indexed_at
            ? `Last indexed: ${new Date(stats.last_indexed_at + 'Z').toLocaleString()}`
            : !isRunning ? 'Not yet indexed' : null}
        </div>
      </div>

      {!readOnlyMode && <>
      <MediaSourcesPanel />

      {/* Control card */}
      <div className="bg-slate-100 dark:bg-zinc-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300">
            Processing order
            <select
              aria-label="Processing order"
              value={options.processingOrder}
              disabled={isRunning || startMutation.isPending || !settingsReady}
              onChange={event => updateOptions({ processingOrder: event.target.value as ProcessingOrder })}
              className="rounded border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-900 px-2 py-1 text-sm"
            >
              <option value="default">Default</option>
              <option value="fastest">Fastest first</option>
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
            </select>
          </label>

          {/* Action button */}
          {isRunning ? (
            <button
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white text-sm rounded-md transition-colors disabled:opacity-50"
            >
              <Square size={14} />
              Stop
            </button>
          ) : (
            <button
              onClick={() => startMutation.mutate(options.processingOrder)}
              disabled={!hasSources || !settingsReady || modelConfigLoading || modelConfigError || startMutation.isPending || (startMutation.isSuccess && !isRunning)}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-md transition-colors disabled:opacity-50"
            >
              <Play size={14} />
              {status === 'idle' ? 'Run Indexer' : 'Run Again'}
            </button>
          )}
        </div>

        <div className="text-xs text-zinc-500 dark:text-zinc-400">
          Extraction options are configured in Settings and used for future runs.
        </div>
        {settingsReady && captionsRequested && (!imageCaptionCapability?.available || !videoCaptionCapability?.available) && (
          <div role="status" className="text-xs text-amber-700 dark:text-amber-300">
            Caption processing is not ready yet. Complete setup before starting an indexing run.
          </div>
        )}
        {settingsLoadError && (
          <div role="alert" className="text-xs text-amber-700 dark:text-amber-300">
            Could not load saved Indexer options; defaults are in use.
          </div>
        )}
        {saveSettingsMutation.isError && (
          <div role="alert" className="text-xs text-red-500 dark:text-red-400">
            Could not save processing order.
          </div>
        )}
        {modelConfigError && (
          <div role="alert" className="text-xs text-red-500 dark:text-red-400">
            Could not load extraction settings.
          </div>
        )}

        {options.processingOrder === 'fastest' && (
          <div className="text-xs text-zinc-500 dark:text-zinc-400">
            Fastest first is a heuristic: photos before videos, then smaller files first.
          </div>
        )}
        {(options.processingOrder === 'newest' || options.processingOrder === 'oldest') && (
          <div className="text-xs text-zinc-500 dark:text-zinc-400">
            Chronological order uses filesystem modification time.
          </div>
        )}

        {!hasSources && !isRunning && (
          <div className="text-xs text-amber-600 dark:text-amber-400 bg-white dark:bg-zinc-900 px-3 py-2 rounded">
            Setup required. Add at least one media source above to enable indexing.
          </div>
        )}

        {showSummaryGrid && summary && (
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-white dark:bg-zinc-900 rounded-lg p-3">
              <div className="text-xs text-zinc-500 dark:text-zinc-400">Media found</div>
              <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatCount(summary.total_found)}
              </div>
            </div>
            <div className="bg-white dark:bg-zinc-900 rounded-lg p-3">
              <div className="text-xs text-zinc-500 dark:text-zinc-400">
                Already up to date
              </div>
              <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatCount(summary.already_indexed ?? summary.skipped)}
              </div>
            </div>
            <div className="bg-white dark:bg-zinc-900 rounded-lg p-3">
              <div className="text-xs text-zinc-500 dark:text-zinc-400">
                {status === 'complete'
                  ? 'Photos processed'
                  : summary.already_indexed != null
                    ? 'Photos to process'
                    : 'Photos found'}
              </div>
              <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatCount(summary.images_to_process ?? summary.processed_images)}
              </div>
            </div>
            <div className="bg-white dark:bg-zinc-900 rounded-lg p-3">
              <div className="text-xs text-zinc-500 dark:text-zinc-400">
                {status === 'complete'
                  ? 'Videos processed'
                  : summary.already_indexed != null
                    ? 'Videos to process'
                    : 'Videos found'}
              </div>
              <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatCount(summary.videos_to_process ?? summary.processed_videos)}
              </div>
            </div>
          </div>
        )}

        {summary?.video_scene_captioning && (
          <section aria-live="polite" className="bg-white dark:bg-zinc-900 rounded-lg p-3 space-y-2">
            <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">AI Video Scene Captions</div>
            {isRunning && summary.video_scene_captioning.status === 'running' && summary.video_scene_captioning.current != null && (
              <div className="text-xs text-zinc-500 dark:text-zinc-400">
                Captioning scene {summary.video_scene_captioning.current} of {formatCount(summary.video_scene_captioning.total)}…
              </div>
            )}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <div className="text-zinc-500 dark:text-zinc-400">Generated</div>
              <div className="text-right tabular-nums">{formatCount(summary.video_scene_captioning.generated)}</div>
              <div className="text-zinc-500 dark:text-zinc-400">Skipped (already complete)</div>
              <div className="text-right tabular-nums">{formatCount(summary.video_scene_captioning.skipped)}</div>
              <div className="text-zinc-500 dark:text-zinc-400">Failed</div>
              <div className="text-right tabular-nums">{formatCount(summary.video_scene_captioning.failed)}</div>
              <div className="text-zinc-500 dark:text-zinc-400">Elapsed</div>
              <div className="text-right tabular-nums">{formatDuration(summary.video_scene_captioning.elapsed_seconds)}</div>
            </div>
            {summary.video_scene_captioning.error && (
              <div role="alert" className="text-xs text-red-600 dark:text-red-400">{summary.video_scene_captioning.error}</div>
            )}
          </section>
        )}

        {summary?.captioning && (
          <section aria-live="polite" className="bg-white dark:bg-zinc-900 rounded-lg p-3 space-y-2">
            <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">AI Image Captions</div>
            {isRunning && summary.captioning.status === 'running' && summary.captioning.current != null && (
              <div className="text-xs text-zinc-500 dark:text-zinc-400">
                Captioning image {summary.captioning.current} of {formatCount(summary.captioning.total)}…
              </div>
            )}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <div className="text-zinc-500 dark:text-zinc-400">Generated</div>
              <div className="text-right tabular-nums">{formatCount(summary.captioning.generated)}</div>
              <div className="text-zinc-500 dark:text-zinc-400">Skipped (already complete)</div>
              <div className="text-right tabular-nums">{formatCount(summary.captioning.skipped)}</div>
              <div className="text-zinc-500 dark:text-zinc-400">Failed</div>
              <div className="text-right tabular-nums">{formatCount(summary.captioning.failed)}</div>
              <div className="text-zinc-500 dark:text-zinc-400">Elapsed</div>
              <div className="text-right tabular-nums">{formatDuration(summary.captioning.elapsed_seconds)}</div>
            </div>
            {summary.captioning.error && (
              <div role="alert" className="text-xs text-red-600 dark:text-red-400">{summary.captioning.error}</div>
            )}
          </section>
        )}

        {status === 'complete' && summary && (
          <div className="bg-white dark:bg-zinc-900 rounded-lg p-3 space-y-2">
            <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Run summary</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <div className="text-zinc-500 dark:text-zinc-400">Items processed</div>
              <div className="text-right text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatCount(summary.needs_processing)}
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">Faces detected</div>
              <div className="text-right text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatCount(summary.faces)}
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">Tagged items</div>
              <div className="text-right text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatCount(summary.tagged_items)}
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">Average image time</div>
              <div className="text-right text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatDuration(summary.avg_image_seconds)}
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">Average video time</div>
              <div className="text-right text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatDuration(summary.avg_video_seconds)}
              </div>
              <div className="text-zinc-500 dark:text-zinc-400">Video processing rate</div>
              <div className="text-right text-zinc-900 dark:text-zinc-100 tabular-nums">
                {formatRate(summary.avg_video_seconds_per_min)}
              </div>
            </div>
          </div>
        )}

        {/* Start error (e.g. 409 already running) */}
        {startMutation.error && (
          <div className="text-xs text-red-500 dark:text-red-400">{String(startMutation.error)}</div>
        )}

        {/* Stop error (e.g. sentinel write failed on Windows — indexer was not asked to stop) */}
        {stopMutation.error && (
          <div className="text-xs text-red-500 dark:text-red-400">{String(stopMutation.error)}</div>
        )}
      </div>

      {/* Log viewer (collapsible + expandable) */}
      {logLines.length > 0 && (
        <div className={cn(
          "bg-slate-100 dark:bg-zinc-800 rounded-lg overflow-hidden",
          logExpanded && "fixed inset-4 z-50 flex flex-col shadow-2xl"
        )}>
          <div className="flex items-center justify-between px-4 py-3 shrink-0">
            <button
              onClick={() => setLogOpen(o => !o)}
              className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
            >
              {logOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              <span>Log ({logLines.length} lines)</span>
            </button>
            <button
              onClick={() => { setLogExpanded(e => !e); setLogOpen(true) }}
              className="text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
              title={logExpanded ? "Collapse" : "Expand"}
            >
              {logExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
          </div>
          {logOpen && (
            <div ref={logRef} className={cn(
              "overflow-y-auto overflow-x-auto px-4 pb-4",
              logExpanded ? "flex-1" : "max-h-72"
            )}>
              <pre className="text-xs text-zinc-500 dark:text-zinc-400 font-mono whitespace-pre leading-5">
                {logLines.join('\n')}
              </pre>
            </div>
          )}
        </div>
      )}
      </>}
    </div>
  )
}
