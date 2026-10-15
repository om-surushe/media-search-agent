import { useEffect, useRef, useState } from 'react'
import { apiUrl } from '@/lib/apiBase'
import { fetchSetupStatus, retrySetup, type ModelInfo } from '@/api/setup'
import { getSources, type MediaSource } from '@/api/indexer'
import { useSetupWS } from '@/hooks/useSetupWS'

type Stage = { id: string; number: number; name: string; runnable: boolean; reason?: string | null; description?: string }
type Entry = { name: string; relative_path: string; extension: string; size_bytes: number }
type Preview = { source: string; returned: number; has_more: boolean; entries: Entry[]; elapsed_seconds: number }
type RunResult = { output?: Record<string, unknown>; error?: string; elapsed_seconds?: number }

export function AdapterWorkbenchPage() {
  const [stages, setStages] = useState<Stage[]>([])
  const [sources, setSources] = useState<MediaSource[]>([])
  const [source, setSource] = useState('')
  const [entries, setEntries] = useState<Entry[]>([])
  const [selectedPath, setSelectedPath] = useState('')
  const [discovery, setDiscovery] = useState<Preview | null>(null)
  const [results, setResults] = useState<Record<string, RunResult>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [models, setModels] = useState<ModelInfo[]>([])
  const [modelSetupReadOnly, setModelSetupReadOnly] = useState(false)
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelError, setModelError] = useState('')
  const [modelLog, setModelLog] = useState<string[]>([])
  const [setupConnection, setSetupConnection] = useState(0)
  const retryRevision = useRef<number | null>(null)
  const seenModelStates = useRef<Record<string, string>>({})
  const { models: liveModels, complete: modelSetupComplete, revision: setupRevision } = useSetupWS(setupConnection)

  useEffect(() => {
    void Promise.all([
      fetch(apiUrl('/adapters')).then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() }),
      getSources(),
    ]).then(([catalog, configured]) => {
      setStages(catalog)
      const enabled = configured.filter(item => item.enabled)
      setSources(enabled)
      setSource(enabled[0]?.name ?? '')
    }).catch(e => setError(String(e)))
    void refreshModels()
  }, [])

  async function refreshModels(forceStageRefresh = false) {
    try {
      const status = await fetchSetupStatus()
      setModels(status.models)
      setModelSetupReadOnly(Boolean(status.read_only_mode))
      if (status.ready && (!loadingModels || forceStageRefresh)) setLoadingModels(false)
      if (forceStageRefresh || (status.ready && !loadingModels)) {
        const response = await fetch(apiUrl('/adapters'))
        if (response.ok) setStages(await response.json())
      }
      return status
    } catch (e) {
      setModelError(String(e))
      return null
    }
  }

  useEffect(() => {
    if (!loadingModels) return
    const timer = window.setInterval(() => { void refreshModels() }, 3000)
    return () => window.clearInterval(timer)
  }, [loadingModels])

  useEffect(() => {
    if (!liveModels) return
    const events: string[] = []
    for (const [id, state] of Object.entries(liveModels)) {
      const signature = `${state.status}:${state.error ?? ''}`
      if (seenModelStates.current[id] === signature) continue
      seenModelStates.current[id] = signature
      const label = models.find(model => model.id === id)?.label ?? id.toUpperCase()
      events.push(`${new Date().toLocaleTimeString()} · ${label}: ${state.status}${state.error ? ` — ${state.error}` : ''}`)
    }
    if (events.length) setModelLog(current => [...current, ...events].slice(-50))
  }, [liveModels, models])

  useEffect(() => {
    if (!loadingModels || retryRevision.current === null || setupRevision <= retryRevision.current || !modelSetupComplete) return
    retryRevision.current = null
    setLoadingModels(false)
    void refreshModels(true)
  }, [loadingModels, modelSetupComplete, setupRevision])

  async function loadModels() {
    const missing = models.filter(model => !model.present || liveModels?.[model.id]?.status === 'error')
    const sizeMb = missing.reduce((total, model) => total + model.size_mb, 0)
    const sources = [...new Set(missing.map(model => model.source).filter(Boolean))].join(', ')
    setModelError('')
    setLoadingModels(true)
    retryRevision.current = setupRevision
    setModelLog(current => [...current, `${new Date().toLocaleTimeString()} · Starting model setup (${missing.length} missing, ~${sizeMb} MB${sources ? ` from ${sources}` : ''}).`].slice(-50))
    try {
      await retrySetup()
      setSetupConnection(connection => connection + 1)
    } catch (e) {
      retryRevision.current = null
      setLoadingModels(false)
      setModelError(String(e))
    }
  }

  async function runDiscovery() {
    setBusy('discovery'); setError('')
    try {
      const response = await fetch(apiUrl(`/adapters/discovery/run?source_name=${encodeURIComponent(source)}&limit=25`), { method: 'POST' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail ?? response.statusText)
      setDiscovery(result); setEntries(result.entries); setSelectedPath('')
      setResults({})
    } catch (e) { setError(String(e)) } finally { setBusy(null) }
  }

  async function runStage(stageId: string) {
    const folderStage = ['identity', 'metadata', 'transcription', 'image-visual'].includes(stageId)
    if (!source || (!folderStage && !selectedPath)) return
    if (folderStage) {
      const target = stageId === 'transcription' ? 'every video' : stageId === 'image-visual' ? 'every image' : 'every media file'
      if (!window.confirm(`Run ${stageId} across ${target} in configured source “${source}”? This read-only run may take time.`)) return
    }
    setBusy(stageId)
    setResults(current => ({ ...current, [stageId]: {} }))
    const started = performance.now()
    try {
      const query = new URLSearchParams({ source_name: source })
      if (!folderStage) query.set('relative_path', selectedPath)
      const response = await fetch(apiUrl(`/adapters/${stageId}/run?${query}`), { method: 'POST' })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail ?? response.statusText)
      setResults(current => ({ ...current, [stageId]: { output: body, elapsed_seconds: body.elapsed_seconds ?? (performance.now() - started) / 1000 } }))
    } catch (e) {
      setResults(current => ({ ...current, [stageId]: { error: String(e), elapsed_seconds: (performance.now() - started) / 1000 } }))
    } finally { setBusy(null) }
  }

  return <section className="max-w-4xl space-y-5">
    <header><h1 className="text-2xl font-semibold">Adapter Workbench</h1><p className="mt-1 text-sm text-zinc-500">Stages 02–03 process every media file; Stage 04 transcribes every video; Stage 05 processes every image when local models are available. Discovery is a bounded sample, and previews use disposable per-request state.</p></header>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <div className="flex flex-wrap items-center gap-2"><label htmlFor="source" className="text-sm">Configured source</label><select id="source" value={source} onChange={e => { setSource(e.target.value); setEntries([]); setSelectedPath(''); setDiscovery(null); setResults({}) }} className="rounded border bg-transparent px-2 py-1 text-sm">{sources.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></div>
    {discovery && <p className="text-sm text-zinc-500">Discovery: {discovery.returned} files sampled{discovery.has_more ? ' (more files exist)' : ''} in {discovery.elapsed_seconds}s.</p>}
    <section className="rounded-lg border border-zinc-200 dark:border-zinc-700 p-4">
      <h2 className="font-medium">Model setup</h2>
      <p className="mt-1 text-sm text-zinc-500">Stage 05 always runs the configured RT-DETR object detector; optional face recognition follows Settings. Object detection may be slow on CPU. Model selection and optional detector settings are in <a className="text-blue-600 underline" href="/settings">Settings</a>. Downloads use the app’s verified sources; loading a preview never downloads models.</p>
      {models.length > 0 && <ul className="mt-2 space-y-1 text-xs text-zinc-500">{models.map(model => {
        const live = liveModels?.[model.id]
        return <li key={model.id}>{model.label} · ~{model.size_mb} MB · {live?.status ?? (model.present ? 'cached' : 'missing')}{model.source ? ` · ${model.source}` : ''}{live?.error && <span className="block text-red-600">{live.error}</span>}</li>
      })}</ul>}
      {modelError && <p role="alert" className="mt-2 text-sm text-red-600">Model setup: {modelError}</p>}
      <button disabled={loadingModels || modelSetupReadOnly} onClick={() => void loadModels()} className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{loadingModels ? 'Loading models…' : models.some(model => !model.present || liveModels?.[model.id]?.status === 'error') ? `Download / retry ${models.filter(model => !model.present || liveModels?.[model.id]?.status === 'error').length} model(s) (~${models.filter(model => !model.present || liveModels?.[model.id]?.status === 'error').reduce((total, model) => total + model.size_mb, 0)} MB)` : 'Retry / verify model setup'}</button>
      {modelSetupReadOnly && <p className="mt-2 text-xs text-amber-700">Model downloads are disabled in read-only mode.</p>}
      {modelLog.length > 0 && <details open={loadingModels} className="mt-3 text-xs"><summary className="cursor-pointer font-medium">Model setup logs ({modelLog.length})</summary><ol role="log" aria-live="polite" className="mt-2 max-h-40 space-y-1 overflow-auto font-mono">{modelLog.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}</ol></details>}
    </section>
    {entries.length > 0 && stages.some(stage => stage.runnable && !['discovery', 'identity', 'metadata', 'transcription', 'image-visual'].includes(stage.id)) && <details className="text-sm"><summary className="cursor-pointer text-zinc-500">Optional sample selection for single-file stages 06–09</summary><div className="mt-2 flex flex-wrap items-center gap-2"><label htmlFor="sample-file">Sample file</label><select id="sample-file" value={selectedPath} onChange={e => setSelectedPath(e.target.value)} className="max-w-full rounded border bg-transparent px-2 py-1 text-sm"><option value="">Select a sample</option>{entries.map(entry => <option key={entry.relative_path} value={entry.relative_path}>{entry.relative_path}</option>)}</select></div></details>}
    <div className="space-y-3">{stages.map(stage => {
      const result = results[stage.id]
      const folderStage = ['identity', 'metadata', 'transcription', 'image-visual'].includes(stage.id)
      const canRun = stage.runnable && stage.id !== 'discovery'
      return <article key={stage.id} className="rounded-lg border border-zinc-200 dark:border-zinc-700 p-4">
        <div className="flex justify-between gap-3"><h2 className="font-medium">{String(stage.number).padStart(2, '0')} · {stage.name}</h2><span className="text-xs text-zinc-500">{stage.runnable ? 'Runnable' : 'Not runnable'}</span></div>
        {stage.description && <p className="mt-1 text-sm text-zinc-500">{stage.description}</p>}
        {!stage.runnable && <p className="mt-1 text-sm text-amber-700 dark:text-amber-400">{stage.reason}</p>}
        {stage.id === 'discovery' && stage.runnable && <button disabled={!source || Boolean(busy)} onClick={() => void runDiscovery()} className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{busy === 'discovery' ? 'Running…' : 'Run Discovery (25 max)'}</button>}
        {canRun && folderStage && <button disabled={Boolean(busy)} onClick={() => void runStage(stage.id)} className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{busy === stage.id ? 'Running…' : stage.id === 'image-visual' ? 'Run on every image' : `Run ${stage.name} on whole folder`}</button>}
        {canRun && !folderStage && stage.id !== 'image-visual' && selectedPath && <button disabled={Boolean(busy)} onClick={() => void runStage(stage.id)} className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{busy === stage.id ? 'Running…' : 'Run on selected sample'}</button>}
        {canRun && !folderStage && !selectedPath && stage.id !== 'image-visual' && <p className="mt-3 text-xs text-zinc-500">Single-file stage; choose a sample only when you test this stage.</p>}
        {result?.error && <p role="alert" className="mt-2 text-sm text-red-600">Failed in {result.elapsed_seconds?.toFixed(3)}s: {result.error}</p>}
        {result?.output && <div className="mt-2 space-y-2"><p className="text-xs text-zinc-500">Completed in {result.elapsed_seconds?.toFixed(3)}s</p><pre className="max-h-96 overflow-auto rounded bg-zinc-100 dark:bg-zinc-800 p-3 text-xs">{JSON.stringify(result.output, null, 2)}</pre></div>}
      </article>
    })}</div>
  </section>
}
