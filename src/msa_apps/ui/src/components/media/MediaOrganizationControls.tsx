import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { addMediaToCollection, getCollections, getUserMediaTags, setUserMediaTags } from '../../api/organization'

export function MediaOrganizationControls({ mediaId }: { mediaId: string }) {
  const queryClient = useQueryClient()
  const tags = useQuery({ queryKey: ['media-tags', mediaId], queryFn: () => getUserMediaTags(mediaId) })
  const collections = useQuery({ queryKey: ['collections'], queryFn: getCollections })
  const [draft, setDraft] = useState('')
  const [collectionId, setCollectionId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const tagText = tags.data?.tags?.join(', ') ?? ''
  useEffect(() => setDraft(tagText), [tagText])

  const saveTags = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await setUserMediaTags(mediaId, draft.split(',').map(tag => tag.trim()).filter(Boolean))
      queryClient.setQueryData(['media-tags', mediaId], result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save tags')
    } finally {
      setBusy(false)
    }
  }

  const addToCollection = async () => {
    if (!collectionId) return
    setBusy(true)
    setError(null)
    try {
      await addMediaToCollection(collectionId, [mediaId])
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
      await queryClient.invalidateQueries({ queryKey: ['collection-items', collectionId] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add to collection')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Organization" className="border-t border-slate-200 dark:border-zinc-800 pt-4 space-y-3">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Your organization</h2>
      <div>
        <label htmlFor="user-tags" className="block text-xs text-zinc-500 mb-1">Your tags (comma-separated)</label>
        <div className="flex gap-2">
          <input id="user-tags" value={draft} onChange={e => setDraft(e.target.value)} maxLength={5000}
            className="min-w-0 flex-1 rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1 text-sm"
            placeholder="family, vacation" />
          <button type="button" onClick={saveTags} disabled={busy || tags.isLoading}
            className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50">Save</button>
        </div>
        {tags.isLoading && <p className="mt-1 text-xs text-zinc-500">Loading tags…</p>}
      </div>
      <div>
        <label htmlFor="collection-select" className="block text-xs text-zinc-500 mb-1">Add to collection</label>
        <div className="flex gap-2">
          <select id="collection-select" value={collectionId} onChange={e => setCollectionId(e.target.value)}
            className="min-w-0 flex-1 rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1 text-sm">
            <option value="">Choose a collection</option>
            {(collections.data?.items ?? []).map(collection => <option key={collection.collection_id} value={collection.collection_id}>{collection.name}</option>)}
          </select>
          <button type="button" onClick={addToCollection} disabled={busy || !collectionId}
            className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50">Add</button>
        </div>
        <Link to="/collections" className="mt-1 inline-block text-xs text-indigo-600 hover:underline dark:text-indigo-300">Manage collections</Link>
      </div>
      {error && <p role="alert" className="text-xs text-rose-600">{error}</p>}
    </section>
  )
}
