import type { MaterialQuery } from '../lib/query'
import { serializeQuery } from '../lib/query'

export interface MaterialSummary {
  material_id: string
  formula: string
  chemical_system: string
  dataset: 'experimental' | 'candidate'
  is_experimental: boolean
  n_elements: number
  n_atoms: number
  pbes_gap: number | null
  density: number | null
  volume?: number | null
  spacegroup_number: number | null
  spacegroup_symbol?: string | null
  crystal_system: string | null
  material_family?: string | null
}

export interface MaterialProperty {
  property: string
  unit: string | null
  kind: string
  value_num: number | null
  value_text: string | null
  value_bool?: boolean
  method: string | null
  source: string
  source_name: string
  source_license: string | null
  source_url: string | null
  native_id: string | null
}

export interface MaterialSourceRef {
  source: string
  source_name: string
  source_license: string | null
  source_url: string | null
  native_id: string
  match_via: string
}

export interface MaterialCurve {
  id: number
  curve_type: string
  fmt: 'xy' | 'peaks' | 'svg'
  method: string | null
  label: string | null
  native_id: string | null
  source: string
  source_name: string
}

export interface XrdPattern {
  wavelength: string
  x_label: string
  x_unit: string
  y_label: string
  y_unit: string
  x: number[]
  y: number[]
  hkl?: string[]
  d?: number[]
}

export interface CurvePayload {
  x: number[]
  y: number[]
  x_label?: string
  y_label?: string
  x_unit?: string
  y_unit?: string
  hkl?: string[]
  d?: number[]
  series?: Array<{ name: string; y: number[] }>
}

export interface MaterialDetailRecord extends MaterialSummary {
  elements: string[]
  source_split: string
  source_index: string
  lattice_a?: number | null
  lattice_b?: number | null
  lattice_c?: number | null
  lattice_alpha?: number | null
  lattice_beta?: number | null
  lattice_gamma?: number | null
  formation_energy_per_atom?: number | null
  energy_above_hull?: number | null
  is_stable?: boolean | null
  is_metal?: boolean | null
  magnetic_ordering?: string | null
  total_magnetization?: number | null
  bulk_modulus?: number | null
  shear_modulus?: number | null
  poisson_ratio?: number | null
  properties?: MaterialProperty[]
  source_refs?: MaterialSourceRef[]
  curves?: MaterialCurve[]
}

export interface CrystalSite {
  index: number
  element: string
  species: string
  occupancy: number
  atomic_number: number
  fractional: number[]
  cartesian: number[]
  color: number[]
  radius: number
}

export interface CrystalStructure {
  formula: string
  site_count: number
  lattice: {
    matrix: number[][]
    a: number
    b: number
    c: number
    alpha: number
    beta: number
    gamma: number
    volume: number
  }
  sites: CrystalSite[]
  bonds: Array<{ from: number; to: number; distance: number }>
}

export interface SearchResponse {
  items: MaterialSummary[]
  total: number
  page: number
  page_size: number
  pages: number
  facets: { datasets?: Record<string, number> }
}

export interface AtlasStats {
  total: number
  datasets: Record<string, number>
  property_counts: Record<string, number>
  ovito_available: boolean
  /** Cross-database property rows; null when the index has not cached the count. */
  property_rows?: number | null
  /** Stored spectra/curves; null when the index has not cached the count. */
  curve_count?: number | null
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function searchMaterials(query: MaterialQuery, signal?: AbortSignal) {
  return request<SearchResponse>(`/api/materials?${serializeQuery(query)}`, { signal })
}

export async function getStats(signal?: AbortSignal) {
  return request<AtlasStats>('/api/stats', { signal })
}

export async function getMaterial<T = MaterialDetailRecord>(materialId: string, signal?: AbortSignal) {
  return request<T>(`/api/materials/${encodeURIComponent(materialId)}`, { signal })
}

export async function getStructure<T = CrystalStructure>(materialId: string, signal?: AbortSignal) {
  return request<T>(`/api/materials/${encodeURIComponent(materialId)}/structure`, { signal })
}

export async function getXrd(materialId: string, signal?: AbortSignal) {
  return request<XrdPattern>(`/api/materials/${encodeURIComponent(materialId)}/xrd`, { signal })
}

export async function getCurve(materialId: string, curveId: number, signal?: AbortSignal) {
  return request<CurvePayload>(
    `/api/materials/${encodeURIComponent(materialId)}/curves/${curveId}`,
    { signal },
  )
}

export function curveUrl(materialId: string, curveId: number) {
  return `/api/materials/${encodeURIComponent(materialId)}/curves/${curveId}`
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, { ...init, headers: { Accept: 'application/json', ...init?.headers } })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const payload = await response.json() as { detail?: { message?: string } | string }
      message = typeof payload.detail === 'string' ? payload.detail : payload.detail?.message ?? message
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}
