import { lazy, Suspense, useMemo, useState } from 'react'
import { Box, Camera, ImageOff, Layers3, Rotate3D } from 'lucide-react'

import type { CrystalStructure } from '../api/client'
import { useI18n } from '../i18n'
import { formulaText } from './Formula'

const InteractiveCrystal = lazy(() => import('./InteractiveCrystal').then((module) => ({ default: module.InteractiveCrystal })))

interface CrystalViewerProps {
  materialId: string
  structure: CrystalStructure
  /** From /api/stats. When false the server has no OVITO worker, so a render
   *  request can only fail — do not open on that tab and do not send one. */
  ovitoAvailable?: boolean
}

type View = 'isometric' | 'front' | 'top'
type Representation = 'ball_stick' | 'spacefill'

export function CrystalViewer({ materialId, structure, ovitoAvailable = true }: CrystalViewerProps) {
  const { t } = useI18n()
  const [mode, setMode] = useState<'ovito' | 'interactive'>(ovitoAvailable ? 'ovito' : 'interactive')
  const [view, setView] = useState<View>('isometric')
  const [representation, setRepresentation] = useState<Representation>('ball_stick')
  const [supercell, setSupercell] = useState('2,2,2')
  const [showCell, setShowCell] = useState(true)
  const [quality, setQuality] = useState<'preview' | 'high'>('preview')
  const [renderFailed, setRenderFailed] = useState(false)
  const [renderLoaded, setRenderLoaded] = useState(false)
  const hasWebGL = typeof window !== 'undefined' && (
    typeof window.WebGLRenderingContext !== 'undefined' ||
    typeof window.WebGL2RenderingContext !== 'undefined'
  )

  const renderUrl = useMemo(() => {
    const params = new URLSearchParams({ view, representation, supercell, show_cell: String(showCell), quality })
    return `/api/materials/${encodeURIComponent(materialId)}/render?${params}`
  }, [materialId, quality, representation, showCell, supercell, view])

  const updateRender = (callback: () => void) => {
    setRenderFailed(false)
    setRenderLoaded(false)
    callback()
  }

  return (
    <section className="crystal-viewer" aria-label={t('viewer.label')}>
      <div className="viewer-tabs" role="tablist" aria-label={t('viewer.engines')}>
        <button
          role="tab"
          aria-selected={mode === 'ovito'}
          onClick={() => setMode('ovito')}
          disabled={!ovitoAvailable}
          title={ovitoAvailable ? undefined : t('viewer.ovitoUnavailable')}
          type="button"
        >
          <span className="engine-live" /> OVITO render
        </button>
        <button role="tab" aria-selected={mode === 'interactive'} aria-label={t('viewer.interactive')} onClick={() => setMode('interactive')} type="button">
          <Rotate3D size={14} /> Interactive 3D
        </button>
      </div>

      <div className="viewer-stage">
        {mode === 'ovito' ? (
          <>
            {!renderLoaded && !renderFailed && <div className="viewer-loading"><i /><span>{t('viewer.ovitoLoading')}</span></div>}
            {!renderFailed && (
              <img
                key={renderUrl}
                src={renderUrl}
                alt={`${t('viewer.ovitoAlt')} ${formulaText(structure.formula)}`}
                onLoad={() => setRenderLoaded(true)}
                onError={() => setRenderFailed(true)}
              />
            )}
            {renderFailed && (
              <div className="viewer-unavailable" role="alert">
                <ImageOff size={28} />
                <strong>{t('viewer.ovitoFailed')}</strong>
                <p>{t('viewer.ovitoFailedBody')}</p>
                <button type="button" onClick={() => setMode('interactive')}>{t('viewer.switchInteractive')}</button>
              </div>
            )}
            <span className="viewer-engine-label">OVITO · TACHYON</span>
          </>
        ) : (
          hasWebGL ? (
            <Suspense fallback={<div className="viewer-loading"><i /><span>{t('viewer.sceneLoading')}</span></div>}>
              <InteractiveCrystal structure={structure} showCell={showCell} representation={representation}
                                  view={view} supercell={supercell} />
            </Suspense>
          ) : (
            <div className="viewer-unavailable" role="status">
              <span>WEBGL OFFLINE</span>
              <strong>{t('viewer.webglFailed')}</strong>
              <p>{t('viewer.webglFailedBody')}</p>
            </div>
          )
        )}
      </div>

      <div className="viewer-controls">
        <ControlGroup icon={<Camera size={14} />} label={t('viewer.camera')}>
          {([['isometric', 'viewer.isometric'], ['front', 'viewer.front'], ['top', 'viewer.top']] as const).map(([value, key]) => (
            <button aria-label={t(key)} data-active={view === value} key={value} onClick={() => updateRender(() => setView(value))} type="button">{t(key).slice(0, 1)}</button>
          ))}
        </ControlGroup>
        <ControlGroup icon={<Box size={14} />} label={t('viewer.model')}>
          <select aria-label={t('viewer.representation')} value={representation} onChange={(event) => updateRender(() => setRepresentation(event.target.value as Representation))}>
            <option value="ball_stick">{t('viewer.ballStick')}</option>
            <option value="spacefill">{t('viewer.spacefill')}</option>
          </select>
        </ControlGroup>
        <ControlGroup icon={<Layers3 size={14} />} label={t('viewer.cell')}>
          <select aria-label={t('viewer.supercell')} value={supercell} onChange={(event) => updateRender(() => setSupercell(event.target.value))}>
            <option value="1,1,1">1 × 1 × 1</option>
            <option value="2,2,2">2 × 2 × 2</option>
            <option value="3,3,3">3 × 3 × 3</option>
          </select>
        </ControlGroup>
        <label className="viewer-toggle"><input type="checkbox" checked={showCell} onChange={(event) => updateRender(() => setShowCell(event.target.checked))} /><span>{t('viewer.cellEdges')}</span></label>
        {/* Tachyon's ray-tracing quality. The live WebGL view has no equivalent, and a
            disabled select frozen on one value reads as broken rather than as inapplicable. */}
        {mode === 'ovito' && (
          <label className="viewer-quality">{t('viewer.quality')}<select value={quality} onChange={(event) => updateRender(() => setQuality(event.target.value as 'preview' | 'high'))}><option value="preview">PREVIEW</option><option value="high">HIGH</option></select></label>
        )}
      </div>
    </section>
  )
}

function ControlGroup({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return <div className="viewer-control"><span>{icon}{label}</span><div>{children}</div></div>
}
