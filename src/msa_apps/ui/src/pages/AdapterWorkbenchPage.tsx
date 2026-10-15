import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/apiBase'
import { getSources, type MediaSource } from '@/api/indexer'

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
  }, [])

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
    const folderStage = stageId === 'identity' || stageId === 'metadata' || stageId === 'transcription'
    if (!source || (!folderStage && !selectedPath)) return
    if (folderStage) {
      const target = stageId === 'transcription' ? 'every video' : 'every media file'
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
    <header><h1 className="text-2xl font-semibold">Adapter Workbench</h1><p className="mt-1 text-sm text-zinc-500">Stages 02–03 process every media file; Stage 04 transcribes every video in the configured source. Discovery is a bounded sample, and write-capable previews use disposable per-request state.</p></header>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <div className="flex flex-wrap items-center gap-2"><label htmlFor="source" className="text-sm">Configured source</label><select id="source" value={source} onChange={e => { setSource(e.target.value); setEntries([]); setSelectedPath(''); setDiscovery(null); setResults({}) }} className="rounded border bg-transparent px-2 py-1 text-sm">{sources.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></div>
    {discovery && <p className="text-sm text-zinc-500">Discovery: {discovery.returned} files sampled{discovery.has_more ? ' (more files exist)' : ''} in {discovery.elapsed_seconds}s.</p>}
    {entries.length > 0 && stages.some(stage => stage.runnable && !['discovery', 'identity', 'metadata', 'transcription'].includes(stage.id)) && <details className="text-sm"><summary className="cursor-pointer text-zinc-500">Optional sample selection for single-file stages 05–09</summary><div className="mt-2 flex flex-wrap items-center gap-2"><label htmlFor="sample-file">Sample file</label><select id="sample-file" value={selectedPath} onChange={e => setSelectedPath(e.target.value)} className="max-w-full rounded border bg-transparent px-2 py-1 text-sm"><option value="">Select a sample</option>{entries.map(entry => <option key={entry.relative_path} value={entry.relative_path}>{entry.relative_path}</option>)}</select></div></details>}
    <div className="space-y-3">{stages.map(stage => {
      const result = results[stage.id]
      const folderStage = stage.id === 'identity' || stage.id === 'metadata' || stage.id === 'transcription'
      const canRun = stage.runnable && stage.id !== 'discovery'
      return <article key={stage.id} className="rounded-lg border border-zinc-200 dark:border-zinc-700 p-4">
        <div className="flex justify-between gap-3"><h2 className="font-medium">{String(stage.number).padStart(2, '0')} · {stage.name}</h2><span className="text-xs text-zinc-500">{stage.runnable ? 'Runnable' : 'Not runnable'}</span></div>
        {stage.description && <p className="mt-1 text-sm text-zinc-500">{stage.description}</p>}
        {!stage.runnable && <p className="mt-1 text-sm text-amber-700 dark:text-amber-400">{stage.reason}</p>}
        {stage.id === 'discovery' && stage.runnable && <button disabled={!source || Boolean(busy)} onClick={() => void runDiscovery()} className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{busy === 'discovery' ? 'Running…' : 'Run Discovery (25 max)'}</button>}
        {canRun && folderStage && <button disabled={Boolean(busy)} onClick={() => void runStage(stage.id)} className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{busy === stage.id ? 'Running…' : `Run ${stage.name} on whole folder`}</button>}
        {canRun && !folderStage && selectedPath && <button disabled={Boolean(busy)} onClick={() => void runStage(stage.id)} className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{busy === stage.id ? 'Running…' : 'Run on selected sample'}</button>}
        {canRun && !folderStage && !selectedPath && <p className="mt-3 text-xs text-zinc-500">Single-file stage; choose a sample only when you test this stage.</p>}
        {result?.error && <p role="alert" className="mt-2 text-sm text-red-600">Failed in {result.elapsed_seconds?.toFixed(3)}s: {result.error}</p>}
        {result?.output && <div className="mt-2 space-y-2"><p className="text-xs text-zinc-500">Completed in {result.elapsed_seconds?.toFixed(3)}s</p><pre className="max-h-96 overflow-auto rounded bg-zinc-100 dark:bg-zinc-800 p-3 text-xs">{JSON.stringify(result.output, null, 2)}</pre></div>}
      </article>
    })}</div>
  </section>
}
