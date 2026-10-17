import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MediaSelectionToolbar } from './MediaSelectionToolbar'

function renderToolbar(onCancel = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    onCancel,
    ...render(<QueryClientProvider client={queryClient}>
      <MediaSelectionToolbar active selectedIds={['image-1', 'video-1']} onStart={vi.fn()} onCancel={onCancel} />
    </QueryClientProvider>),
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/collections?')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
        items: [{ collection_id: 'col-trip', name: 'Trip', description: '', created_at: '' }], count: 1,
      }) })
    }
    if (url.endsWith('/collections/col-trip/items') && init?.method === 'POST') {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ added: 2 }) })
    }
    if (url.endsWith('/collections') && init?.method === 'POST') {
      return Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve({ collection_id: 'col-new', name: 'New Trip', description: '' }) })
    }
    if (url.endsWith('/collections/col-new/items') && init?.method === 'POST') {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ added: 2 }) })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [], count: 0 }) })
  }))
})
afterEach(() => vi.unstubAllGlobals())

describe('MediaSelectionToolbar', () => {
  it('adds the selected assets to an existing collection, confirms, and clears selection', async () => {
    const { onCancel } = renderToolbar()
    fireEvent.click(screen.getByRole('button', { name: 'Add to collection' }))
    await screen.findByRole('option', { name: 'Trip' })
    await userEvent.selectOptions(screen.getByLabelText('Existing collection'), 'col-trip')
    fireEvent.click(screen.getByRole('button', { name: 'Add selected assets' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Added 2 of 2 selected assets to “Trip”.')
    await waitFor(() => expect(onCancel).toHaveBeenCalledOnce())
    expect(fetch).toHaveBeenCalledWith('/collections/col-trip/items', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ media_ids: ['image-1', 'video-1'] }),
    }))
  })

  it('creates a new collection and adds all selected assets', async () => {
    const { onCancel } = renderToolbar()
    fireEvent.click(screen.getByRole('button', { name: 'Add to collection' }))
    fireEvent.change(screen.getByLabelText('New collection'), { target: { value: 'New Trip' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create and add selected' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Added 2 of 2 selected assets to “New Trip”.')
    expect(fetch).toHaveBeenCalledWith('/collections', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ name: 'New Trip', description: '' }),
    }))
    expect(fetch).toHaveBeenCalledWith('/collections/col-new/items', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ media_ids: ['image-1', 'video-1'] }),
    }))
    await waitFor(() => expect(onCancel).toHaveBeenCalledOnce())
  })
})
