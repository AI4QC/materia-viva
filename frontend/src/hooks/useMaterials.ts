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
    if (hasInvalidRange(query)) {
      setLoading(false)
      setError('invalid-range')
      return () => controller.abort()
    }
    if (hasInvalidSpacegroups(query.spacegroups)) {
      setLoading(false)
      setError('invalid-spacegroups')
      return () => controller.abort()
    }
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
    }, 350)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [queryKey, revision])

  return { data, error, loading, refresh: useCallback(() => setRevision((value) => value + 1), []) }
}

function hasInvalidSpacegroups(value: string) {
  if (!value.trim()) return false
  return value.split(',').some((item) => {
    const number = Number(item.trim())
    return !Number.isInteger(number) || number < 1 || number > 230
  })
}

function hasInvalidRange(query: MaterialQuery) {
  return [
    [query.gapMin, query.gapMax], [query.densityMin, query.densityMax],
    [query.nAtomsMin, query.nAtomsMax], [query.nElementsMin, query.nElementsMax],
    [query.volumeMin, query.volumeMax], [query.formationEnergyMin, query.formationEnergyMax],
    [query.energyAboveHullMin, query.energyAboveHullMax], [query.magnetizationMin, query.magnetizationMax],
    [query.bulkModulusMin, query.bulkModulusMax], [query.shearModulusMin, query.shearModulusMax],
  ].some(([min, max]) => min !== undefined && max !== undefined && min > max)
}

export function useAtlasStats() {
  const [data, setData] = useState<AtlasStats | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  useEffect(() => {
    const controller = new AbortController()
    getStats(controller.signal)
      .then((stats) => { setData(stats); setStatus('ready') })
      .catch(() => { if (!controller.signal.aborted) setStatus('error') })
    return () => controller.abort()
  }, [])
  return { data, status }
}
