import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MediaOrganizationControls } from './MediaOrganizationControls'

beforeEach(() => {
  const tags = ['Family']
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/media/asset-1/tags')) {
      if (init?.method === 'PUT') {
        tags.splice(0, tags.length, ...JSON.parse(String(init.body)).tags)
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ media_id: 'asset-1', tags: [...tags] }) })
    }
    if (url.includes('/collections?')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [{ collection_id: 'c1', name: 'Trip' }], count: 1 }) })
    }
    if (url.endsWith('/collections/c1/items') && init?.method === 'POST') {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ added: 1 }) })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) })
  }))
})
afterEach(() => vi.unstubAllGlobals())

describe('MediaOrganizationControls', () => {
  it('saves user tags and adds the asset to a selected collection', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><MediaOrganizationControls mediaId="asset-1" /></MemoryRouter></QueryClientProvider>)

    const tagInput = await screen.findByLabelText(/Your tags/)
    await waitFor(() => expect(tagInput).toHaveValue('Family'))
    fireEvent.change(tagInput, { target: { value: 'Family, Trip' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/media/asset-1/tags'), expect.objectContaining({ method: 'PUT' })))

    await screen.findByRole('option', { name: 'Trip' })
    fireEvent.change(await screen.findByLabelText('Add to collection'), { target: { value: 'c1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/collections/c1/items'), expect.objectContaining({ method: 'POST' })))
  })
})
