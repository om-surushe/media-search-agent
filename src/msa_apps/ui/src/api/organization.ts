import { apiUrl } from '../lib/apiBase'

export interface UserMediaTags {
  media_id: string
  tags: string[]
}

export interface MediaCollection {
  collection_id: string
  name: string
  description: string
  created_at: string
  media_count?: number
}

export interface CollectionItem {
  id: string
  type: string | null
  date: string | null
  duration: number | null
  added_at: string
}

export interface CollectionPage {
  items: CollectionItem[]
  count: number
  limit: number
  offset: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), init)
  if (!res.ok) throw new Error(`Organization request failed: ${res.status}`)
  if (res.status === 204) return undefined as T
  return res.json()
}

export async function getUserTags(): Promise<string[]> {
  const tags = await request<unknown>('/user-tags')
  return Array.isArray(tags) ? tags.filter((tag): tag is string => typeof tag === 'string') : []
}

export function getUserMediaTags(mediaId: string): Promise<UserMediaTags> {
  return request(`/media/${encodeURIComponent(mediaId)}/tags`)
}

export function setUserMediaTags(mediaId: string, tags: string[]): Promise<UserMediaTags> {
  return request(`/media/${encodeURIComponent(mediaId)}/tags`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tags }),
  })
}

export function getCollections(): Promise<{ items: MediaCollection[]; count: number }> {
  return request('/collections?limit=100&offset=0')
}

export function createCollection(name: string, description = ''): Promise<MediaCollection> {
  return request('/collections', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, description }),
  })
}

export function getCollectionItems(collectionId: string, limit = 100, offset = 0): Promise<CollectionPage> {
  return request(`/collections/${encodeURIComponent(collectionId)}/items?limit=${limit}&offset=${offset}`)
}

export function addMediaToCollection(collectionId: string, mediaIds: string[]): Promise<{ added: number }> {
  return request(`/collections/${encodeURIComponent(collectionId)}/items`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ media_ids: mediaIds }),
  })
}

export function removeMediaFromCollection(collectionId: string, mediaId: string): Promise<void> {
  return request(`/collections/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(mediaId)}`, { method: 'DELETE' })
}

export function deleteCollection(collectionId: string): Promise<void> {
  return request(`/collections/${encodeURIComponent(collectionId)}`, { method: 'DELETE' })
}
