import { describe, expect, it } from 'vitest'

import { cameraPosition, collapseIdenticalRows, expandStructure, formulaParts, framingRadius, parseRepeats } from './crystal'

const cubic = {
  formula: 'SiC',
  site_count: 2,
  lattice: { matrix: [[5, 0, 0], [0, 5, 0], [0, 0, 5]], a: 5, b: 5, c: 5, alpha: 90, beta: 90, gamma: 90, volume: 125 },
  sites: [
    { index: 0, element: 'Si', species: 'Si', occupancy: 1, atomic_number: 14, fractional: [0, 0, 0], cartesian: [0, 0, 0], color: [1, 1, 1], radius: 1.1 },
    { index: 1, element: 'C', species: 'C', occupancy: 1, atomic_number: 6, fractional: [0.5, 0.5, 0.5], cartesian: [2.5, 2.5, 2.5], color: [0, 0, 0], radius: 0.7 },
  ],
  bonds: [{ from: 0, to: 1, distance: 4.33 }],
}

describe('parseRepeats', () => {
  it('reads the viewer control and clamps to what the renderer accepts', () => {
    expect(parseRepeats('2,2,2')).toEqual([2, 2, 2])
    expect(parseRepeats('1,1,1')).toEqual([1, 1, 1])
    expect(parseRepeats('9,0,-3')).toEqual([4, 1, 1])
    expect(parseRepeats('nonsense')).toEqual([1, 1, 1])
  })
})

describe('expandStructure', () => {
  it('leaves a 1x1x1 cell untouched rather than rebuilding it', () => {
    const result = expandStructure(cubic, [1, 1, 1])
    expect(result.sites).toBe(cubic.sites)
    expect(result.bonds).toBe(cubic.bonds)
  })

  it('repeats sites along the lattice vectors', () => {
    const { sites, origins } = expandStructure(cubic, [2, 1, 1])

    expect(sites).toHaveLength(4)
    expect(origins).toEqual([[0, 0, 0], [5, 0, 0]])
    // the second copy is the first, moved one lattice vector along a
    expect(sites[2].cartesian).toEqual([5, 0, 0])
    expect(sites[3].cartesian).toEqual([7.5, 2.5, 2.5])
  })

  it('never lets a bond join two different copies of the cell', () => {
    const { bonds, sites } = expandStructure(cubic, [2, 2, 2])

    expect(sites).toHaveLength(16)
    expect(bonds).toHaveLength(8)
    for (const bond of bonds) {
      expect(Math.floor(bond.from / 2)).toBe(Math.floor(bond.to / 2))
    }
  })
})

describe('cameraPosition', () => {
  it('puts front down one axis and top down another', () => {
    const [fx, fy, fz] = cameraPosition('front', 10)
    expect(fx).toBeCloseTo(0)
    expect(fy).toBeCloseTo(0)
    expect(fz).toBeCloseTo(10)

    const [, ty] = cameraPosition('top', 10)
    expect(ty).toBeCloseTo(10, 1)
  })

  it('never looks exactly straight down, which leaves the up vector undefined', () => {
    const [x, , z] = cameraPosition('top', 10)
    expect(Math.hypot(x, z)).toBeGreaterThan(0)
  })

  it('gives each preset a distinct camera, which is the bug being fixed', () => {
    const seen = new Set([
      cameraPosition('isometric', 10).map((v) => v.toFixed(3)).join(),
      cameraPosition('front', 10).map((v) => v.toFixed(3)).join(),
      cameraPosition('top', 10).map((v) => v.toFixed(3)).join(),
    ])
    expect(seen.size).toBe(3)
  })

  it('keeps the requested distance', () => {
    for (const view of ['isometric', 'front', 'top'] as const) {
      const [x, y, z] = cameraPosition(view, 12)
      expect(Math.hypot(x, y, z)).toBeCloseTo(12, 3)
    }
  })
})

describe('framingRadius', () => {
  it('grows with the structure, so a supercell is not framed like one cell', () => {
    const one = framingRadius(cubic.sites)
    const many = framingRadius(expandStructure(cubic, [3, 3, 3]).sites)
    expect(many).toBeGreaterThan(one)
  })

  it('has a floor, so a single atom at the origin is still visible', () => {
    expect(framingRadius([])).toBeGreaterThan(0)
    expect(framingRadius([cubic.sites[0]])).toBeGreaterThan(0)
  })
})

describe('collapseIdenticalRows', () => {
  const aflow = (native_id: string, value_num = -8.7719) => ({
    property: 'total_energy_per_atom', unit: 'eV/atom', method: 'PBE (AFLOW)',
    source: 'aflow', value_num, value_text: null, native_id,
  })

  it('folds rows that say exactly the same thing and counts them', () => {
    // ThO2 showed "-8.7719 eV/atom, PBE (AFLOW), AFLOW" six times over
    const folded = collapseIdenticalRows([aflow('a'), aflow('b'), aflow('c'),
                                          aflow('d'), aflow('e'), aflow('f')])

    expect(folded).toHaveLength(1)
    expect(folded[0].count).toBe(6)
  })

  it('keeps the upstream ids, so the count can be checked', () => {
    const folded = collapseIdenticalRows([aflow('aflow:1'), aflow('aflow:2')])
    expect(folded[0].nativeIds).toEqual(['aflow:1', 'aflow:2'])
  })

  it('never folds two rows that disagree', () => {
    const folded = collapseIdenticalRows([aflow('a', -8.77), aflow('b', -8.81)])
    expect(folded).toHaveLength(2)
  })

  it('does not fold across method or source, however equal the number', () => {
    const same = { property: 'density', unit: 'g/cm³', value_num: 3.24, value_text: null }
    const folded = collapseIdenticalRows([
      { ...same, method: 'measured', source: 'amcsd', native_id: '1' },
      { ...same, method: 'measured', source: 'cod', native_id: '2' },
      { ...same, method: 'computed', source: 'amcsd', native_id: '3' },
    ])
    expect(folded).toHaveLength(3)
  })

  it('separates a text value from a numeric one', () => {
    const folded = collapseIdenticalRows([
      { property: 'chemical_name', unit: null, method: null, source: 'cod', value_num: null, value_text: 'Moissanite', native_id: '1' },
      { property: 'chemical_name', unit: null, method: null, source: 'cod', value_num: null, value_text: 'Moissanite 3C', native_id: '2' },
    ])
    expect(folded).toHaveLength(2)
  })

  it('keeps the order the rows arrived in', () => {
    const folded = collapseIdenticalRows([
      aflow('a'), { ...aflow('b'), property: 'band_gap' }, aflow('c'),
    ])
    expect(folded.map((f) => f.row.property)).toEqual(['total_energy_per_atom', 'band_gap'])
    expect(folded[0].count).toBe(2)
  })
})

describe('formulaParts', () => {
  const plain = (f: string) => formulaParts(f).map((p) => p.text).join('')

  it('drops a count of one, which is not how anyone writes a formula', () => {
    // the index stores every count, so CdS arrives as Cd1S1 and read as Cd₁S₁
    expect(plain('Cd1S1')).toBe('CdS')
    expect(plain('Th1O2')).toBe('ThO2')
    expect(plain('Ag1Cl1O4')).toBe('AgClO4')
  })

  it('keeps every other count, and subscripts it', () => {
    expect(formulaParts('Th1O2')).toEqual([
      { text: 'Th', sub: false }, { text: 'O', sub: false }, { text: '2', sub: true },
    ])
  })

  it('never reduces a cell to its lowest terms', () => {
    // Ag2I2 is two formula units in one cell, not AgI
    expect(plain('Ag2I2')).toBe('Ag2I2')
    expect(formulaParts('Ag2I2').filter((p) => p.sub).map((p) => p.text)).toEqual(['2', '2'])
  })

  it('keeps a fractional occupancy', () => {
    expect(plain('Fe0.5Ni0.5')).toBe('Fe0.5Ni0.5')
  })

  it('shows anything it cannot read exactly as given', () => {
    expect(formulaParts('not a formula')).toEqual([{ text: 'not a formula', sub: false }])
  })
})
