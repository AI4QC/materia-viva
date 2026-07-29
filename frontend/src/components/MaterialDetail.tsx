import { useEffect, useState } from 'react'
import { ArrowDownToLine, Database, FlaskConical, X } from 'lucide-react'

import { getMaterial, getStructure, type CrystalStructure, type MaterialDetailRecord } from '../api/client'
import { useI18n } from '../i18n'
import { CrystalViewer } from './CrystalViewer'

interface MaterialDetailProps {
  materialId: string
  onClose: () => void
}

export function MaterialDetail({ materialId, onClose }: MaterialDetailProps) {
  const { t } = useI18n()
  const [material, setMaterial] = useState<MaterialDetailRecord | null>(null)
  const [structure, setStructure] = useState<CrystalStructure | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setMaterial(null)
    setStructure(null)
    setError(null)
    Promise.all([getMaterial(materialId, controller.signal), getStructure(materialId, controller.signal)])
      .then(([nextMaterial, nextStructure]) => { setMaterial(nextMaterial); setStructure(nextStructure) })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setError(reason instanceof Error ? reason.message : t('detail.loadFailed'))
      })
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      controller.abort()
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [materialId, onClose, t])

  return (
    <div className="detail-shell" role="dialog" aria-modal="true" aria-label={t('detail.label')}>
      <button className="detail-close" aria-label={t('detail.close')} onClick={onClose} type="button"><X /></button>
      {error ? (
        <div className="detail-state" role="alert"><strong>{t('detail.workbenchFailed')}</strong><p>{error}</p></div>
      ) : !material || !structure ? (
        <div className="detail-state"><span className="scanner" /><strong>{t('detail.parsing')}</strong><p>{materialId}</p></div>
      ) : (
        <article className="detail-workbench">
          <header className="detail-heading">
            <div>
              <span className={`source-badge source-badge--${material.dataset}`}>
                {material.is_experimental ? <FlaskConical size={13} /> : <Database size={13} />}
                {material.is_experimental ? t('badge.experimental') : t('badge.candidate')}
              </span>
              <h1 aria-label={material.formula}><Formula value={material.formula} /></h1>
              <p>{material.material_id} <i /> {material.chemical_system}</p>
            </div>
            <a className="download-button" href={`/api/materials/${encodeURIComponent(materialId)}/cif`} download>
              <ArrowDownToLine size={16} /> {t('detail.downloadCif')}
            </a>
          </header>

          <div className="detail-layout">
            <CrystalViewer materialId={materialId} structure={structure} />
            <aside className="material-inspector">
              <div className="inspector-ruler"><span>MATERIAL RECORD</span><b>{material.material_id}</b></div>
              <PropertySection title={t('detail.basic')}>
                <Property label={t('detail.spacegroup')} value={material.spacegroup_symbol && material.spacegroup_number ? `${material.spacegroup_symbol} · ${material.spacegroup_number}` : material.spacegroup_number} />
                <Property label={t('detail.crystalSystem')} value={material.crystal_system} />
                <Property label={t('detail.gap')} value={unit(material.pbes_gap, 'eV', 3)} />
                <Property label={t('detail.density')} value={unit(material.density, 'g cm⁻³', 3)} />
                <Property label={t('detail.atoms')} value={material.n_atoms} />
                <Property label={t('detail.volume')} value={unit(material.volume ?? structure.lattice.volume, 'Å³', 3)} />
              </PropertySection>
              <PropertySection title={t('detail.lattice')}>
                <Property label="a / b / c" value={`${fixed(material.lattice_a ?? structure.lattice.a)} / ${fixed(material.lattice_b ?? structure.lattice.b)} / ${fixed(material.lattice_c ?? structure.lattice.c)} Å`} wide />
                <Property label="α / β / γ" value={`${fixed(material.lattice_alpha ?? structure.lattice.alpha, 2)} / ${fixed(material.lattice_beta ?? structure.lattice.beta, 2)} / ${fixed(material.lattice_gamma ?? structure.lattice.gamma, 2)}°`} wide />
              </PropertySection>
              <PropertySection title={t('detail.composition')}>
                <div className="element-tags">{material.elements.map((element) => <span key={element}>{element}</span>)}</div>
              </PropertySection>
              <PropertySection title={t('detail.provenance')}>
                <p className="provenance">{material.source_split} · row {material.source_index}</p>
                <p className="provenance-note">{t('detail.provenanceNote')}</p>
              </PropertySection>
            </aside>
          </div>
        </article>
      )}
    </div>
  )
}

function PropertySection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="property-section"><h2>{title}</h2><div className="property-section__grid">{children}</div></section>
}

function Property({ label, value, wide = false }: { label: string; value: string | number | null | undefined; wide?: boolean }) {
  return <dl className={wide ? 'wide' : ''}><dt>{label}</dt><dd>{value ?? '—'}</dd></dl>
}

function Formula({ value }: { value: string }) {
  return <>{value.split(/(\d+(?:\.\d+)?)/g).map((part, index) => /^\d/.test(part) ? <sub key={index}>{part}</sub> : part)}</>
}

function fixed(value: number | null | undefined, digits = 3) {
  return value == null ? '—' : value.toFixed(digits)
}

function unit(value: number | null | undefined, suffix: string, digits: number) {
  return value == null ? '—' : `${value.toFixed(digits)} ${suffix}`
}
