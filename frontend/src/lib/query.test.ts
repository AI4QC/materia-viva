import { describe, expect, it } from 'vitest'

import { DEFAULT_QUERY, SORT_KEYS, parseQuery, serializeQuery } from './query'


describe('query URL state', () => {
  it('serializes multi-element filters and numeric ranges deterministically', () => {
    const params = serializeQuery({
      ...DEFAULT_QUERY,
      includedElements: ['O', 'Li'],
      excludedElements: ['Fe'],
      elementMode: 'exact',
      datasets: ['experimental'],
      formula: 'Li2O',
      gapMin: 1.2,
      gapMax: 4.8,
      formationEnergyMax: -1.2,
      energyAboveHullMax: 0.05,
      stability: 'stable',
      hasProperties: ['elasticity', 'formation_energy'],
      page: 3,
    })

    expect(params.toString()).toBe(
      'elements=Li%2CO&exclude=Fe&element_mode=exact&datasets=experimental&formula=Li2O&gap_min=1.2&gap_max=4.8&formation_energy_max=-1.2&e_hull_max=0.05&stability=stable&has_properties=elasticity%2Cformation_energy&page=3',
    )
  })

  it('serializes and parses material families', () => {
    const params = serializeQuery({ ...DEFAULT_QUERY, materialFamilies: ['mof', '2d-material'] })
    expect(params.get('material_families')).toBe('2d-material,mof')

    const parsed = parseQuery(new URLSearchParams('material_families=mof,bulk'))
    expect(parsed.materialFamilies).toEqual(['mof', 'bulk'])
  })

  it('omits defaults and round-trips supported filters', () => {
    expect(serializeQuery(DEFAULT_QUERY).toString()).toBe('')

    const parsed = parseQuery(new URLSearchParams(
      'elements=Fe,O&crystal_systems=cubic,trigonal&n_atoms_min=2&page_size=48&sort=density&direction=desc',
    ))

    expect(parsed.includedElements).toEqual(['Fe', 'O'])
    expect(parsed.crystalSystems).toEqual(['cubic', 'trigonal'])
    expect(parsed.nAtomsMin).toBe(2)
    expect(parsed.pageSize).toBe(48)
    expect(parsed.sort).toBe('density')
    expect(parsed.direction).toBe('desc')
  })
})

describe('sort keys from the address bar', () => {
  it('keeps a key the API will accept', () => {
    expect(parseQuery(new URLSearchParams('sort=density')).sort).toBe('density')
  })

  it('falls back on one it will not, rather than leaving a dead Retry button', () => {
    // an unknown key reached the API, came back 422, and the page offered a
    // "Try again" that could never succeed because the key was still in state
    for (const bad of ['garbage', 'DROP TABLE materials', '', 'Formula']) {
      expect(parseQuery(new URLSearchParams(`sort=${encodeURIComponent(bad)}`)).sort)
        .toBe('material_id')
    }
  })

  it('validates direction the same way, as it already did', () => {
    expect(parseQuery(new URLSearchParams('direction=desc')).direction).toBe('desc')
    expect(parseQuery(new URLSearchParams('direction=sideways')).direction).toBe('asc')
  })

  it('offers every key the sort control can produce', () => {
    // the dropdown and the parser drifting apart is how this got through
    for (const key of SORT_KEYS) {
      expect(parseQuery(new URLSearchParams(`sort=${key}`)).sort).toBe(key)
    }
  })
})
