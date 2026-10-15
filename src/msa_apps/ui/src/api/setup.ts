export type ModelState = 'pending' | 'downloading' | 'verifying' | 'done' | 'error'

export interface ModelInfo {
  id: string
  label: string
  size_mb: number
  present: boolean
  integrity_hint: string
  // Download origin host + path (e.g. "huggingface.co/PekingU/rtdetr_r18vd").
  // Shown on the first-launch setup page as a trust signal so users can see
  // bytes are coming from a known model host rather than a random URL.
  source: string
}

export interface SetupStatus {
  ready: boolean
  models: ModelInfo[]
  read_only_mode?: boolean
}

export interface ModelDownloadState {
  status: ModelState
  error: string | null
  downloaded_bytes?: number
  total_bytes?: number
  filename?: string | null
}

export interface CommercialModel {
  id: string
  task: string
  label: string
  publisher: string
  source: string
  revision: string | null
  license_claim: string
  license_evidence: string
  clearance: 'review_required' | 'conditional' | 'gated' | 'hosted_only'
  access_note: string | null
  downloadable: boolean
  installed: boolean
  path: string
  size_bytes: number
  min_ram_gb: number
  hardware_fit: boolean
  recommended_for_task: boolean
  adapter_status: string
  state: ModelDownloadState
}

export interface CommercialModelCatalog {
  hardware: {
    os: string
    architecture: string
    ram_gb: number | null
    cpu_count: number
    accelerator: string
    hardware_recommendations_are_advisory: true
  }
  models: CommercialModel[]
}

export interface SetupWSUpdate {
  type: 'update' | 'complete'
  models: Record<string, ModelDownloadState>
}

import { apiUrl } from '../lib/apiBase'

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const res = await fetch(apiUrl('/api/setup/status'))
  if (!res.ok) throw new Error(`setup/status ${res.status}`)
  return res.json()
}

/**
 * Re-trigger the first-launch model downloads (resets errored models and restarts the background
 * worker). The setup screen's Retry button calls this BEFORE reloading — a plain reload only
 * re-subscribes to the manager's held complete/error state and never restarts a failed download.
 */
export async function retrySetup(): Promise<void> {
  const res = await fetch(apiUrl('/api/setup/retry'), { method: 'POST' })
  if (!res.ok) throw new Error(`setup/retry ${res.status}`)
}

export async function fetchCommercialModelCatalog(): Promise<CommercialModelCatalog> {
  const res = await fetch(apiUrl('/api/models/catalog'))
  if (!res.ok) throw new Error(`models/catalog ${res.status}`)
  return res.json()
}

export async function downloadCommercialModel(modelId: string): Promise<void> {
  const res = await fetch(apiUrl(`/api/models/${encodeURIComponent(modelId)}/download`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_experimental: true }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? `models/${modelId}/download ${res.status}`)
  }
}

export async function retryCaptioningSetup(): Promise<void> {
  const res = await fetch(apiUrl('/api/setup/captioning/retry'), { method: 'POST' })
  if (!res.ok) throw new Error(`setup/captioning/retry ${res.status}`)
}
