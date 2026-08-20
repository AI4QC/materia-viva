import { fireEvent, render, screen, waitFor } from './test/render'
import { beforeEach, expect, test, vi } from 'vitest'

import App from './App'

vi.mock('./hooks/useMaterials', () => ({
  useAtlasStats: () => ({
    total: 13_504_703,
    datasets: { experimental: 357_124, candidate: 13_147_579 },
    property_counts: {},
    property_rows: 121_106_364,
    curve_count: 1_198_897,
    ovito_available: true,
  }),
  useMaterials: () => ({
    data: {
      items: [], total: 6_219_302, page: 1, page_size: 24, pages: 259_138,
      facets: { datasets: { experimental: 99_162, candidate: 6_120_140 } },
    },
    error: null,
    loading: false,
    refresh: vi.fn(),
  }),
}))

beforeEach(() => {
  window.localStorage.clear()
  delete document.documentElement.dataset.theme
})

test('presents the database as MateriaViva with a unified deduplicated-data promise', () => {
  render(<App />)

  expect(screen.getByRole('link', { name: 'MateriaViva home' })).toBeInTheDocument()
  expect(screen.getAllByText('MateriaViva').length).toBeGreaterThan(0)
  expect(screen.getAllByText('MateriaViva').length).toBeGreaterThan(0)
  // Driven by the mocked /api/stats payload, never by a literal in the copy:
  // hardcoded figures here silently went stale every time the pool grew.
  expect(screen.getByRole('heading', {
    name: /Every crystal dataset in one place,\s*discover 13\.5 million unique structures\./,
  })).toBeInTheDocument()
  expect(
    screen.getByText(/357,124 experimental and 13,147,579 candidate structures/),
  ).toBeInTheDocument()
  expect(screen.getByText(/121\.1 million cross-database property records/)).toBeInTheDocument()
  expect(screen.getByText('357,124')).toBeInTheDocument()
  expect(screen.getByText('13,147,579')).toBeInTheDocument()
  expect(screen.queryByText('99,162')).not.toBeInTheDocument()
  expect(screen.queryByText('8.13M')).not.toBeInTheDocument()
  expect(screen.queryByText(/CSAgent/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/Materials Atlas/i)).not.toBeInTheDocument()
})

test('switches from the night theme to the day theme and remembers it', async () => {
  render(<App />)

  fireEvent.click(screen.getByRole('button', { name: 'Switch to light mode' }))

  await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'light'))
  expect(window.localStorage.getItem('mv-theme')).toBe('light')
  expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument()
})

test('starts in English and switches the interface to Chinese on request', async () => {
  render(<App />)

  expect(screen.getByRole('heading', {
    name: /Every crystal dataset in one place,/,
  })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: '切换到中文' }))

  await waitFor(() => expect(screen.getByRole('heading', {
    name: /汇聚全部晶体数据集，/,
  })).toBeInTheDocument())
  expect(window.localStorage.getItem('mv-lang')).toBe('zh')
  expect(document.documentElement).toHaveAttribute('lang', 'zh-CN')
  expect(screen.getByRole('button', { name: 'Switch to English' })).toBeInTheDocument()
})

test('restores the stored day theme on the next visit', async () => {
  window.localStorage.setItem('mv-theme', 'light')

  render(<App />)

  await waitFor(() => expect(document.documentElement).toHaveAttribute('data-theme', 'light'))
  expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument()
})
