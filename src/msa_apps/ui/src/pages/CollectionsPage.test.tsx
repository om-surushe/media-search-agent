import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { CollectionsPage } from './CollectionsPage'

function renderPage(initialPath = '/collections') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[initialPath]}><Routes>
    <Route path="/collections" element={<CollectionsPage />} />
    <Route path="/collections/:collectionId" element={<CollectionsPage />} />
  </Routes></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => {
  let created = false
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/collections?')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
        items: created ? [{ collection_id: 'collection-1', name: 'Trip', description: '', created_at: '', media_count: 0 }] : [], count: Number(created),
      }) })
    }
    if (url.endsWith('/collections') && init?.method === 'POST') {
      created = true
      return Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve({ collection_id: 'collection-1', name: 'Trip', description: '' }) })
    }
    if (url.includes('/collections/collection-1/items?')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [], count: 0, limit: 50, offset: 0 }) })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }))
})
afterEach(() => vi.unstubAllGlobals())

describe('CollectionsPage', () => {
  it('creates and opens a persistent virtual collection', async () => {
    renderPage()
    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Trip' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create collection' }))
    expect(await screen.findByRole('heading', { name: 'Trip' })).toBeInTheDocument()
    expect(await screen.findByText(/This collection is empty/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /back to collections/i }))
    expect(await screen.findByRole('button', { name: 'Open collection Trip' })).toBeInTheDocument()
  })

  it('shows a media grid, opens photo and video previews, and removes only collection membership', async () => {
    let items = [
      { id: 'photo-1', type: 'image', date: '2024-03-15', duration: null, added_at: '' },
      { id: 'video-1', type: 'video', date: '2024-03-16', duration: 30, added_at: '' },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/collections?')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
          items: [{ collection_id: 'collection-1', name: 'Trip', description: 'Coast', created_at: '', media_count: items.length }], count: 1,
        }) })
      }
      if (url.includes('/collections/collection-1/items?')) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items, count: items.length, limit: 50, offset: 0 }) })
      }
      if (url.endsWith('/collections/collection-1/items/photo-1') && init?.method === 'DELETE') {
        items = items.filter(item => item.id !== 'photo-1')
        return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve({}) })
      }
      if (url.endsWith('/intelligence')) return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) })
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
    })
    vi.stubGlobal('fetch', fetchMock)
    const { container } = renderPage('/collections/collection-1')

    expect(await screen.findByRole('heading', { name: 'Trip' })).toBeInTheDocument()
    expect(await screen.findByText('2 assets')).toBeInTheDocument()
    await waitFor(() => expect(container.querySelectorAll('button.group')).toHaveLength(2))
    expect(container.querySelector('img[src="/thumbnails/photo-1.jpg"]')).toBeInTheDocument()
    expect(container.querySelector('img[src="/thumbnails/video-1.jpg"]')).toBeInTheDocument()

    const cards = container.querySelectorAll('button.group')
    fireEvent.click(cards[0])
    expect(await screen.findByText('photo-1')).toBeInTheDocument()
    expect(container.querySelector('img[src="/images/photo-1"]')).toBeInTheDocument()
    fireEvent.click(cards[1])
    await waitFor(() => expect(container.querySelector('video[src="/videos/video-1"]')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Remove photo-1 from collection' }))
    expect(await screen.findByText('1 asset')).toBeInTheDocument()
    await waitFor(() => expect(container.querySelectorAll('button.group')).toHaveLength(1))
    expect(fetchMock).toHaveBeenCalledWith('/collections/collection-1/items/photo-1', { method: 'DELETE' })
    expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/media/photo-1') && init?.method === 'DELETE')).toBe(false)
  })
})
