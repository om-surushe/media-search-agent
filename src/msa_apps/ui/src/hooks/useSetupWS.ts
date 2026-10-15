import { useState, useEffect } from 'react'
import type { ModelDownloadState, SetupWSUpdate } from '../api/setup'
import { wsUrl } from '../lib/apiBase'

export interface SetupWSState {
  models: Record<string, ModelDownloadState> | null
  complete: boolean
  revision: number
}

/**
 * Connects to /ws/setup and streams per-model download progress.
 * Reconnects automatically on disconnect (while complete is false).
 */
export function useSetupWS(reconnectKey = 0): SetupWSState {
  const [state, setState] = useState<SetupWSState>({ models: null, complete: false, revision: 0 })

  useEffect(() => {
    let closed = false
    let ws: WebSocket | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    function connect() {
      if (closed) return
      ws = new WebSocket(wsUrl('/ws/setup'))

      ws.onmessage = (e) => {
        try {
          const msg: SetupWSUpdate = JSON.parse(e.data)
          setState((prev) => ({ models: msg.models, complete: msg.type === 'complete', revision: prev.revision + 1 }))
        } catch {}
      }

      ws.onclose = () => {
        // Clear any existing timer before scheduling a new one — rapid flaps
        // (e.g. server restart) would otherwise stack timers and spawn multiple
        // concurrent WebSocket connections.
        if (retryTimer) clearTimeout(retryTimer)
        // Reconnect only if setup is not yet complete
        if (!closed) {
          retryTimer = setTimeout(() => {
            setState((prev) => {
              if (prev.complete) return prev  // already done, stop reconnecting
              connect()
              return prev
            })
          }, 3000)
        }
      }
    }

    connect()

    return () => {
      closed = true
      if (retryTimer) clearTimeout(retryTimer)
      ws?.close()
    }
  }, [reconnectKey])

  return state
}
