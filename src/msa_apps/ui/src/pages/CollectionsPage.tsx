import { useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createCollection, deleteCollection, getCollectionItems, getCollections, removeMediaFromCollection } from '../api/organization'
import { MediaCard } from '../components/media/MediaCard'
import { MediaDetailDrawer } from '../components/media/MediaDetailDrawer'

const PAGE_SIZE = 50

type InspectorItem = { id: string; type: 'image' | 'video' | null; date?: string | null }

export function CollectionsPage() {
  const { collectionId } = useParams()
  return collectionId
    ? <CollectionDetailPage key={collectionId} collectionId={collectionId} />
    : <CollectionsListPage />
}

function CollectionsListPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const collections = useQuery({ queryKey: ['collections'], queryFn: getCollections })
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)

  const create = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      const collection = await createCollection(name, description)
      setName('')
      setDescription('')
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
      navigate(`/collections/${encodeURIComponent(collection.collection_id)}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create collection')
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
          <input required maxLength={100} value={name} onChange={event => setName(event.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1.5 text-sm text-zinc-900 dark:text-zinc-100" />
        </label>
        <label className="text-xs text-zinc-500">Description
          <input maxLength={1000} value={description} onChange={event => setDescription(event.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1.5 text-sm text-zinc-900 dark:text-zinc-100" />
        </label>
        <button className="self-end rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">Create collection</button>
      </form>

      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
      {collections.isLoading && <p className="text-sm text-zinc-500">Loading collections…</p>}
      {collections.error && <p role="alert" className="text-sm text-rose-600">Collections unavailable.</p>}
      {!collections.isLoading && !collections.error && collections.data?.items.length === 0 && <p className="text-sm text-zinc-500">No collections yet. Open an asset to add it to a collection.</p>}

      {collections.data && collections.data.items.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {collections.data.items.map(collection => (
            <button key={collection.collection_id} type="button"
              aria-label={`Open collection ${collection.name}`}
              onClick={() => navigate(`/collections/${encodeURIComponent(collection.collection_id)}`)}
              className="rounded-lg border border-slate-200 dark:border-zinc-800 p-4 text-left hover:border-indigo-400 hover:bg-slate-50 dark:hover:bg-zinc-800/60">
              <span className="block font-medium">{collection.name}</span>
              <span className="mt-1 block text-xs text-zinc-500">{collection.media_count ?? 0} assets</span>
              {collection.description && <span className="mt-2 block text-sm text-zinc-500 line-clamp-2">{collection.description}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function CollectionDetailPage({ collectionId }: { collectionId: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [offset, setOffset] = useState(0)
  const [activeItem, setActiveItem] = useState<InspectorItem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const collections = useQuery({ queryKey: ['collections'], queryFn: getCollections })
  const collection = collections.data?.items.find(item => item.collection_id === collectionId)
  const page = useQuery({
    queryKey: ['collection-items', collectionId, offset],
    queryFn: () => getCollectionItems(collectionId, PAGE_SIZE, offset),
  })
  const count = page.data?.count ?? collection?.media_count ?? 0

  const remove = async (mediaId: string) => {
    setError(null)
    try {
      await removeMediaFromCollection(collectionId, mediaId)
      if (offset > 0 && page.data?.items.length === 1 && page.data.count - 1 <= offset) {
        setOffset(Math.max(0, offset - PAGE_SIZE))
      }
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
      await queryClient.invalidateQueries({ queryKey: ['collection-items', collectionId] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove media from collection')
    }
  }

  const removeCollection = async () => {
    if (!collection || !window.confirm(`Delete collection “${collection.name}”? Media files will not be changed.`)) return
    setError(null)
    try {
      await deleteCollection(collectionId)
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
      navigate('/collections')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete collection')
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <header className="space-y-3">
        <button type="button" onClick={() => navigate('/collections')} className="text-sm text-indigo-600 hover:underline dark:text-indigo-300">
          ← Back to collections
        </button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{collection?.name ?? (collections.isLoading ? 'Loading collection…' : 'Collection not found')}</h1>
            {collection?.description && <p className="mt-1 text-sm text-zinc-500">{collection.description}</p>}
            <p className="mt-1 text-sm text-zinc-500">{count} {count === 1 ? 'asset' : 'assets'}</p>
          </div>
          {collection && <button type="button" onClick={() => void removeCollection()} className="text-xs text-rose-600 hover:underline">Delete collection</button>}
        </div>
      </header>

      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
      {collections.error && <p role="alert" className="text-sm text-rose-600">Collections unavailable.</p>}
      {!collections.isLoading && !collections.error && !collection && <p className="text-sm text-zinc-500">This collection may have been deleted. Return to the collections list.</p>}
      {collection && page.isLoading && <p className="text-sm text-zinc-500">Loading items…</p>}
      {collection && page.error && <p role="alert" className="text-sm text-rose-600">Collection items unavailable.</p>}
      {collection && page.data?.count === 0 && <p className="rounded-lg border border-dashed border-slate-300 dark:border-zinc-700 p-8 text-center text-sm text-zinc-500">This collection is empty. Add media from Search or Browse.</p>}
      {collection && page.data && page.data.count > 0 && page.data.items.length === 0 && <p className="text-sm text-zinc-500">No assets on this page.</p>}

      {collection && page.data && page.data.items.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {page.data.items.map(item => (
            <MediaCard key={item.id} id={item.id} type={item.type === 'image' || item.type === 'video' ? item.type : null}
              date={item.date} duration={item.duration}
              onClick={() => setActiveItem({ id: item.id, type: item.type === 'image' || item.type === 'video' ? item.type : null, date: item.date })}
              onRemove={() => void remove(item.id)} />
          ))}
        </div>
      )}

      {collection && page.data && page.data.count > PAGE_SIZE && (
        <nav aria-label="Collection pages" className="flex items-center justify-between text-xs">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="disabled:opacity-40">Previous</button>
          <span>{page.data.items.length ? `${offset + 1}–${Math.min(offset + page.data.items.length, page.data.count)} of ${page.data.count}` : `${page.data.count} assets`}</span>
          <button type="button" disabled={page.data.items.length === 0 || offset + page.data.items.length >= page.data.count}
            onClick={() => setOffset(offset + PAGE_SIZE)} className="disabled:opacity-40">Next</button>
        </nav>
      )}

      <MediaDetailDrawer item={activeItem} onClose={() => setActiveItem(null)} />
    </div>
  )
}
