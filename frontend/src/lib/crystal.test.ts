import { describe, expect, it } from 'vitest'

import type { CrystalStructure, MaterialProperty } from '../api/client'
import { cameraPosition, collapseIdenticalRows, elementDisplayColor, expandStructure, formulaParts, framingRadius, mutedElementColor, parseRepeats } from './crystal'

const structure: CrystalStructure = {
  formula: 'Na1Cl1', site_count: 2,
  lattice: { matrix: [[2, 0, 0], [0, 2, 0], [0, 0, 2]], a: 2, b: 2, c: 2, alpha: 90, beta: 90, gamma: 90, volume: 8 },
  sites: [
    { index: 0, element: 'Na', species: 'Na', occupancy: 1, atomic_number: 11, fractional: [0, 0, 0], cartesian: [0, 0, 0], color: [1, 1, 1], radius: 1 },
    { index: 1, element: 'Cl', species: 'Cl', occupancy: 1, atomic_number: 17, fractional: [.5, .5, .5], cartesian: [1, 1, 1], color: [0, 1, 0], radius: 1 },
  ],
  bonds: [{ from: 0, to: 1, distance: 1.73 }],
}

describe('crystal helpers', () => {
  it('formats explicit unit counts as conventional chemical formulas', () => {
    expect(formulaParts('Cd1S1').map((part) => part.text).join('')).toBe('CdS')
    expect(formulaParts('Ca3(PO4)2').filter((part) => part.sub).map((part) => part.text)).toEqual(['3', '4', '2'])
  })

  it('expands sites and keeps every bond inside its replica', () => {
    const expanded = expandStructure(structure, parseRepeats('2,1,1'))
    expect(expanded.sites).toHaveLength(4)
    expect(expanded.origins).toEqual([[0, 0, 0], [2, 0, 0]])
    expect(expanded.bonds.map(({ from, to }) => [from, to])).toEqual([[0, 1], [2, 3]])
    expect(framingRadius(expanded.sites)).toBeGreaterThanOrEqual(4)
  })

  it('provides distinct, equally distant camera presets', () => {
    const positions = ['isometric', 'front', 'top'].map((view) => cameraPosition(view as 'isometric' | 'front' | 'top', 5))
    expect(new Set(positions.map(String))).toHaveLength(3)
    positions.forEach((position) => expect(Math.hypot(...position)).toBeCloseTo(17, 3))
  })

  it('includes visible atom radii when framing a space-filling model', () => {
    const largeAtoms = structure.sites.map((site) => ({ ...site, radius: 10 }))
    expect(framingRadius(largeAtoms, 0.74)).toBeGreaterThan(7.4)
  })

  it('keeps source colors and derives a stable muted variant from them', () => {
    expect(elementDisplayColor([0, 1, 0])).toBe('rgb(0,255,0)')
    expect(mutedElementColor([0, 1, 0])).toBe('rgb(27,244,27)')
    expect(mutedElementColor([0, 1, 0])).toBe(mutedElementColor([0, 1, 0]))
  })

  it('collapses duplicate visible property rows while retaining native ids', () => {
    const base: MaterialProperty = { property: 'gap', unit: 'eV', kind: 'num', value_num: 2, value_text: null, method: 'PBE', source: 'demo', source_name: 'Demo', source_license: null, source_url: null, native_id: 'a' }
    expect(collapseIdenticalRows([base, { ...base, native_id: 'b' }])).toEqual([{ row: base, count: 2, nativeIds: ['a', 'b'] }])
  })
})
