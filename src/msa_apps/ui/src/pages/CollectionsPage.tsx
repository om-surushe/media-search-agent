import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createCollection, deleteCollection, getCollectionItems, getCollections, removeMediaFromCollection } from '../api/organization'
import { thumbnailUrl } from '../api/media'
import { MediaDetailDrawer } from '../components/media/MediaDetailDrawer'

export function CollectionsPage() {
  const queryClient = useQueryClient()
  const collections = useQuery({ queryKey: ['collections'], queryFn: getCollections })
  const [selectedId, setSelectedId] = useState('')
  const [offset, setOffset] = useState(0)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [activeItem, setActiveItem] = useState<{ id: string; type: 'image' | 'video' | null; date?: string | null } | null>(null)
  const selected = collections.data?.items.find(item => item.collection_id === selectedId)
  const page = useQuery({
    queryKey: ['collection-items', selectedId, offset],
    queryFn: () => getCollectionItems(selectedId, 50, offset),
    enabled: !!selectedId,
  })

  useEffect(() => setOffset(0), [selectedId])

  const create = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      const collection = await createCollection(name, description)
      setName('')
      setDescription('')
      setSelectedId(collection.collection_id)
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create collection')
    }
  }

  const remove = async (mediaId: string) => {
    if (!selectedId) return
    setError(null)
    try {
      await removeMediaFromCollection(selectedId, mediaId)
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
      await queryClient.invalidateQueries({ queryKey: ['collection-items', selectedId] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove media')
    }
  }

  const removeCollection = async () => {
    if (!selected || !window.confirm(`Delete collection “${selected.name}”? Media files will not be changed.`)) return
    setError(null)
    try {
      await deleteCollection(selected.collection_id)
      setSelectedId('')
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete collection')
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Collections</h1>
        <p className="mt-1 text-sm text-zinc-500">Virtual albums store media IDs only. Originals are never moved or copied.</p>
      </header>

      <form onSubmit={create} className="grid gap-3 rounded-lg border border-slate-200 dark:border-zinc-800 p-4 sm:grid-cols-[1fr_2fr_auto]">
        <label className="text-xs text-zinc-500">Name
          <input required maxLength={100} value={name} onChange={e => setName(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1.5 text-sm text-zinc-900 dark:text-zinc-100" />
        </label>
        <label className="text-xs text-zinc-500">Description
          <input maxLength={1000} value={description} onChange={e => setDescription(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1.5 text-sm text-zinc-900 dark:text-zinc-100" />
        </label>
        <button className="self-end rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">Create collection</button>
      </form>

      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
      {collections.isLoading && <p className="text-sm text-zinc-500">Loading collections…</p>}
      {collections.error && <p role="alert" className="text-sm text-rose-600">Collections unavailable.</p>}
      {!collections.isLoading && !collections.error && collections.data?.items.length === 0 && <p className="text-sm text-zinc-500">No collections yet. Open an asset to add it to a collection.</p>}

      {collections.data && collections.data.items.length > 0 && (
        <div className="grid gap-5 md:grid-cols-[16rem_minmax(0,1fr)]">
          <nav aria-label="Saved collections" className="space-y-1">
            {collections.data.items.map(collection => (
              <button key={collection.collection_id} type="button" onClick={() => setSelectedId(collection.collection_id)}
                aria-current={selectedId === collection.collection_id ? 'true' : undefined}
                className={`block w-full rounded-md px-3 py-2 text-left ${selectedId === collection.collection_id ? 'bg-indigo-100 text-indigo-900 dark:bg-indigo-950 dark:text-indigo-100' : 'hover:bg-slate-100 dark:hover:bg-zinc-800'}`}>
                <span className="block text-sm font-medium">{collection.name}</span>
                <span className="text-xs text-zinc-500">{collection.media_count ?? 0} items</span>
              </button>
            ))}
          </nav>

          <section aria-label="Collection contents" className="min-w-0 rounded-lg border border-slate-200 dark:border-zinc-800 p-4">
            {selected ? <>
              <div className="mb-4 flex items-start justify-between gap-4">
                <div><h2 className="text-lg font-semibold">{selected.name}</h2><p className="text-sm text-zinc-500">{selected.description}</p></div>
                <button type="button" onClick={removeCollection} className="text-xs text-rose-600 hover:underline">Delete collection</button>
              </div>
              {page.isLoading && <p className="text-sm text-zinc-500">Loading items…</p>}
              {page.error && <p role="alert" className="text-sm text-rose-600">Collection items unavailable.</p>}
              {page.data?.items.length === 0 && <p className="text-sm text-zinc-500">This collection is empty. Add media from its asset inspector.</p>}
              <div className="divide-y divide-slate-100 dark:divide-zinc-800">
                {page.data?.items.map(item => (
                  <div key={item.id} className="flex items-center gap-3 py-2">
                    <img src={thumbnailUrl(item.id) ?? undefined} alt="" className="h-12 w-16 rounded bg-slate-100 object-cover dark:bg-zinc-800" onError={e => { e.currentTarget.hidden = true }} />
                    <button type="button" onClick={() => setActiveItem({ id: item.id, type: item.type === 'image' || item.type === 'video' ? item.type : null, date: item.date })}
                      className="min-w-0 flex-1 truncate text-left text-xs font-mono text-indigo-700 hover:underline dark:text-indigo-300">{item.id}</button>
                    <span className="text-xs text-zinc-500">{item.date ? new Date(item.date).toLocaleDateString() : item.type ?? 'media'}</span>
                    <button type="button" aria-label={`Remove ${item.id} from collection`} onClick={() => remove(item.id)} className="text-xs text-rose-600 hover:underline">Remove</button>
                  </div>
                ))}
              </div>
              {page.data && page.data.count > 50 && <div className="mt-3 flex justify-between text-xs">
                <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))} className="disabled:opacity-40">Previous</button>
                <span>{offset + 1}–{Math.min(offset + page.data.items.length, page.data.count)} of {page.data.count}</span>
                <button disabled={offset + page.data.items.length >= page.data.count} onClick={() => setOffset(offset + 50)} className="disabled:opacity-40">Next</button>
              </div>}
            </> : <p className="text-sm text-zinc-500">Select a collection.</p>}
          </section>
        </div>
      )}
      <MediaDetailDrawer item={activeItem} onClose={() => setActiveItem(null)} />
    </div>
  )
}
