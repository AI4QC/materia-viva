import type { CrystalStructure, MaterialProperty } from '../api/client'

export type View = 'isometric' | 'front' | 'top'

export interface FormulaPart {
  text: string
  sub: boolean
}

/** Hide explicit unit counts and mark all other formula counts as subscripts. */
export function formulaParts(value: string): FormulaPart[] {
  const parts: FormulaPart[] = []
  for (const token of value.matchAll(/(\d+(?:\.\d+)?|[^\d]+)/g)) {
    const text = token[0]
    if (/^\d/.test(text)) {
      if (Number(text) !== 1) parts.push({ text, sub: true })
    } else {
      parts.push({ text, sub: false })
    }
  }
  return parts.length ? parts : [{ text: value, sub: false }]
}

export function parseRepeats(value: string): [number, number, number] {
  const parsed = value.split(',').map(Number)
  return parsed.length === 3 && parsed.every((item) => Number.isInteger(item) && item >= 1 && item <= 3)
    ? parsed as [number, number, number]
    : [1, 1, 1]
}

export function expandStructure(structure: CrystalStructure, repeats: [number, number, number]) {
  const sites: CrystalStructure['sites'] = []
  const bonds: CrystalStructure['bonds'] = []
  const origins: number[][] = []
  const [a = [0, 0, 0], b = [0, 0, 0], c = [0, 0, 0]] = structure.lattice.matrix

  for (let i = 0; i < repeats[0]; i += 1) {
    for (let j = 0; j < repeats[1]; j += 1) {
      for (let k = 0; k < repeats[2]; k += 1) {
        const shift = [0, 1, 2].map((axis) => i * (a[axis] ?? 0) + j * (b[axis] ?? 0) + k * (c[axis] ?? 0))
        const offset = sites.length
        origins.push(shift)
        sites.push(...structure.sites.map((site, index) => ({
          ...site,
          index: offset + index,
          cartesian: site.cartesian.map((value, axis) => value + shift[axis]),
        })))
        bonds.push(...structure.bonds.map((bond) => ({
          ...bond,
          from: bond.from + offset,
          to: bond.to + offset,
        })))
      }
    }
  }
  return { sites, bonds, origins }
}

export function framingRadius(sites: CrystalStructure['sites'], atomScale = 0): number {
  if (!sites.length) return 4
  const center = [0, 1, 2].map((axis) => sites.reduce((sum, site) => sum + (site.cartesian[axis] ?? 0), 0) / sites.length)
  return Math.max(4, ...sites.map((site) => (
    Math.hypot(...site.cartesian.map((value, axis) => value - center[axis])) + site.radius * atomScale
  )))
}

export function cameraPosition(view: View, radius: number): [number, number, number] {
  const distance = Math.max(8, radius * 3.4)
  if (view === 'front') return [0, 0, distance]
  if (view === 'top') return [0, distance, distance * 0.001]
  const axis = distance / Math.sqrt(3)
  return [axis, axis, axis]
}

export function elementDisplayColor(color: number[]): string {
  const values = [0, 1, 2].map((index) => Math.round((color[index] ?? 0) * 255))
  return `rgb(${values.join(',')})`
}

/** Slightly soften the source Jmol color while preserving its identity. */
export function mutedElementColor(color: number[]): string {
  const source = [0, 1, 2].map((index) => Math.max(0, Math.min(1, color[index] ?? 0)) * 255)
  const gray = source[0] * 0.2126 + source[1] * 0.7152 + source[2] * 0.0722
  const values = source.map((value) => Math.round(value * 0.85 + gray * 0.15))
  return `rgb(${values.join(',')})`
}

export function collapseIdenticalRows(properties: MaterialProperty[]) {
  const groups = new Map<string, { row: MaterialProperty; count: number; nativeIds: string[] }>()
  for (const row of properties) {
    const { native_id: _nativeId, ...visible } = row
    const key = JSON.stringify(visible)
    const group = groups.get(key)
    if (group) {
      group.count += 1
      if (row.native_id) group.nativeIds.push(row.native_id)
    } else {
      groups.set(key, { row, count: 1, nativeIds: row.native_id ? [row.native_id] : [] })
    }
  }
  return [...groups.values()]
}
