import { useEffect, useRef, useState } from 'react'
import { X, MapPin, Calendar, Tag, Expand, Copy, Check } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { faceThumbnailUrl, getAssetIntelligence, imageUrl, videoUrl } from '../../api/media'
import { trackOpen } from '../../api/search'
import { FaceStrip } from './FaceStrip'
import { MediaOrganizationControls } from './MediaOrganizationControls'
import { cn } from '../../lib/utils'
import type { VideoSceneSearchMatch } from '../../api/types'

interface DrawerItem {
  id: string
  type?: 'image' | 'video' | null
  date?: string | null
  place?: string | null
  gps_lat?: number | null
  gps_lon?: number | null
  score?: number | null
  raw_similarity_score?: number | null
  similarity_score?: number | null
  person_boost?: number | null
  person_multiplier?: number | null
  expansion_boost?: number | null
  expansion_multiplier?: number | null
  tags?: string[] | null
  why?: string | null
  timestamp?: number | null
  scene_timestamp?: number | null
  scene_matches?: VideoSceneSearchMatch[] | null
  path?: string | null
  // People page: similarity score from face search (0–1)
  similarity?: number | null
}

interface MediaDetailDrawerProps {
  item: DrawerItem | null
  onClose: () => void
  searchId?: string | null  // present only when opened from a search → enables /track/open
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function PathRow({ path }: { path: string }) {
  const [copied, setCopied] = useState(false)
  const slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  const filename = slash >= 0 ? path.slice(slash + 1) : path

  const copy = () => {
    navigator.clipboard.writeText(path).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }).catch(() => {})
  }

  return (
    <div className="group relative flex items-center gap-2">
      <span className="text-xs text-zinc-400 dark:text-zinc-500 truncate min-w-0 flex-1">{filename}</span>
      <button
        onClick={copy}
        title={path}
        className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
      >
        {copied ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
      </button>
      {/* Full path on hover */}
      <div className="absolute bottom-full left-0 mb-1 hidden group-hover:block z-10 max-w-xs">
        <div className="bg-zinc-800 text-zinc-200 text-xs font-mono px-2 py-1.5 rounded shadow-lg break-all">
          {path}
        </div>
      </div>
    </div>
  )
}

export function MediaDetailDrawer({ item, onClose, searchId }: MediaDetailDrawerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const pendingVideoSeekRef = useRef<number | null>(null)
  const [selectedKeyframeId, setSelectedKeyframeId] = useState<number | null>(null)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [imgLightbox, setImgLightbox] = useState(false)

  // Log the open as a relevance label when this item came from a search (best-effort).
  // Track once per opened item — a later searchId change while the same item stays open
  // (background refetch / a new search) must not re-post a duplicate, mis-attributed label.
  const trackedItemRef = useRef<string | null>(null)
  useEffect(() => {
    if (!item?.id) {
      trackedItemRef.current = null  // reset when the drawer closes
      return
    }
    if (searchId && trackedItemRef.current !== item.id) {
      trackedItemRef.current = item.id
      trackOpen(searchId, item.id)
    }
  }, [item?.id, searchId])

  const { data: intelligence, isLoading: intelligenceLoading, error: intelligenceError } = useQuery({
    queryKey: ['asset-intelligence', item?.id],
    queryFn: () => getAssetIntelligence(item!.id),
    enabled: !!item,
    staleTime: 30_000,
  })

  const objectState = intelligence?.pipeline_status.find(stage => stage.pipeline === 'object_detection')
  const faceState = intelligence?.pipeline_status.find(stage => stage.pipeline === 'face_detection')
  const imageCaptions = intelligence?.descriptions.image_captions ?? []
  const videoSceneCaptions = intelligence?.descriptions.video_scene_captions ?? []

  // Reset lightbox when item changes
  useEffect(() => {
    setImgLightbox(false)
  }, [item?.id])

  const applyPendingVideoSeek = () => {
    const video = videoRef.current
    const timestamp = pendingVideoSeekRef.current
    if (!video || timestamp == null || video.readyState < 1) return
    try {
      video.pause()
      video.currentTime = timestamp
      pendingVideoSeekRef.current = null
    } catch {
      pendingVideoSeekRef.current = null
      setVideoError('Unable to seek to this video timestamp.')
    }
  }

  const selectKeyframe = (id: number, timestamp: number) => {
    pendingVideoSeekRef.current = timestamp
    setSelectedKeyframeId(id)
    setVideoError(null)
    const video = videoRef.current
    if (!video) {
      setVideoError('Video preview is unavailable.')
      return
    }
    if (video.readyState < 1) video.pause()
    applyPendingVideoSeek()
  }

  useEffect(() => {
    pendingVideoSeekRef.current = item?.type === 'video'
      ? item.scene_timestamp ?? item.scene_matches?.[0]?.timestamp ?? item.timestamp ?? null
      : null
    setSelectedKeyframeId(item?.scene_matches?.[0]?.keyframe_id ?? null)
    setVideoError(null)
    applyPendingVideoSeek()
  }, [item?.id, item?.type, item?.timestamp, item?.scene_timestamp, item?.scene_matches?.[0]?.timestamp, item?.scene_matches?.[0]?.keyframe_id])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (imgLightbox) setImgLightbox(false)
        else if (item) onClose()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose, item, imgLightbox])

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn('fixed inset-0 bg-black/60 z-40 transition-opacity md:hidden', item ? 'opacity-100' : 'opacity-0 pointer-events-none')}
        onClick={onClose}
      />

      {/* Drawer */}
      <div className={cn(
        'fixed top-0 right-0 h-full w-full md:w-[min(42rem,calc(100vw-4rem))] bg-white dark:bg-zinc-900 z-50 flex flex-col',
        'shadow-2xl transition-transform duration-300',
        item ? 'translate-x-0' : 'translate-x-full',
      )}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-zinc-800">
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200 truncate">{item?.id ?? 'Asset details'}</span>
          <button onClick={onClose} aria-label="Close asset inspector" className="text-zinc-400 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-100">
            <X size={18} />
          </button>
        </div>

        {item && (
          <div className="flex-1 overflow-y-auto">
            {/* Media preview */}
            <div className="bg-slate-100 dark:bg-zinc-950 flex items-center justify-center relative group/preview">
              {item.type === 'video' ? (
                <video
                  key={item.id}
                  ref={videoRef}
                  src={videoUrl(item.id)}
                  controls
                  className="w-full max-h-72 object-contain"
                  onLoadedMetadata={applyPendingVideoSeek}
                  onError={() => {
                    pendingVideoSeekRef.current = null
                    setVideoError('Unable to load or seek this video.')
                  }}
                />
              ) : (
                <>
                  <img
                    src={imageUrl(item.id)}
                    alt=""
                    className="w-full max-h-72 object-contain cursor-zoom-in"
                    onClick={() => setImgLightbox(true)}
                  />
                  <button
                    onClick={() => setImgLightbox(true)}
                    className="absolute top-2 right-2 p-1.5 rounded-lg bg-black/40 text-white opacity-0 group-hover/preview:opacity-100 transition-opacity hover:bg-black/70"
                    title="View full size"
                  >
                    <Expand size={15} />
                  </button>
                </>
              )}
            </div>
            {item.type === 'video' && videoError && <p role="alert" className="px-4 pt-2 text-xs text-rose-600">{videoError}</p>}

            {/* Metadata */}
            <div className="px-4 py-4 space-y-4">
              {/* Semantic search score */}
              {item.score != null && (() => {
                const pct = Math.min(100, Math.max(0, Math.round(item.score * 100)))
                return (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 bg-slate-200 dark:bg-zinc-700 rounded-full overflow-hidden">
                      <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs text-zinc-500 dark:text-zinc-400 tabular-nums">{pct}% match</span>
                  </div>
                )
              })()}

              {/* Face similarity score */}
              {item.similarity != null && (() => {
                const pct = Math.min(100, Math.max(0, Math.round(item.similarity * 100)))
                return (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 bg-slate-200 dark:bg-zinc-700 rounded-full overflow-hidden">
                      <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs text-zinc-500 dark:text-zinc-400 tabular-nums">{pct}% face similarity</span>
                  </div>
                )
              })()}

              {(item.raw_similarity_score != null || item.person_boost != null || item.expansion_boost != null) && (
                <div className="rounded-lg bg-slate-50 dark:bg-zinc-800/60 px-3 py-2">
                  <div className="text-xs uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-2">Score details</div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    {item.raw_similarity_score != null && (
                      <>
                        <span className="text-zinc-500 dark:text-zinc-400">Raw similarity</span>
                        <span className="text-zinc-700 dark:text-zinc-200 tabular-nums text-right">{item.raw_similarity_score.toFixed(4)}</span>
                      </>
                    )}
                    {item.similarity_score != null && (
                      <>
                        <span className="text-zinc-500 dark:text-zinc-400">Similarity</span>
                        <span className="text-zinc-700 dark:text-zinc-200 tabular-nums text-right">{item.similarity_score.toFixed(4)}</span>
                      </>
                    )}
                    {item.person_boost != null && (
                      <>
                        <span className="text-zinc-500 dark:text-zinc-400">Person boost</span>
                        <span className="text-zinc-700 dark:text-zinc-200 tabular-nums text-right">{item.person_boost.toFixed(4)}</span>
                      </>
                    )}
                    {item.expansion_boost != null && (
                      <>
                        <span className="text-zinc-500 dark:text-zinc-400">Expansion boost</span>
                        <span className="text-zinc-700 dark:text-zinc-200 tabular-nums text-right">{item.expansion_boost.toFixed(4)}</span>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* File path — hover to reveal full path + copy */}
              {item.path && <PathRow path={item.path} />}
              <MediaOrganizationControls mediaId={item.id} />

              {/* Date */}
              {item.date && (
                <div className="flex items-start gap-2 text-sm">
                  <Calendar size={14} className="text-zinc-400 dark:text-zinc-500 mt-0.5 shrink-0" />
                  <span className="text-zinc-700 dark:text-zinc-300">{formatDate(item.date)}</span>
                </div>
              )}

              {/* Place / GPS */}
              {(item.place || item.gps_lat != null) && (() => {
                const mapsUrl = item.gps_lat != null
                  ? `https://www.google.com/maps?q=${item.gps_lat},${item.gps_lon}`
                  : null
                const content = (
                  <>
                    <MapPin size={14} className={`mt-0.5 shrink-0 ${mapsUrl ? 'text-indigo-400 hover:text-indigo-600' : 'text-zinc-400 dark:text-zinc-500'}`} />
                    <span className="text-zinc-700 dark:text-zinc-300">
                      {item.place ?? `${item.gps_lat?.toFixed(4)}, ${item.gps_lon?.toFixed(4)}`}
                    </span>
                  </>
                )
                return mapsUrl ? (
                  <a href={mapsUrl} target="_blank" rel="noopener noreferrer"
                    className="flex items-start gap-2 text-sm hover:underline"
                    title="Open in Google Maps"
                  >
                    {content}
                  </a>
                ) : (
                  <div className="flex items-start gap-2 text-sm">{content}</div>
                )
              })()}

              {/* Tags */}
              {item.tags && item.tags.length > 0 && (
                <div className="flex items-start gap-2">
                  <Tag size={14} className="text-zinc-400 dark:text-zinc-500 mt-0.5 shrink-0" />
                  <div className="flex flex-wrap gap-1">
                    {item.tags.map(t => (
                      <span key={t} className="px-2 py-0.5 bg-slate-100 dark:bg-zinc-800 rounded text-xs text-zinc-600 dark:text-zinc-300">{t}</span>
                    ))}
                  </div>
                </div>
              )}


              {/* Asset intelligence — stored facts only; unavailable stages stay explicit. */}
              <section className="border-t border-slate-200 dark:border-zinc-800 pt-4 space-y-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Asset intelligence</h2>
                {intelligenceLoading && <p className="text-xs text-zinc-500">Loading asset metadata…</p>}
                {intelligenceError && <p role="alert" className="text-xs text-rose-600">Asset metadata unavailable.</p>}
                {intelligence && <>
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    {[
                      ['File', intelligence.media.filename], ['Type', intelligence.media.mime],
                      ['Size', intelligence.media.size_bytes == null ? null : `${new Intl.NumberFormat().format(intelligence.media.size_bytes)} bytes`],
                      ['Dimensions', intelligence.media.width && intelligence.media.height ? `${intelligence.media.width} × ${intelligence.media.height}` : null],
                      ['Duration', intelligence.media.duration == null ? null : `${intelligence.media.duration.toFixed(2)} s`],
                      ['Source', intelligence.media.source_name], ['Folder', intelligence.media.source_folder],
                      ['Camera', intelligence.media.camera], ['Lens', intelligence.media.lens],
                      ['Place', intelligence.media.place],
                      ['GPS coordinates', intelligence.media.gps_lat == null || intelligence.media.gps_lon == null ? null : `${intelligence.media.gps_lat}, ${intelligence.media.gps_lon}`],
                      ['GPS extraction', intelligence.media.gps_processed == null ? null : intelligence.media.gps_processed ? `processed${intelligence.media.gps_data_mode ? ` · ${intelligence.media.gps_data_mode}` : ''}` : 'not processed'],
                      ['Captured', formatDate(intelligence.media.captured_at)],
                      ['Indexed', formatDate(intelligence.media.added_at)],
                      ['Modified', formatDate(intelligence.media.filesystem_mtime)],
                      ['Content hash', intelligence.media.hash_blake3],
                    ].filter(([, value]) => value && value !== '—').map(([label, value]) => (
                      <div key={label} className="contents"><dt className="text-zinc-500">{label}</dt><dd className="text-right text-zinc-700 dark:text-zinc-300 truncate" title={String(value)}>{value}</dd></div>
                    ))}
                  </dl>
                  {intelligence.pipeline_status.map(stage => (
                    <div key={stage.pipeline} className="flex justify-between gap-3 text-xs">
                      <span className="text-zinc-500">{stage.pipeline === 'face_detection' ? 'Face detection' : 'Object detection'}</span>
                      <span className="text-zinc-700 dark:text-zinc-300 text-right">
                        {stage.status.replace('_', ' ')}{stage.error_type ? ` · ${stage.error_type}` : ''}
                        {stage.evidence === 'legacy_flag' ? ' · legacy record' : ''}
                      </span>
                    </div>
                  ))}
                  <div className="text-xs text-zinc-500 space-y-1">
                    <h3 className="font-medium text-zinc-600 dark:text-zinc-300">Embeddings (vectors are not returned)</h3>
                    {(['image', 'keyframes'] as const).map(kind => {
                      const embedding = intelligence.embeddings[kind]
                      return <p key={kind}>{kind}: {embedding.present ? `${embedding.count} stored · ${embedding.dimensions ?? '?'} dimensions${embedding.model ? ` · ${embedding.model}` : ''}${embedding.created_at ? ` · ${formatDate(embedding.created_at)}` : ''}` : 'not stored'}</p>
                    })}
                  </div>
                  <div>
                    <h3 className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Stored object labels</h3>
                    {intelligence.objects.length ? <div className="flex flex-wrap gap-1">{intelligence.objects.map((object, index) => <span key={`${object.label}-${index}`} className="px-2 py-0.5 rounded bg-slate-100 dark:bg-zinc-800 text-xs text-zinc-600 dark:text-zinc-300">{object.label}{object.confidence != null ? ` · ${(object.confidence * 100).toFixed(1)}%` : ''}{object.timestamp != null ? ` · ${object.timestamp.toFixed(1)}s` : ''}{object.bbox ? ` · box ${object.bbox.map(n => n.toFixed(2)).join(',')}` : ''}</span>)}</div> : <p className="text-xs text-zinc-500">{objectState?.status === 'completed' ? 'Detection completed; no labels were stored.' : objectState?.status === 'failed' ? `Detection failed${objectState.error_type ? ` (${objectState.error_type})` : ''}.` : objectState?.status === 'disabled' ? 'Detection is disabled; no result is available.' : 'Detection has not completed; no result is available.'}</p>}
                    {intelligence.objects_evidence === 'stored_label_only' && <p className="mt-1 text-[11px] text-zinc-400">Stored labels only; confidence scores and bounding boxes are not available.</p>}
                  </div>
                  {intelligence.media.type === 'video' && <div>
                    <h3 className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Shots & keyframes · {intelligence.total_shots} shots · {intelligence.total_keyframes} keyframes</h3>
                    <div className="space-y-1">{intelligence.keyframes.map(k => <button key={k.id} type="button" aria-pressed={selectedKeyframeId === k.id} className={cn('block text-left text-xs rounded px-1 -mx-1 hover:underline', selectedKeyframeId === k.id ? 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200' : 'text-indigo-600 dark:text-indigo-300')} onClick={() => selectKeyframe(k.id, k.timestamp)}>{k.timestamp.toFixed(1)}s · shot {k.shot_index + 1}{k.tags.length ? ` · ${k.tags.join(', ')}` : ''}{k.place ? ` · ${k.place}` : ''}</button>)}</div>
                  </div>}
                  {intelligence.media.type === 'video' && <div>
                    <h3 className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Visual Scene Descriptions</h3>
                    {videoSceneCaptions.length === 0 ? (
                      <p className="text-xs text-zinc-500">No visual scene descriptions available.</p>
                    ) : (
                      <div className="space-y-2">
                        {videoSceneCaptions.map(scene => (
                          <article key={`${scene.keyframe_id}-${scene.model_id}-${scene.prompt_version}`} className="rounded-lg bg-slate-50 dark:bg-zinc-800/60 px-3 py-2">
                            <button
                              type="button"
                              aria-label={`Seek to scene at ${scene.timestamp.toFixed(1)} seconds`}
                              aria-pressed={selectedKeyframeId === scene.keyframe_id}
                              onClick={() => selectKeyframe(scene.keyframe_id, scene.timestamp)}
                              className={cn('text-xs tabular-nums hover:underline', selectedKeyframeId === scene.keyframe_id ? 'text-indigo-800 dark:text-indigo-200' : 'text-indigo-600 dark:text-indigo-300')}
                            >{scene.timestamp.toFixed(1)}s</button>
                            <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-200">{scene.caption ?? 'Caption generation failed for this frame.'}</p>
                            <p className="mt-2 text-[11px] text-zinc-400 break-all">{scene.model_id} · {scene.prompt_version} · {formatDate(scene.generated_at_utc)} · {scene.status}</p>
                          </article>
                        ))}
                      </div>
                    )}
                  </div>}
                  <div>
                    <h3 className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Face detections · {intelligence.face_count}</h3>
                    {intelligence.faces.length ? <div className="space-y-2">{intelligence.faces.map(face => <div key={face.face_id} className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300"><img src={faceThumbnailUrl(face.face_id)} alt="" className="h-8 w-8 rounded object-cover" onError={e => { e.currentTarget.hidden = true }} /><span>{face.person_name ?? 'Unknown identity'}{face.confidence != null ? ` · ${(face.confidence * 100).toFixed(1)}%` : ''}{face.timestamp != null ? ` · ${face.timestamp.toFixed(1)}s` : ''}{face.shot_index != null ? ` · shot ${face.shot_index + 1}` : ''}<span className="block text-zinc-400">Box {face.bbox.map(n => n.toFixed(3)).join(', ')}{face.gender ? ` · ${face.gender}` : ''}{face.age != null ? ` · age ${face.age}` : ''}{face.embedding.present ? ` · embedding ${face.embedding.dimensions ?? '?'}d${face.embedding.model ? ` (${face.embedding.model})` : ''}` : ''}</span></span></div>)}</div> : <p className="text-xs text-zinc-500">{faceState?.status === 'completed' ? 'Detection completed; no faces were stored.' : faceState?.status === 'failed' ? `Detection failed${faceState.error_type ? ` (${faceState.error_type})` : ''}.` : faceState?.status === 'disabled' ? 'Detection is disabled; no result is available.' : 'Detection has not completed; no result is available.'}</p>}
                  </div>
                  {intelligence.media.type === 'video' && intelligence.shots.length > 0 && <div className="text-[11px] text-zinc-400">{intelligence.shots.map(s => `Shot ${s.shot_index + 1}: ${s.start.toFixed(1)}–${s.end.toFixed(1)}s${s.is_synthetic ? ' (synthetic)' : ''}`).join(' · ')}</div>}
                  {intelligence.media.type === 'image' && <div className="text-xs text-zinc-500">Object detection evidence: {intelligence.objects_evidence}. {intelligence.stored_tags.length ? `Stored tags: ${intelligence.stored_tags.join(', ')}` : 'No stored tags.'}</div>}
                  {intelligence.media.fingerprints.length > 0 && <div className="text-[11px] text-zinc-400 break-all"><div>Indexed source paths</div>{intelligence.media.fingerprints.map((f, index) => <div key={`${f.source_name}-${f.relative_path}-${index}`}>{f.source_name}/{f.relative_path} · {new Intl.NumberFormat().format(f.size_bytes)} bytes · {formatDate(f.filesystem_mtime)}</div>)}</div>}
                  {intelligence.media.type === 'image' && <div>
                    <h3 className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">AI Description</h3>
                    {imageCaptions.length === 0 ? (
                      <p className="text-xs text-zinc-500">No AI description generated yet.</p>
                    ) : (
                      <div className="space-y-2">
                        {imageCaptions.map(caption => (
                          <article key={JSON.stringify([caption.model_id, caption.prompt_version])} className="rounded-lg bg-slate-50 dark:bg-zinc-800/60 px-3 py-2 min-w-0">
                            <p className="text-sm leading-relaxed whitespace-pre-wrap break-words text-zinc-700 dark:text-zinc-200">{caption.caption}</p>
                            <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-[11px]">
                              <dt className="text-zinc-500">Model</dt>
                              <dd className="min-w-0 break-all text-right text-zinc-600 dark:text-zinc-300">{caption.model_id}</dd>
                              <dt className="text-zinc-500">Prompt version</dt>
                              <dd className="min-w-0 break-all text-right text-zinc-600 dark:text-zinc-300">{caption.prompt_version}</dd>
                              <dt className="text-zinc-500">Generated</dt>
                              <dd className="text-right text-zinc-600 dark:text-zinc-300">{formatDate(caption.generated_at_utc)}</dd>
                              <dt className="text-zinc-500">Status</dt>
                              <dd className="text-right text-zinc-600 dark:text-zinc-300">{caption.status}</dd>
                            </dl>
                          </article>
                        ))}
                      </div>
                    )}
                  </div>}
                  <div>
                    <h3 className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Visual descriptions</h3>
                    {imageCaptions.length === 0 && <p className="text-xs text-zinc-500">Image caption: {intelligence.descriptions.image_caption.status === 'not_generated' ? 'not generated yet.' : intelligence.descriptions.image_caption.text ?? intelligence.descriptions.image_caption.status}</p>}
                    {intelligence.media.type === 'video' && <p className="text-xs text-zinc-500">Video summary: {intelligence.descriptions.video_summary.status === 'not_generated' ? 'not generated yet.' : intelligence.descriptions.video_summary.text ?? intelligence.descriptions.video_summary.status}</p>}
                    {intelligence.descriptions.scenes.map((scene, index) => <p key={index} className="text-xs text-zinc-500">Scene {index + 1} · {scene.start.toFixed(1)}–{scene.end.toFixed(1)}s: {scene.text ?? scene.status}</p>)}
                  </div>
                  <div>
                    <h3 className="text-xs font-medium text-zinc-600 dark:text-zinc-300 mb-1">Transcript · {intelligence.transcript.status}</h3>
                    {(intelligence.transcript.model_name || intelligence.transcript.language || intelligence.transcript.error_code) && <p className="mb-1 text-[11px] text-zinc-400">{[intelligence.transcript.model_name, intelligence.transcript.language, intelligence.transcript.error_code].filter(Boolean).join(' · ')}</p>}
                    {intelligence.transcript.segments.length ? <div className="max-h-48 overflow-y-auto space-y-1">{intelligence.transcript.segments.map(segment => <p key={segment.id} className="text-xs text-zinc-600 dark:text-zinc-300"><span className="text-zinc-400 tabular-nums">{segment.start.toFixed(1)}s </span>{segment.text}</p>)}</div> : <p className="text-xs text-zinc-500">No transcript segments stored.</p>}
                    {intelligence.transcript.total_segments > intelligence.transcript.segments.length && <p className="text-[11px] text-zinc-400">Showing {intelligence.transcript.segments.length} of {intelligence.transcript.total_segments} segments.</p>}
                  </div>
                </>}
              </section>

              {/* Faces */}
              {intelligence && intelligence.faces.length > 0 && (
                <div>
                  <div className="text-xs text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-2">People</div>
                  <FaceStrip faces={intelligence.faces.map(face => ({
                    face_id: face.face_id,
                    bbox: face.bbox as [number, number, number, number],
                    confidence: face.confidence ?? 0,
                    person_id: face.person_id,
                    person_name: face.person_name,
                    gender: face.gender,
                    age: face.age,
                    shot_index: face.shot_index,
                    kf_index: face.kf_index,
                  }))} />
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Image lightbox — sibling of drawer so CSS transform doesn't trap fixed positioning */}
      {imgLightbox && item?.type !== 'video' && (
        <div
          className="fixed inset-0 z-[60] bg-black/90 flex items-center justify-center cursor-zoom-out"
          onClick={() => setImgLightbox(false)}
        >
          <img
            src={imageUrl(item!.id)}
            alt=""
            className="max-w-full max-h-full object-contain select-none"
            onClick={e => e.stopPropagation()}
          />
          <button
            onClick={() => setImgLightbox(false)}
            className="absolute top-4 right-4 p-2 rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors"
          >
            <X size={20} />
          </button>
        </div>
      )}
    </>
  )
}
