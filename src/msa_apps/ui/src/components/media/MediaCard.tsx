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
  onClick: () => void
}

function formatVideoTime(s: number): string {
  const totalSeconds = Math.floor(Math.max(0, s))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return hours > 0
    ? `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    : `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}

export function MediaCard({ id, path: _path, type, date, place, captionExcerpt, sceneMatches, duration, faces, onClick }: MediaCardProps) {
  const thumb = thumbnailUrl(id)
  return (
    <button
      onClick={onClick}
      className={cn(
        'group relative flex flex-col bg-slate-100 dark:bg-zinc-800 rounded-lg overflow-hidden',
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
            <span>VIDEO</span>
            {duration != null && <span>· {formatVideoTime(duration)}</span>}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-2 py-1.5 flex flex-col gap-1 min-h-[3rem]">
        {type === 'video' && sceneMatches?.length ? (
          <div className="space-y-0.5 text-xs text-indigo-700 dark:text-indigo-300">
            {sceneMatches.slice(0, 3).map(match => (
              <div key={`${match.keyframe_id}-${match.timestamp}`} className="truncate" title={`${formatVideoTime(match.timestamp)} · ${match.caption_excerpt}`}>
                <span className="font-semibold">{formatVideoTime(match.timestamp)} ·</span> {match.caption_excerpt}
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
  )
}
