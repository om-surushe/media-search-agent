import { useState } from 'react'
import { previewVideoKeyframes, type KeyframePreview } from '../api/keyframes'

export function KeyframesPage() {
  const [file, setFile] = useState<File | null>(null)
  const [sensitivity, setSensitivity] = useState(8)
  const [testSharedFrameCache, setTestSharedFrameCache] = useState(true)
  const [testAdaptiveSelection, setTestAdaptiveSelection] = useState(false)
  const [testLongShotCoverage, setTestLongShotCoverage] = useState(false)
  const [preview, setPreview] = useState<KeyframePreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function analyze() {
    if (!file || loading) return
    setLoading(true)
    setError(null)
    setPreview(null)
    try {
      setPreview(await previewVideoKeyframes(
        file, sensitivity, testSharedFrameCache, testAdaptiveSelection, testLongShotCoverage,
      ))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not analyze this video.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Video keyframes</h1>
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
          Every frame is compared with the previous and last selected frame. Similar-looking repeats are skipped; new frames are kept when enough pixels change. Times are approximate for variable-frame-rate videos.
        </p>
      </header>

      <section className="flex flex-wrap items-end gap-4 rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <label className="flex min-w-64 flex-1 flex-col gap-2 text-sm">
          <span className="font-medium">Choose a video</span>
          <input
            aria-label="Choose a video"
            type="file"
            accept="video/*"
            onChange={event => {
              setFile(event.currentTarget.files?.[0] ?? null)
              setPreview(null)
              setError(null)
            }}
            className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-indigo-600 file:px-3 file:py-2 file:text-white hover:file:bg-indigo-500"
          />
          <span className="text-xs text-zinc-500">Local temporary upload; deleted after analysis. Maximum 512 MiB.</span>
        </label>

        <label className="flex w-56 flex-col gap-2 text-sm">
          <span className="font-medium">Change threshold: {sensitivity}%</span>
          <input
            aria-label="Change threshold"
            type="range"
            min="1"
            max="30"
            step="1"
            value={sensitivity}
            onChange={event => setSensitivity(Number(event.currentTarget.value))}
          />
          <span className="text-xs text-zinc-500">Percent of pixels changing by ≥25/255; lower keeps more. Near-duplicates are skipped.</span>
        </label>

        <label className="flex max-w-xs items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={testSharedFrameCache}
            onChange={event => setTestSharedFrameCache(event.currentTarget.checked)}
          />
          Also test shared frame IDs/cache (temporary isolated data; no index changes)
        </label>

        <label className="flex max-w-sm items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={testAdaptiveSelection}
            onChange={event => setTestAdaptiveSelection(event.currentTarget.checked)}
          />
          Compare opt-in adaptive selection with shot midpoints (extra full scan)
        </label>
        <label className="flex max-w-sm items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={testLongShotCoverage}
            disabled={!testAdaptiveSelection}
            onChange={event => setTestLongShotCoverage(event.currentTarget.checked)}
          />
          Include novelty-gated coverage for long shots
        </label>

        <button
          type="button"
          disabled={!file || loading}
          onClick={analyze}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading
            ? testAdaptiveSelection
              ? 'Scanning and comparing selectors…'
              : testSharedFrameCache ? 'Scanning and checking cache…' : 'Scanning frames…'
            : 'Show changing frames'}
        </button>
      </section>

      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}

      {preview?.adaptive_selection_test && (
        <section aria-label="Adaptive selection comparison" className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="font-medium">Adaptive selection comparison</h2>
          {preview.adaptive_selection_test.error ? (
            <p role="alert" className="mt-2 text-sm text-red-500">{preview.adaptive_selection_test.error}</p>
          ) : (
            <>
              <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
                {preview.adaptive_selection_test.shots_detected} shots · {preview.adaptive_selection_test.midpoint_frames} midpoint fallback frames · {preview.adaptive_selection_test.adaptive_frames} additional adaptive candidates. Existing midpoint frames are retained; candidates are additive. This comparison uses indexer settings and does not change the library.
              </p>
              {preview.adaptive_selection_test.frames.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1 text-xs text-zinc-500">
                  {preview.adaptive_selection_test.frames.slice(0, 10).map((frame, index) => (
                    <li key={`${frame.selection_version}-${frame.shot_index}-${index}`} className="flex items-center gap-3">
                      {frame.image_data_url && (
                        <img
                          src={frame.image_data_url}
                          alt={`Adaptive candidate from shot ${frame.shot_index + 1} at ${frame.timestamp.toFixed(1)} seconds`}
                          className="h-16 w-24 rounded object-cover"
                        />
                      )}
                      <span>
                        Shot {frame.shot_index + 1} · {frame.timestamp.toFixed(3)}s · {frame.reason} · {frame.change_percent.toFixed(1)}% change
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}

      {preview?.frame_cache_test && (
        <section aria-label="Shared frame cache test" className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="font-medium">Shared frame cache test</h2>
          {preview.frame_cache_test.error ? (
            <p role="alert" className="mt-2 text-sm text-red-500">{preview.frame_cache_test.error}</p>
          ) : (
            <>
              <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
                Tested {preview.frame_cache_test.tested_frames} of {preview.frame_cache_test.selected_frames} selected frames; second pass reused {preview.frame_cache_test.cache_reuse_hits} cached rendition{preview.frame_cache_test.cache_reuse_hits === 1 ? '' : 's'}. The temporary database and cache are deleted after the request.
              </p>
              {preview.frame_cache_test.frames.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1 text-xs text-zinc-500">
                  {preview.frame_cache_test.frames.slice(0, 5).map(frame => (
                    <li key={`${frame.requested_timestamp}-${frame.frame_id ?? frame.error}`}>
                      {frame.actual_timestamp?.toFixed(3) ?? '—'}s · {frame.frame_id?.slice(0, 16) ?? frame.error ?? 'no frame'} · {frame.reused ? 'cache hit' : 'miss'}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}

      {preview && (
        <section aria-live="polite" className="flex flex-col gap-4">
          <div className="text-sm text-zinc-600 dark:text-zinc-300">
            {preview.frames.length} frame{preview.frames.length === 1 ? '' : 's'} shown · {preview.duration.toFixed(1)}s · scanned {preview.frames_scanned.toLocaleString()} source frames · {preview.change_frames} change-triggered · {preview.slow_change_frames} gradual-change
            {preview.omitted_frames > 0 && ` · ${preview.omitted_frames} additional frames omitted by the preview limit`}
          </div>
          {preview.frames.length === 0 ? (
            <p className="text-sm text-zinc-500">No frames could be decoded from this video.</p>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {preview.frames.map((frame, index) => (
                <figure key={`${index}-${frame.timestamp}`} className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
                  <img src={frame.image_data_url} alt={`Frame at ${frame.timestamp.toFixed(1)} seconds`} className="aspect-video w-full bg-black object-contain" />
                  <figcaption className="px-3 py-2 text-sm text-zinc-600 dark:text-zinc-300">
                    {frame.timestamp.toFixed(2)}s · {frame.reason.replace('_', ' ')}{frame.reason !== 'start' ? ` (${frame.change_percent}% new)` : ''}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
