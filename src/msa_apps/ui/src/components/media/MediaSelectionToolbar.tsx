import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { addMediaToCollection, createCollection, getCollections } from '../../api/organization'

interface MediaSelectionToolbarProps {
  active: boolean
  selectedIds: string[]
  onStart: () => void
  onCancel: () => void
}

export function MediaSelectionToolbar({ active, selectedIds, onStart, onCancel }: MediaSelectionToolbarProps) {
  const queryClient = useQueryClient()
  const [showCollectionForm, setShowCollectionForm] = useState(false)
  const [collectionId, setCollectionId] = useState('')
  const [newCollectionName, setNewCollectionName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: getCollections,
    enabled: active && showCollectionForm,
  })

  const openSelection = () => {
    setSuccess(null)
    onStart()
  }

  const finish = (message: string) => {
    setSuccess(message)
    setShowCollectionForm(false)
    setError(null)
    onCancel()
  }

  const invalidateCollections = async (id: string) => {
    await queryClient.invalidateQueries({ queryKey: ['collections'] })
    await queryClient.invalidateQueries({ queryKey: ['collection-items', id] })
  }

  const addToExisting = async () => {
    const collection = collections.data?.items.find(item => item.collection_id === collectionId)
    if (!collection || selectedIds.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const result = await addMediaToCollection(collectionId, selectedIds)
      await invalidateCollections(collectionId)
      finish(`Added ${result.added} of ${selectedIds.length} selected assets to “${collection.name}”.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add selected media')
    } finally {
      setBusy(false)
    }
  }

  const createAndAdd = async () => {
    const name = newCollectionName.trim()
    if (!name || selectedIds.length === 0) return
    setBusy(true)
    setError(null)
    let createdId: string | null = null
    try {
      const collection = await createCollection(name)
      createdId = collection.collection_id
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
      setCollectionId(createdId)
      setNewCollectionName('')
      const result = await addMediaToCollection(createdId, selectedIds)
      await invalidateCollections(createdId)
      finish(`Added ${result.added} of ${selectedIds.length} selected assets to “${collection.name}”.`)
    } catch (err) {
      setError(createdId
        ? `Collection created, but adding the selected assets failed. Choose it above and retry.`
        : err instanceof Error ? err.message : 'Could not create collection')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      {!active ? (
        <button type="button" onClick={openSelection} className="rounded border border-slate-300 dark:border-zinc-700 px-3 py-1.5 text-xs font-medium hover:bg-slate-100 dark:hover:bg-zinc-800">
          Select assets
        </button>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 dark:border-indigo-900 bg-indigo-50/70 dark:bg-indigo-950/30 px-3 py-2">
            <span aria-live="polite" className="mr-auto text-sm font-medium text-indigo-900 dark:text-indigo-100">
              {selectedIds.length} {selectedIds.length === 1 ? 'asset' : 'assets'} selected
            </span>
            {selectedIds.length > 0 && <button type="button" onClick={() => { setShowCollectionForm(value => !value); setError(null) }} className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500">
              Add to collection
            </button>}
            <button type="button" onClick={() => { setShowCollectionForm(false); setError(null); onCancel() }} className="rounded px-3 py-1.5 text-xs text-zinc-600 hover:bg-white dark:text-zinc-300 dark:hover:bg-zinc-800">
              Cancel selection
            </button>
          </div>
          {showCollectionForm && <section aria-label="Add selected assets to a collection" className="grid gap-3 rounded-lg border border-slate-200 dark:border-zinc-800 p-3 sm:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="existing-collection" className="block text-xs text-zinc-500">Existing collection</label>
              <select id="existing-collection" value={collectionId} onChange={event => setCollectionId(event.target.value)} disabled={busy} className="w-full rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1.5 text-sm">
                <option value="">Choose a collection</option>
                {(collections.data?.items ?? []).map(collection => <option key={collection.collection_id} value={collection.collection_id}>{collection.name}</option>)}
              </select>
              <button type="button" onClick={() => void addToExisting()} disabled={busy || !collectionId} className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
                Add selected assets
              </button>
            </div>
            <div className="space-y-2">
              <label htmlFor="new-collection-name" className="block text-xs text-zinc-500">New collection</label>
              <input id="new-collection-name" value={newCollectionName} onChange={event => setNewCollectionName(event.target.value)} maxLength={100} placeholder="Collection name" disabled={busy} className="w-full rounded border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1.5 text-sm" />
              <button type="button" onClick={() => void createAndAdd()} disabled={busy || !newCollectionName.trim()} className="rounded border border-indigo-300 dark:border-indigo-800 px-3 py-1.5 text-xs font-medium text-indigo-700 dark:text-indigo-300 disabled:opacity-50">
                Create and add selected
              </button>
            </div>
            {collections.isLoading && <p className="text-xs text-zinc-500 sm:col-span-2">Loading collections…</p>}
            {collections.error && <p role="alert" className="text-xs text-rose-600 sm:col-span-2">Existing collections unavailable. You can still create a new collection.</p>}
          </section>}
        </>
      )}
      {error && <p role="alert" className="text-xs text-rose-600">{error}</p>}
      {success && <p role="status" className="text-xs text-emerald-700 dark:text-emerald-300">{success}</p>}
    </div>
  )
}
