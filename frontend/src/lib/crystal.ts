import type { CrystalStructure } from '../api/client'

export type View = 'isometric' | 'front' | 'top'

/** `"2,2,2"` as the viewer stores it, clamped to what the render options allow. */
export function parseRepeats(value: string): [number, number, number] {
  const parts = value.split(',').map((part) => Number.parseInt(part.trim(), 10))
  const clamp = (n: number) => (Number.isFinite(n) ? Math.min(4, Math.max(1, n)) : 1)
  return [clamp(parts[0] ?? 1), clamp(parts[1] ?? 1), clamp(parts[2] ?? 1)]
}

/**
 * Repeat the cell along its lattice vectors.
 *
 * The OVITO render has always honoured `supercell`; the interactive view drew
 * one cell whatever the control said. Sites are translated by whole lattice
 * vectors and bond indices are shifted per replica, so a bond never joins two
 * different copies.
 */
export function expandStructure(
  structure: CrystalStructure,
  repeats: [number, number, number],
): { sites: CrystalStructure['sites']; bonds: CrystalStructure['bonds']; origins: number[][] } {
  const [nx, ny, nz] = repeats
  if (nx === 1 && ny === 1 && nz === 1) {
    return { sites: structure.sites, bonds: structure.bonds, origins: [[0, 0, 0]] }
  }

  const [a, b, c] = structure.lattice.matrix
  const per = structure.sites.length
  const sites: CrystalStructure['sites'] = []
  const bonds: CrystalStructure['bonds'] = []
  const origins: number[][] = []

  let replica = 0
  for (let i = 0; i < nx; i += 1) {
    for (let j = 0; j < ny; j += 1) {
      for (let k = 0; k < nz; k += 1) {
        const shift = [
          i * (a?.[0] ?? 0) + j * (b?.[0] ?? 0) + k * (c?.[0] ?? 0),
          i * (a?.[1] ?? 0) + j * (b?.[1] ?? 0) + k * (c?.[1] ?? 0),
          i * (a?.[2] ?? 0) + j * (b?.[2] ?? 0) + k * (c?.[2] ?? 0),
        ]
        origins.push(shift)
        const offset = replica * per
        structure.sites.forEach((site) => {
          sites.push({
            ...site,
            index: site.index + offset,
            cartesian: [
              (site.cartesian[0] ?? 0) + shift[0],
              (site.cartesian[1] ?? 0) + shift[1],
              (site.cartesian[2] ?? 0) + shift[2],
            ],
          })
        })
        structure.bonds.forEach((bond) => {
          bonds.push({ ...bond, from: bond.from + offset, to: bond.to + offset })
        })
        replica += 1
      }
    }
  }
  return { sites, bonds, origins }
}

/** How far the camera has to sit to frame everything on screen. */
export function framingRadius(sites: CrystalStructure['sites']): number {
  if (!sites.length) return 6
  let max = 0
  for (const site of sites) {
    for (const value of site.cartesian.slice(0, 3)) max = Math.max(max, Math.abs(value ?? 0))
  }
  return Math.max(4, max * 1.9)
}

/**
 * Where the camera goes for each preset.
 *
 * These three buttons only ever changed the OVITO image URL. In the interactive
 * view they did nothing at all, which is what made them look broken.
 */
export function cameraPosition(view: View, radius: number): [number, number, number] {
  const direction: Record<View, [number, number, number]> = {
    isometric: [0.62, 0.55, 0.68],
    front: [0, 0, 1],
    top: [0, 1, 0.001], // not exactly axis-aligned: straight down leaves OrbitControls' up vector undefined
  }
  const [x, y, z] = direction[view]
  const length = Math.hypot(x, y, z) || 1
  return [(x / length) * radius, (y / length) * radius, (z / length) * radius]
}

/**
 * Collapse property rows that say exactly the same thing.
 *
 * A source database can hold many records for one crystal — AFLOW keeps a dozen
 * calculation entries for some structures — and fingerprint deduplication
 * matches them all to one MateriaViva material. Every one of those records is
 * kept, so the table showed the same value, method and source a dozen times
 * over. That is faithful to the data and useless to read: it looks like a bug.
 *
 * Rows are folded only when the property, the value, the unit, the method and
 * the source all match, so nothing that differs is ever hidden. The upstream
 * ids are carried through, because the count is only trustworthy if you can
 * still see what it counted.
 */
export function collapseIdenticalRows<
  T extends {
    property: string
    unit?: string | null
    method?: string | null
    source?: string | null
    value_num?: number | null
    value_text?: string | null
    native_id?: string | null
  },
>(rows: readonly T[]): Array<{ row: T; count: number; nativeIds: string[] }> {
  const order: string[] = []
  const groups = new Map<string, { row: T; count: number; nativeIds: string[] }>()

  for (const row of rows) {
    const key = JSON.stringify([
      row.property, row.unit ?? null, row.method ?? null, row.source ?? null,
      row.value_num ?? null, row.value_text ?? null,
    ])
    const seen = groups.get(key)
    if (seen) {
      seen.count += 1
      if (row.native_id) seen.nativeIds.push(row.native_id)
    } else {
      order.push(key)
      groups.set(key, { row, count: 1, nativeIds: row.native_id ? [row.native_id] : [] })
    }
  }
  return order.map((key) => groups.get(key)!)
}

/**
 * A formula split into the parts a `<sub>` should and should not wrap.
 *
 * Indexed formulas spell every count out, so cadmium sulfide arrives as
 * `Cd1S1` and rendered as written it reads Cd₁S₁ — which is not how anyone
 * writes it. A count of exactly 1 is dropped; every other count, including a
 * fractional occupancy, is kept and subscripted.
 *
 * `Ag2I2` keeps both 2s: it is a cell of two formula units, not AgI.
 */
export function formulaParts(formula: string): Array<{ text: string; sub: boolean }> {
  const parts: Array<{ text: string; sub: boolean }> = []
  const pattern = /([A-Z][a-z]?)(\d+(?:\.\d+)?)?|([^A-Za-z\d]+)/g
  let consumed = 0

  for (const match of formula.matchAll(pattern)) {
    if (match.index !== consumed) return [{ text: formula, sub: false }] // unreadable; show as given
    consumed += match[0].length
    if (match[3]) {
      parts.push({ text: match[3], sub: false })
      continue
    }
    parts.push({ text: match[1], sub: false })
    if (match[2] && match[2] !== '1') parts.push({ text: match[2], sub: true })
  }
  if (consumed !== formula.length) return [{ text: formula, sub: false }]
  return parts
}
