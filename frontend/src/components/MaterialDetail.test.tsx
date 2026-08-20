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

const xrd = {
  wavelength: 'CuKa 1.5406 Å', x_label: '2θ', x_unit: 'deg',
  y_label: 'Intensity', y_unit: 'a.u.',
  x: [21.98, 28.44, 35.1], y: [100, 41.2, 12.9], hkl: ['(011)', '(101)', '(111)'], d: [4.04, 3.13, 2.55],
}

function stubFetch(detailPayload: unknown) {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    const payload = url.endsWith('/structure') ? structure : url.endsWith('/xrd') ? xrd : detailPayload
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('MaterialDetail', () => {
  it('loads the record and structure into the detail workbench', async () => {
    stubFetch(detail)

    render(<MaterialDetail materialId="exp-000001" onClose={() => undefined} />)

    expect(screen.getByText('Parsing crystal structure')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'SiO2' })).toBeInTheDocument())
    expect(screen.getByText('Experimental')).toBeInTheDocument()
    expect(screen.getByText('Fd-3m · 227')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download CIF' })).toHaveAttribute('href', '/api/materials/exp-000001/cif')
    expect(screen.getByText('train · row 17')).toBeInTheDocument()
  })

  it('renders cross-database properties with source tags, refs and the family badge', async () => {
    const enriched = {
      ...detail,
      material_family: 'mof',
      formation_energy_per_atom: -2.41,
      properties: [
        {
          property: 'band_gap', unit: 'eV', kind: 'num', value_num: 2.05,
          value_text: null, method: 'HSE06', source: 'snumat',
          source_name: 'SNUMAT', source_license: 'Figshare record licence',
          source_url: 'https://www.snumat.com/', native_id: 'SM-1888',
        },
        {
          property: 'topology_class', unit: null, kind: 'text', value_num: null,
          value_text: 'TI', method: 'PBE+SOC SymTopo', source: 'materiae',
          source_name: 'Materiae', source_license: null, source_url: null,
          native_id: 'MAT00000001',
        },
      ],
      source_refs: [
        {
          source: 'snumat', source_name: 'SNUMAT',
          source_license: 'Figshare record licence',
          source_url: 'https://www.snumat.com/', native_id: 'SM-1888',
          match_via: 'id:icsd',
        },
      ],
    }
    stubFetch(enriched)

    render(<MaterialDetail materialId="exp-000001" onClose={() => undefined} />)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'SiO2' })).toBeInTheDocument())
    expect(screen.getByText('MOF')).toBeInTheDocument()
    expect(screen.getByText('Cross-database properties')).toBeInTheDocument()
    expect(screen.getByText('2.05 eV')).toBeInTheDocument()
    expect(screen.getByText('HSE06')).toBeInTheDocument()
    expect(screen.getAllByText('SNUMAT').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('TI')).toBeInTheDocument()
    expect(screen.getByText('Materiae')).toBeInTheDocument()
    expect(screen.getByText('Representative properties')).toBeInTheDocument()
    expect(screen.getByText('-2.410 eV/atom')).toBeInTheDocument()
    expect(screen.getByText('SM-1888')).toBeInTheDocument()
  })

  it('renders the spectra area with a simulated XRD pattern below the viewer', async () => {
    stubFetch(detail)

    render(<MaterialDetail materialId="exp-000001" onClose={() => undefined} />)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'SiO2' })).toBeInTheDocument())
    expect(screen.getByText('Spectra & curves')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('img', { name: 'Powder XRD' })).toBeInTheDocument())
    expect(screen.getByText('Simulated (CuKα)')).toBeInTheDocument()
    const chart = screen.getByRole('img', { name: 'Powder XRD' })
    expect(chart.querySelectorAll('.chart-stick')).toHaveLength(3)
  })
})
