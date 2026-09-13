import { fireEvent, render, screen } from '../test/render'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_QUERY } from '../lib/query'
import { AdvancedFilters } from './AdvancedFilters'


describe('AdvancedFilters', () => {
  it('applies formula and dataset filters through the controlled query contract', () => {
    const onChange = vi.fn()
    render(
      <AdvancedFilters query={DEFAULT_QUERY} onChange={onChange} />,
    )

    fireEvent.change(screen.getByLabelText('Formula, chemical system or material ID'), { target: { value: 'LiFePO4' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ formula: 'LiFePO4', page: 1 }))

    fireEvent.click(screen.getByRole('button', { name: 'Experimental' }))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ datasets: ['experimental'], page: 1 }))

    fireEvent.change(screen.getByLabelText('Stability'), { target: { value: 'stable' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ stability: 'stable', page: 1 }))

  })

  it('marks an inverted numeric range before it reaches search', () => {
    render(<AdvancedFilters query={{ ...DEFAULT_QUERY, gapMin: 5, gapMax: 1 }} onChange={vi.fn()} />)

    expect(screen.getByText('Minimum must not exceed maximum')).toBeVisible()
    expect(screen.getAllByRole('spinbutton', { name: /Min|Max/ }).slice(0, 2).every((input) => input.getAttribute('aria-invalid') === 'true')).toBe(true)
  })
})
