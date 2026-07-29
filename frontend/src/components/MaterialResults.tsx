import type { CSSProperties } from 'react'
import { ArrowLeft, ArrowRight, Atom, Database, TriangleAlert } from 'lucide-react'

import type { MaterialSummary, SearchResponse } from '../api/client'
import { useI18n } from '../i18n'

interface MaterialResultsProps {
  loading: boolean
  data: SearchResponse | null
  error: string | null
  onPage: (page: number) => void
  onSelect: (materialId: string) => void
  onRetry: () => void
}

export function MaterialResults({ loading, data, error, onPage, onSelect, onRetry }: MaterialResultsProps) {
  const { t, locale } = useI18n()

  if (loading && !data) return <LoadingResults />
  if (error) {
    return (
      <div className="results-state results-state--error" role="alert">
        <TriangleAlert size={28} />
        <h3>{t('results.errorTitle')}</h3>
        <p>{error}</p>
        <button type="button" onClick={onRetry}>{t('results.retry')}</button>
      </div>
    )
  }
  if (!data || data.items.length === 0) {
    return (
      <div className="results-state">
        <Atom size={32} />
        <h3>{t('results.emptyTitle')}</h3>
        <p>{t('results.emptyBody')}</p>
      </div>
    )
  }

  return (
    <section className="results" aria-label={t('results.label')} aria-busy={loading}>
      <div className="results__grid">
        {data.items.map((material, index) => (
          <MaterialCard key={material.material_id} material={material} index={index} onSelect={onSelect} locale={locale} />
        ))}
      </div>
      <nav className="pagination" aria-label={t('results.pagination')}>
        <button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)} type="button">
          <ArrowLeft size={16} /> {t('results.prev')}
        </button>
        <span><b>{data.page}</b> / {data.pages || 1}</span>
        <button disabled={data.page >= data.pages} onClick={() => onPage(data.page + 1)} type="button">
          {t('results.next')} <ArrowRight size={16} />
        </button>
      </nav>
    </section>
  )
}

interface MaterialCardProps {
  material: MaterialSummary
  index: number
  onSelect: (id: string) => void
  locale: string
}

function MaterialCard({ material, index, onSelect, locale }: MaterialCardProps) {
  const { t } = useI18n()
  return (
    <article className="material-card" style={{ '--card-index': index } as CSSProperties}>
      <div className="material-card__rail"><span>{String(index + 1).padStart(2, '0')}</span></div>
      <div className="material-card__body">
        <div className="material-card__topline">
          <span className={`source-badge source-badge--${material.dataset}`}>
            <Database size={12} /> {material.is_experimental ? t('badge.experimental') : t('badge.candidate')}
          </span>
          <span>{material.material_id}</span>
        </div>
        <button
          className="material-card__open"
          onClick={() => onSelect(material.material_id)}
          type="button"
          aria-label={`${t('results.view')} ${material.formula}`}
        >
          <Formula value={material.formula} />
          <span aria-hidden="true">↗</span>
        </button>
        <p className="material-card__chemsys">{material.chemical_system}</p>
        <dl className="property-strip">
          <div><dt>{t('card.spacegroup')}</dt><dd>{material.spacegroup_number ?? '—'}</dd></div>
          <div><dt>{t('card.atoms')}</dt><dd>{formatNumber(material.n_atoms, 0, locale)}</dd></div>
          <div><dt>{t('card.gap')}</dt><dd>{formatNumber(material.pbes_gap, 2, locale)} <small>eV</small></dd></div>
          <div><dt>{t('card.density')}</dt><dd>{formatNumber(material.density, 2, locale)}</dd></div>
        </dl>
      </div>
    </article>
  )
}

function Formula({ value }: { value: string }) {
  const parts = value.split(/(\d+(?:\.\d+)?)/g)
  return <h3 aria-label={value}>{parts.map((part, index) => /^\d/.test(part) ? <sub key={index}>{part}</sub> : part)}</h3>
}

function formatNumber(value: number | null | undefined, digits: number, locale: string) {
  return value === null || value === undefined ? '—' : value.toLocaleString(locale, { maximumFractionDigits: digits })
}

function LoadingResults() {
  const { t } = useI18n()
  return (
    <div className="results-loading" role="status">
      <span className="scanner" />
      <p>{t('results.loading')}</p>
      <div className="skeleton-grid">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</div>
    </div>
  )
}
