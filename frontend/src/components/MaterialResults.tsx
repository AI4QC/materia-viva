import type { CSSProperties } from 'react'
import { ArrowLeft, ArrowRight, Atom, Database, TriangleAlert } from 'lucide-react'

import type { MaterialSummary, SearchResponse } from '../api/client'

interface MaterialResultsProps {
  loading: boolean
  data: SearchResponse | null
  error: string | null
  onPage: (page: number) => void
  onSelect: (materialId: string) => void
  onRetry: () => void
}

export function MaterialResults({ loading, data, error, onPage, onSelect, onRetry }: MaterialResultsProps) {
  if (loading && !data) return <LoadingResults />
  if (error) {
    return (
      <div className="results-state results-state--error" role="alert">
        <TriangleAlert size={28} />
        <h3>检索链路中断</h3>
        <p>{error}</p>
        <button type="button" onClick={onRetry}>重新尝试</button>
      </div>
    )
  }
  if (!data || data.items.length === 0) {
    return (
      <div className="results-state">
        <Atom size={32} />
        <h3>没有命中结构</h3>
        <p>尝试减少包含元素，或清除一个数值范围。</p>
      </div>
    )
  }

  return (
    <section className="results" aria-label="材料检索结果" aria-busy={loading}>
      <div className="results__grid">
        {data.items.map((material, index) => (
          <MaterialCard key={material.material_id} material={material} index={index} onSelect={onSelect} />
        ))}
      </div>
      <nav className="pagination" aria-label="检索结果分页">
        <button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)} type="button">
          <ArrowLeft size={16} /> 上一页
        </button>
        <span><b>{data.page}</b> / {data.pages || 1}</span>
        <button disabled={data.page >= data.pages} onClick={() => onPage(data.page + 1)} type="button">
          下一页 <ArrowRight size={16} />
        </button>
      </nav>
    </section>
  )
}

function MaterialCard({ material, index, onSelect }: { material: MaterialSummary; index: number; onSelect: (id: string) => void }) {
  return (
    <article className="material-card" style={{ '--card-index': index } as CSSProperties}>
      <div className="material-card__rail"><span>{String(index + 1).padStart(2, '0')}</span></div>
      <div className="material-card__body">
        <div className="material-card__topline">
          <span className={`source-badge source-badge--${material.dataset}`}>
            <Database size={12} /> {material.is_experimental ? '实验结构' : '候选结构'}
          </span>
          <span>{material.material_id}</span>
        </div>
        <button
          className="material-card__open"
          onClick={() => onSelect(material.material_id)}
          type="button"
          aria-label={`查看 ${material.formula}`}
        >
          <Formula value={material.formula} />
          <span aria-hidden="true">↗</span>
        </button>
        <p className="material-card__chemsys">{material.chemical_system}</p>
        <dl className="property-strip">
          <div><dt>空间群</dt><dd>{material.spacegroup_number ?? '—'}</dd></div>
          <div><dt>原子数</dt><dd>{formatNumber(material.n_atoms, 0)}</dd></div>
          <div><dt>带隙</dt><dd>{formatNumber(material.pbes_gap, 2)} <small>eV</small></dd></div>
          <div><dt>密度</dt><dd>{formatNumber(material.density, 2)}</dd></div>
        </dl>
      </div>
    </article>
  )
}

function Formula({ value }: { value: string }) {
  const parts = value.split(/(\d+(?:\.\d+)?)/g)
  return <h3 aria-label={value}>{parts.map((part, index) => /^\d/.test(part) ? <sub key={index}>{part}</sub> : part)}</h3>
}

function formatNumber(value: number | null | undefined, digits: number) {
  return value === null || value === undefined ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

function LoadingResults() {
  return (
    <div className="results-loading" role="status">
      <span className="scanner" />
      <p>正在检索材料空间</p>
      <div className="skeleton-grid">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</div>
    </div>
  )
}
