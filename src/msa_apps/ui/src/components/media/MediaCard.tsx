import { Film } from 'lucide-react'
import { thumbnailUrl } from '../../api/media'
import { FaceStrip } from './FaceStrip'
import type { FaceOnMedia, VideoSceneSearchMatch } from '../../api/types'
import { cn } from '../../lib/utils'

interface MediaCardProps {
  id: string | null | undefined
  path?: string | null
  type?: 'image' | 'video' | null
  date?: string | null
  place?: string | null
  captionExcerpt?: string | null
  sceneMatches?: VideoSceneSearchMatch[] | null
  duration?: number | null
  faces?: FaceOnMedia[]
  selectionEnabled?: boolean
  selected?: boolean
  onSelect?: () => void
  onClick: () => void
}

function formatDuration(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}

export function MediaCard({ id, path: _path, type, date, place, captionExcerpt, sceneMatches, duration, faces, selectionEnabled, selected, onSelect, onClick }: MediaCardProps) {
  const thumb = thumbnailUrl(id)
  return (
    <div className={cn('relative rounded-lg', selected && 'ring-2 ring-indigo-500')}>
      <button
        onClick={onClick}
        className={cn(
          'group relative flex w-full flex-col bg-slate-100 dark:bg-zinc-800 rounded-lg overflow-hidden',
          'ring-1 ring-slate-200 dark:ring-zinc-700 hover:ring-indigo-500 transition-all text-left',
        )}
      >
        {/* Thumbnail */}
        <div className="relative aspect-square bg-slate-200 dark:bg-zinc-900 overflow-hidden">
          {thumb && (
            <img
              src={thumb}
              alt=""
              loading="lazy"
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
              onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
            />
          )}
          {/* Video badge */}
          {type === 'video' && (
            <div className="absolute top-1.5 left-1.5 flex items-center gap-1 bg-black/70 rounded px-1.5 py-0.5 text-xs text-white">
              <Film size={10} />
              {duration != null ? formatDuration(duration) : 'video'}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-2 py-1.5 flex flex-col gap-1 min-h-[3rem]">
          {sceneMatches?.length ? (
            <div className="space-y-0.5 text-xs text-indigo-700 dark:text-indigo-300">
              {sceneMatches.slice(0, 3).map(match => (
                <div key={`${match.keyframe_id}-${match.timestamp}`} className="truncate" title={`${match.timestamp.toFixed(1)}s · ${match.caption_excerpt}`}>
                  <span className="font-semibold">{match.timestamp.toFixed(1)}s ·</span> {match.caption_excerpt}
                </div>
              ))}
            </div>
          ) : captionExcerpt && (
            <div className="text-xs text-indigo-700 dark:text-indigo-300 truncate" title={captionExcerpt}>
              <span className="font-semibold">Caption match:</span> {captionExcerpt}
            </div>
          )}
          {(date || place) && (
            <div className="text-xs text-zinc-500 dark:text-zinc-400 truncate">
              {place ?? formatDate(date)}
            </div>
          )}
          {faces && faces.length > 0 && <FaceStrip faces={faces} />}
        </div>
      </button>
      {selectionEnabled && id && onSelect && (
        <label className="absolute top-2 right-2 z-10 flex h-8 w-8 cursor-pointer items-center justify-center rounded-md bg-white/95 shadow ring-1 ring-black/10 dark:bg-zinc-900/95 dark:ring-white/20">
          <input
            type="checkbox"
            checked={!!selected}
            onChange={onSelect}
            aria-label={`Select ${id}`}
            className="h-4 w-4 accent-indigo-600"
          />
        </label>
      )}
    </div>
  )
}
