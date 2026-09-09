import { fireEvent, render, screen } from '../test/render'
import { describe, expect, it, vi } from 'vitest'

import type { SearchResponse } from '../api/client'
import { MaterialResults } from './MaterialResults'


const response: SearchResponse = {
  items: [
    {
      material_id: 'exp-train-1',
      formula: 'LiFePO4',
      chemical_system: 'Fe-Li-O-P',
      dataset: 'experimental',
      is_experimental: true,
      n_elements: 4,
      n_atoms: 7,
      pbes_gap: 2.1,
      density: 3.6,
      spacegroup_number: 62,
      crystal_system: 'orthorhombic',
    },
  ],
  total: 25,
  page: 1,
  page_size: 24,
  pages: 2,
  facets: { datasets: { experimental: 25 } },
}


describe('MaterialResults', () => {
  it('exposes loading, empty, and error states', () => {
    const common = { onPage: vi.fn(), onSelect: vi.fn(), onRetry: vi.fn() }
    const { rerender } = render(<MaterialResults {...common} loading data={null} error={null} />)
    expect(screen.getByRole('status')).toHaveTextContent('Searching the materials space')

    rerender(<MaterialResults {...common} loading={false} data={{ ...response, items: [], total: 0, pages: 0 }} error={null} />)
    expect(screen.getByText('No structures matched')).toBeVisible()

    rerender(<MaterialResults {...common} loading={false} data={null} error="Index unavailable" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Your filters are preserved')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(common.onRetry).toHaveBeenCalledOnce()

    rerender(<MaterialResults {...common} loading={false} data={response} error="invalid-range" />)
    expect(screen.getByRole('alert')).toHaveTextContent('The minimum cannot be greater than the maximum')
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()

    rerender(<MaterialResults {...common} loading={false} data={response} error="invalid-spacegroups" />)
    expect(screen.getByRole('alert')).toHaveTextContent('whole numbers from 1 to 230')
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('opens a result and advances pagination', () => {
    const onPage = vi.fn()
    const onSelect = vi.fn()
    render(
      <MaterialResults
        loading={false}
        data={response}
        error={null}
        onPage={onPage}
        onSelect={onSelect}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByText('PBEsol band gap')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /View LiFePO4/ }))
    expect(onSelect).toHaveBeenCalledWith('exp-train-1')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(onPage).toHaveBeenCalledWith(2)
  })
})
