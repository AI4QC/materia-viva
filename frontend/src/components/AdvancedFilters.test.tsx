import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_QUERY } from '../lib/query'
import { AdvancedFilters } from './AdvancedFilters'


describe('AdvancedFilters', () => {
  it('submits formula and dataset filters through the controlled query contract', () => {
    const onChange = vi.fn()
    const onApply = vi.fn()
    render(
      <AdvancedFilters query={DEFAULT_QUERY} onChange={onChange} onApply={onApply} />,
    )

    fireEvent.change(screen.getByLabelText('化学式、化学体系或材料 ID'), { target: { value: 'LiFePO4' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ formula: 'LiFePO4', page: 1 }))

    fireEvent.click(screen.getByLabelText('仅实验结构'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ datasets: ['experimental'], page: 1 }))

    fireEvent.change(screen.getByLabelText('稳定性'), { target: { value: 'stable' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ stability: 'stable', page: 1 }))

    fireEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    expect(onApply).toHaveBeenCalledOnce()
  })
})
