import { fireEvent, render, screen } from '../test/render'
import { describe, expect, it } from 'vitest'

import { CrystalViewer } from './CrystalViewer'

const structure = {
  formula: 'SiO2',
  site_count: 3,
  lattice: {
    matrix: [[5, 0, 0], [0, 5, 0], [0, 0, 5]],
    a: 5,
    b: 5,
    c: 5,
    alpha: 90,
    beta: 90,
    gamma: 90,
    volume: 125,
  },
  sites: [
    { index: 0, element: 'Si', species: 'Si', occupancy: 1, atomic_number: 14, fractional: [0, 0, 0], cartesian: [0, 0, 0], color: [0.94, 0.78, 0.63], radius: 1.11 },
  ],
  bonds: [],
}

describe('CrystalViewer', () => {
  it('uses the OVITO render as the primary crystal view and updates the camera', () => {
    render(<CrystalViewer materialId="exp-000001" structure={structure} />)

    const image = screen.getByRole('img', { name: 'OVITO crystal structure render of SiO2' })
    expect(image).toHaveAttribute('src', expect.stringContaining('/api/materials/exp-000001/render?'))
    expect(image).toHaveAttribute('src', expect.stringContaining('view=isometric'))

    fireEvent.click(screen.getByRole('button', { name: 'Top' }))
    expect(screen.getByRole('img', { name: 'OVITO crystal structure render of SiO2' })).toHaveAttribute('src', expect.stringContaining('view=top'))
  })

  it('does not open on OVITO, or request a render, when the server says it is unavailable', () => {
    // /api/stats carries ovito_available; the viewer used to ignore it and always
    // open the OVITO tab, so the user waited out a render that could only fail.
    render(<CrystalViewer materialId="exp-000001" structure={structure} ovitoAvailable={false} />)

    expect(screen.queryByRole('img', { name: /OVITO crystal structure render/ })).toBeNull()
    expect(screen.getByRole('tab', { name: 'Interactive 3D' })).toHaveAttribute('aria-selected', 'true')
  })

  it('says why the OVITO tab is unavailable rather than failing silently', () => {
    render(<CrystalViewer materialId="exp-000001" structure={structure} ovitoAvailable={false} />)

    const ovitoTab = screen.getByRole('tab', { name: /OVITO/ })
    expect(ovitoTab).toBeDisabled()
    fireEvent.click(ovitoTab)
    expect(screen.getByRole('tab', { name: 'Interactive 3D' })).toHaveAttribute('aria-selected', 'true')
  })

  it('offers an interactive fallback without loading WebGL', () => {
    render(<CrystalViewer materialId="pool-000001" structure={structure} />)

    fireEvent.click(screen.getByRole('tab', { name: 'Interactive 3D' }))
    expect(screen.getByText('This browser cannot start WebGL')).toBeInTheDocument()
  })

  it('hands the camera and cell-size controls to the interactive view too', () => {
    // both only ever went into the OVITO image URL, so in the interactive view
    // pressing I / F / T and changing cell size did nothing at all
    render(<CrystalViewer materialId="exp-1" structure={structure} ovitoAvailable={false} />)

    fireEvent.click(screen.getByRole('button', { name: 'Front' }))
    fireEvent.change(screen.getByLabelText('Supercell'), { target: { value: '3,3,3' } })

    expect(screen.getByRole('button', { name: 'Front' })).toHaveAttribute('data-active', 'true')
    expect(screen.getByLabelText('Supercell')).toHaveValue('3,3,3')
  })

  it('does not show ray-tracing quality when nothing is being ray-traced', () => {
    // it used to be disabled, which left a select frozen on PREVIEW that read as broken
    render(<CrystalViewer materialId="exp-1" structure={structure} ovitoAvailable={false} />)

    expect(screen.queryByRole('combobox', { name: /quality/i })).not.toBeInTheDocument()
  })

  it('shows ray-tracing quality on the tab it applies to', () => {
    render(<CrystalViewer materialId="exp-1" structure={structure} ovitoAvailable />)

    expect(screen.getByRole('combobox', { name: /quality/i })).toBeInTheDocument()
  })
})
