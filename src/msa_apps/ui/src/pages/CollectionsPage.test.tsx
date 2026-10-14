import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { CollectionsPage } from './CollectionsPage'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><MemoryRouter><CollectionsPage /></MemoryRouter></QueryClientProvider>)
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
  })
})
