import { render, screen, waitFor } from '../test/render'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MaterialDetail } from './MaterialDetail'

const detail = {
  material_id: 'exp-000001', formula: 'SiO2', chemical_system: 'O-Si',
  dataset: 'experimental', is_experimental: true, n_elements: 2, n_atoms: 3,
  pbes_gap: 5.7, density: 2.65, volume: 125, spacegroup_number: 227,
  spacegroup_symbol: 'Fd-3m', crystal_system: 'cubic', elements: ['O', 'Si'],
  source_split: 'train', source_index: '17',
  lattice_a: 5, lattice_b: 5, lattice_c: 5,
  lattice_alpha: 90, lattice_beta: 90, lattice_gamma: 90,
}

const structure = {
  formula: 'SiO2', site_count: 3,
  lattice: { matrix: [[5, 0, 0], [0, 5, 0], [0, 0, 5]], a: 5, b: 5, c: 5, alpha: 90, beta: 90, gamma: 90, volume: 125 },
  sites: [], bonds: [],
}

afterEach(() => vi.unstubAllGlobals())

describe('MaterialDetail', () => {
  it('loads the record and structure into the detail workbench', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url.endsWith('/structure') ? structure : detail
      return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    }))

    render(<MaterialDetail materialId="exp-000001" onClose={() => undefined} />)

    expect(screen.getByText('Parsing crystal structure')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'SiO2' })).toBeInTheDocument())
    expect(screen.getByText('Experimental')).toBeInTheDocument()
    expect(screen.getByText('Fd-3m · 227')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download CIF' })).toHaveAttribute('href', '/api/materials/exp-000001/cif')
    expect(screen.getByText('train · row 17')).toBeInTheDocument()
  })
})
