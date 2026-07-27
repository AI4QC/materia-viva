import { useEffect, useState } from 'react'
import { ArrowDownToLine, Database, FlaskConical, X } from 'lucide-react'

import { getMaterial, getStructure, type CrystalStructure, type MaterialDetailRecord } from '../api/client'
import { CrystalViewer } from './CrystalViewer'

interface MaterialDetailProps {
  materialId: string
  onClose: () => void
}

export function MaterialDetail({ materialId, onClose }: MaterialDetailProps) {
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
        setError(reason instanceof Error ? reason.message : '无法载入材料详情')
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
  }, [materialId, onClose])

  return (
    <div className="detail-shell" role="dialog" aria-modal="true" aria-label="材料详情">
      <button className="detail-close" aria-label="关闭材料详情" onClick={onClose} type="button"><X /></button>
      {error ? (
        <div className="detail-state" role="alert"><strong>结构工作台载入失败</strong><p>{error}</p></div>
      ) : !material || !structure ? (
        <div className="detail-state"><span className="scanner" /><strong>正在解析晶体结构</strong><p>{materialId}</p></div>
      ) : (
        <article className="detail-workbench">
          <header className="detail-heading">
            <div>
              <span className={`source-badge source-badge--${material.dataset}`}>
                {material.is_experimental ? <FlaskConical size={13} /> : <Database size={13} />}
                {material.is_experimental ? '实验结构' : '候选结构'}
              </span>
              <h1 aria-label={material.formula}><Formula value={material.formula} /></h1>
              <p>{material.material_id} <i /> {material.chemical_system}</p>
            </div>
            <a className="download-button" href={`/api/materials/${encodeURIComponent(materialId)}/cif`} download>
              <ArrowDownToLine size={16} /> 下载 CIF
            </a>
          </header>

          <div className="detail-layout">
            <CrystalViewer materialId={materialId} structure={structure} />
            <aside className="material-inspector">
              <div className="inspector-ruler"><span>MATERIAL RECORD</span><b>{material.material_id}</b></div>
              <PropertySection title="基本性质">
                <Property label="空间群" value={material.spacegroup_symbol && material.spacegroup_number ? `${material.spacegroup_symbol} · ${material.spacegroup_number}` : material.spacegroup_number} />
                <Property label="晶系" value={material.crystal_system} />
                <Property label="带隙" value={unit(material.pbes_gap, 'eV', 3)} />
                <Property label="密度" value={unit(material.density, 'g cm⁻³', 3)} />
                <Property label="原子数" value={material.n_atoms} />
                <Property label="晶胞体积" value={unit(material.volume ?? structure.lattice.volume, 'Å³', 3)} />
              </PropertySection>
              <PropertySection title="晶格参数">
                <Property label="a / b / c" value={`${fixed(material.lattice_a ?? structure.lattice.a)} / ${fixed(material.lattice_b ?? structure.lattice.b)} / ${fixed(material.lattice_c ?? structure.lattice.c)} Å`} wide />
                <Property label="α / β / γ" value={`${fixed(material.lattice_alpha ?? structure.lattice.alpha, 2)} / ${fixed(material.lattice_beta ?? structure.lattice.beta, 2)} / ${fixed(material.lattice_gamma ?? structure.lattice.gamma, 2)}°`} wide />
              </PropertySection>
              <PropertySection title="元素组成">
                <div className="element-tags">{material.elements.map((element) => <span key={element}>{element}</span>)}</div>
              </PropertySection>
              <PropertySection title="数据溯源">
                <p className="provenance">{material.source_split} · row {material.source_index}</p>
                <p className="provenance-note">原始 CIF 按数据集来源原样压缩保存，索引字段可重新构建。</p>
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
