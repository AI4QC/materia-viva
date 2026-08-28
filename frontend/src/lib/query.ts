export type ElementMode = 'all' | 'any' | 'exact'
export type SortDirection = 'asc' | 'desc'

/** What the API will sort by. A URL naming anything else is not obeyed. */
export const SORT_KEYS = [
  'material_id', 'formula', 'pbes_gap', 'density', 'n_atoms', 'n_elements',
  'spacegroup_number', 'volume', 'formation_energy_per_atom', 'energy_above_hull',
  'bulk_modulus',
] as const

export type SortKey = (typeof SORT_KEYS)[number]

export type StabilityFilter = '' | 'stable' | 'unstable'
export type MetallicityFilter = '' | 'metal' | 'nonmetal'

export interface MaterialQuery {
  includedElements: string[]
  excludedElements: string[]
  elementMode: ElementMode
  datasets: Array<'experimental' | 'candidate'>
  formula: string
  gapMin?: number
  gapMax?: number
  densityMin?: number
  densityMax?: number
  volumeMin?: number
  volumeMax?: number
  nAtomsMin?: number
  nAtomsMax?: number
  nElementsMin?: number
  nElementsMax?: number
  spacegroups: string
  crystalSystems: string[]
  formationEnergyMin?: number
  formationEnergyMax?: number
  energyAboveHullMin?: number
  energyAboveHullMax?: number
  stability: StabilityFilter
  metallicity: MetallicityFilter
  magneticOrderings: string
  materialFamilies: string[]
  magnetizationMin?: number
  magnetizationMax?: number
  bulkModulusMin?: number
  bulkModulusMax?: number
  shearModulusMin?: number
  shearModulusMax?: number
  hasProperties: string[]
  page: number
  pageSize: number
  sort: string
  direction: SortDirection
}

export const DEFAULT_QUERY: MaterialQuery = {
  includedElements: [],
  excludedElements: [],
  elementMode: 'all',
  datasets: [],
  formula: '',
  spacegroups: '',
  crystalSystems: [],
  stability: '',
  metallicity: '',
  magneticOrderings: '',
  materialFamilies: [],
  hasProperties: [],
  page: 1,
  pageSize: 24,
  sort: 'material_id',
  direction: 'asc',
}

const csv = (values: string[]) => [...new Set(values)].sort().join(',')

export function serializeQuery(query: MaterialQuery): URLSearchParams {
  const params = new URLSearchParams()
  if (query.includedElements.length) params.set('elements', csv(query.includedElements))
  if (query.excludedElements.length) params.set('exclude', csv(query.excludedElements))
  if (query.elementMode !== DEFAULT_QUERY.elementMode) params.set('element_mode', query.elementMode)
  if (query.datasets.length) params.set('datasets', csv(query.datasets))
  if (query.formula.trim()) params.set('formula', query.formula.trim())
  setNumber(params, 'gap_min', query.gapMin)
  setNumber(params, 'gap_max', query.gapMax)
  setNumber(params, 'density_min', query.densityMin)
  setNumber(params, 'density_max', query.densityMax)
  setNumber(params, 'volume_min', query.volumeMin)
  setNumber(params, 'volume_max', query.volumeMax)
  setNumber(params, 'n_atoms_min', query.nAtomsMin)
  setNumber(params, 'n_atoms_max', query.nAtomsMax)
  setNumber(params, 'n_elements_min', query.nElementsMin)
  setNumber(params, 'n_elements_max', query.nElementsMax)
  setNumber(params, 'formation_energy_min', query.formationEnergyMin)
  setNumber(params, 'formation_energy_max', query.formationEnergyMax)
  setNumber(params, 'e_hull_min', query.energyAboveHullMin)
  setNumber(params, 'e_hull_max', query.energyAboveHullMax)
  if (query.stability) params.set('stability', query.stability)
  if (query.metallicity) params.set('metallicity', query.metallicity)
  if (query.magneticOrderings.trim()) params.set('magnetic_orderings', query.magneticOrderings.trim())
  if (query.materialFamilies.length) params.set('material_families', csv(query.materialFamilies))
  setNumber(params, 'magnetization_min', query.magnetizationMin)
  setNumber(params, 'magnetization_max', query.magnetizationMax)
  setNumber(params, 'bulk_modulus_min', query.bulkModulusMin)
  setNumber(params, 'bulk_modulus_max', query.bulkModulusMax)
  setNumber(params, 'shear_modulus_min', query.shearModulusMin)
  setNumber(params, 'shear_modulus_max', query.shearModulusMax)
  if (query.hasProperties.length) params.set('has_properties', csv(query.hasProperties))
  if (query.spacegroups.trim()) params.set('spacegroups', query.spacegroups.trim())
  if (query.crystalSystems.length) params.set('crystal_systems', csv(query.crystalSystems))
  if (query.page !== DEFAULT_QUERY.page) params.set('page', String(query.page))
  if (query.pageSize !== DEFAULT_QUERY.pageSize) params.set('page_size', String(query.pageSize))
  if (query.sort !== DEFAULT_QUERY.sort) params.set('sort', query.sort)
  if (query.direction !== DEFAULT_QUERY.direction) params.set('direction', query.direction)
  return params
}

export function parseQuery(params: URLSearchParams): MaterialQuery {
  const mode = params.get('element_mode')
  const direction = params.get('direction')
  return {
    ...DEFAULT_QUERY,
    includedElements: splitCsv(params.get('elements')),
    excludedElements: splitCsv(params.get('exclude')),
    elementMode: mode === 'any' || mode === 'exact' ? mode : 'all',
    datasets: splitCsv(params.get('datasets')).filter(
      (value): value is 'experimental' | 'candidate' =>
        value === 'experimental' || value === 'candidate',
    ),
    formula: params.get('formula') ?? '',
    gapMin: parseNumber(params.get('gap_min')),
    gapMax: parseNumber(params.get('gap_max')),
    densityMin: parseNumber(params.get('density_min')),
    densityMax: parseNumber(params.get('density_max')),
    volumeMin: parseNumber(params.get('volume_min')),
    volumeMax: parseNumber(params.get('volume_max')),
    nAtomsMin: parseNumber(params.get('n_atoms_min')),
    nAtomsMax: parseNumber(params.get('n_atoms_max')),
    nElementsMin: parseNumber(params.get('n_elements_min')),
    nElementsMax: parseNumber(params.get('n_elements_max')),
    spacegroups: params.get('spacegroups') ?? '',
    crystalSystems: splitCsv(params.get('crystal_systems')),
    formationEnergyMin: parseNumber(params.get('formation_energy_min')),
    formationEnergyMax: parseNumber(params.get('formation_energy_max')),
    energyAboveHullMin: parseNumber(params.get('e_hull_min')),
    energyAboveHullMax: parseNumber(params.get('e_hull_max')),
    stability: parseStability(params.get('stability')),
    metallicity: parseMetallicity(params.get('metallicity')),
    magneticOrderings: params.get('magnetic_orderings') ?? '',
    materialFamilies: splitCsv(params.get('material_families')),
    magnetizationMin: parseNumber(params.get('magnetization_min')),
    magnetizationMax: parseNumber(params.get('magnetization_max')),
    bulkModulusMin: parseNumber(params.get('bulk_modulus_min')),
    bulkModulusMax: parseNumber(params.get('bulk_modulus_max')),
    shearModulusMin: parseNumber(params.get('shear_modulus_min')),
    shearModulusMax: parseNumber(params.get('shear_modulus_max')),
    hasProperties: splitCsv(params.get('has_properties')),
    page: positiveInteger(params.get('page'), 1),
    pageSize: positiveInteger(params.get('page_size'), 24),
    // validated like elementMode and direction beside it: an unknown key used to
    // reach the API, come back 422, and leave a Retry button that could not work
    sort: isSortKey(params.get('sort')) ? (params.get('sort') as SortKey) : 'material_id',
    direction: direction === 'desc' ? 'desc' : 'asc',
  }
}

function parseStability(value: string | null): StabilityFilter {
  return value === 'stable' || value === 'unstable' ? value : ''
}

function parseMetallicity(value: string | null): MetallicityFilter {
  return value === 'metal' || value === 'nonmetal' ? value : ''
}

function splitCsv(value: string | null): string[] {
  return [...new Set((value ?? '').split(',').map((item) => item.trim()).filter(Boolean))]
}

function setNumber(params: URLSearchParams, key: string, value?: number) {
  if (value !== undefined && Number.isFinite(value)) params.set(key, String(value))
}

function parseNumber(value: string | null): number | undefined {
  if (value === null || value.trim() === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function positiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function isSortKey(value: string | null): value is SortKey {
  return value !== null && (SORT_KEYS as readonly string[]).includes(value)
}
