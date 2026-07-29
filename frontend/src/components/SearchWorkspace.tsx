import type { ReactNode } from 'react'
import { Activity, Beaker, DatabaseZap, FlaskConical, Layers3 } from 'lucide-react'

import type { MaterialQuery } from '../lib/query'
import { useAtlasStats, useMaterials } from '../hooks/useMaterials'
import { AdvancedFilters } from './AdvancedFilters'
import { MaterialResults } from './MaterialResults'
import { PeriodicTable, type ElementSelection } from './PeriodicTable'

interface SearchWorkspaceProps {
  query: MaterialQuery
  onQueryChange: (query: MaterialQuery) => void
  onSelectMaterial: (materialId: string) => void
}

export function SearchWorkspace({ query, onQueryChange, onSelectMaterial }: SearchWorkspaceProps) {
  const { data, error, loading, refresh } = useMaterials(query)
  const stats = useAtlasStats()
  const selection: ElementSelection = Object.fromEntries([
    ...query.includedElements.map((symbol) => [symbol, 'include']),
    ...query.excludedElements.map((symbol) => [symbol, 'exclude']),
  ])
  const changeSelection = (next: ElementSelection) => {
    const includedElements = Object.entries(next).filter(([, state]) => state === 'include').map(([symbol]) => symbol)
    const excludedElements = Object.entries(next).filter(([, state]) => state === 'exclude').map(([symbol]) => symbol)
    onQueryChange({ ...query, includedElements, excludedElements, page: 1 })
  }

  return (
    <main>
      <section className="hero">
        <div className="hero__copy">
          <span className="eyebrow"><Activity size={13} /> Unified crystal universe · 01</span>
          <h1>汇聚全部晶体数据集，<br /><em>发现 822 万种独特结构。</em></h1>
          <p>跨数据源统一整合与去重，将 99,162 个实验可合成结构和 8,125,976 个候选结构汇入同一检索空间。</p>
        </div>
        <div className="hero__metrics" aria-label="数据集规模">
          <Metric icon={<FlaskConical />} value="99,162" label="实验收录" tone="mint" />
          <Metric icon={<Layers3 />} value="8.13M" label="候选收录" tone="orange" />
          <Metric icon={<DatabaseZap />} value={stats ? stats.total.toLocaleString() : '—'} label="统一去重索引" tone="plain" />
        </div>
      </section>

      <section className="element-lab" aria-labelledby="element-lab-title">
        <div className="section-ruler"><span>CHEMICAL SPACE</span><b>01—118</b></div>
        <div className="element-lab__heading">
          <div><span className="eyebrow">主筛选器</span><h2 id="element-lab-title">选择化学空间</h2></div>
          <div className="element-legend">
            <span><i data-tone="include" />包含</span><span><i data-tone="exclude" />排除</span><span><i />未选择</span>
          </div>
        </div>
        <PeriodicTable selection={selection} onChange={changeSelection} />
        <div className="element-lab__footer">
          <div className="selection-readout">
            <span>IN</span><strong>{[...query.includedElements].sort().join(' · ') || '任意元素'}</strong>
            <span>OUT</span><strong>{[...query.excludedElements].sort().join(' · ') || '无'}</strong>
          </div>
          <div className="mode-switch" aria-label="元素匹配方式">
            {([['all', '全部包含'], ['any', '包含任一'], ['exact', '精确体系']] as const).map(([value, label]) => (
              <button data-active={query.elementMode === value} key={value} onClick={() => onQueryChange({ ...query, elementMode: value, page: 1 })} type="button">{label}</button>
            ))}
          </div>
        </div>
      </section>

      <section className="catalog" aria-labelledby="catalog-title">
        <aside><AdvancedFilters query={query} onChange={onQueryChange} onApply={refresh} /></aside>
        <div className="catalog__results">
          <div className="results-toolbar">
            <div>
              <span className="eyebrow"><Beaker size={13} /> 匹配结构</span>
              <h2 id="catalog-title">{data ? data.total.toLocaleString() : '—'} <small>results</small></h2>
            </div>
            <label>排序
              <select value={`${query.sort}:${query.direction}`} onChange={(event) => {
                const [sort, direction] = event.target.value.split(':')
                onQueryChange({ ...query, sort, direction: direction as 'asc' | 'desc', page: 1 })
              }}>
                <option value="material_id:asc">材料编号</option>
                <option value="formula:asc">化学式 A–Z</option>
                <option value="pbes_gap:desc">带隙 高→低</option>
                <option value="density:desc">密度 高→低</option>
                <option value="n_atoms:asc">原子数 少→多</option>
                <option value="volume:asc">体积 小→大</option>
                <option value="formation_energy_per_atom:asc">形成能 低→高</option>
                <option value="energy_above_hull:asc">凸包能 低→高</option>
                <option value="spacegroup_number:asc">空间群编号</option>
              </select>
            </label>
          </div>
          <MaterialResults
            data={data}
            error={error}
            loading={loading}
            onPage={(page) => { onQueryChange({ ...query, page }); window.scrollTo({ top: document.querySelector('.catalog')?.getBoundingClientRect().top ?? 0, behavior: 'smooth' }) }}
            onRetry={refresh}
            onSelect={onSelectMaterial}
          />
        </div>
      </section>
    </main>
  )
}

function Metric({ icon, value, label, tone }: { icon: ReactNode; value: string; label: string; tone: string }) {
  return <div className="metric" data-tone={tone}><span>{icon}</span><strong>{value}</strong><small>{label}</small></div>
}
