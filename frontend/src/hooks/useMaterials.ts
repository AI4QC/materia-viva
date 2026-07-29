import { useCallback, useEffect, useMemo, useState } from 'react'

import { getStats, searchMaterials, type AtlasStats, type SearchResponse } from '../api/client'
import type { MaterialQuery } from '../lib/query'
import { serializeQuery } from '../lib/query'

export function useMaterials(query: MaterialQuery) {
  const [data, setData] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const queryKey = useMemo(() => serializeQuery(query).toString(), [query])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        setData(await searchMaterials(query, controller.signal))
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Search failed')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }, 180)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [queryKey, revision])

  return { data, error, loading, refresh: useCallback(() => setRevision((value) => value + 1), []) }
}

export function useAtlasStats() {
  const [stats, setStats] = useState<AtlasStats | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    getStats(controller.signal).then(setStats).catch(() => undefined)
    return () => controller.abort()
  }, [])
  return stats
}
