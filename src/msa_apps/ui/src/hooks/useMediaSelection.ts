import { useCallback, useState } from 'react'

export function useMediaSelection() {
  const [active, setActive] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  const start = useCallback(() => setActive(true), [])
  const toggle = useCallback((id: string) => {
    setSelectedIds(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id])
  }, [])
  const clear = useCallback(() => {
    setSelectedIds([])
    setActive(false)
  }, [])

  return { active, selectedIds, start, toggle, clear }
}
