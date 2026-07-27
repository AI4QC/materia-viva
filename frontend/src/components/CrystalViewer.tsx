import { lazy, Suspense, useMemo, useState } from 'react'
import { Box, Camera, ImageOff, Layers3, Rotate3D } from 'lucide-react'

import type { CrystalStructure } from '../api/client'

const InteractiveCrystal = lazy(() => import('./InteractiveCrystal').then((module) => ({ default: module.InteractiveCrystal })))

interface CrystalViewerProps {
  materialId: string
  structure: CrystalStructure
}

type View = 'isometric' | 'front' | 'top'
type Representation = 'ball_stick' | 'spacefill'

export function CrystalViewer({ materialId, structure }: CrystalViewerProps) {
  const [mode, setMode] = useState<'ovito' | 'interactive'>('ovito')
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
    <section className="crystal-viewer" aria-label="晶体结构查看器">
      <div className="viewer-tabs" role="tablist" aria-label="渲染引擎">
        <button role="tab" aria-selected={mode === 'ovito'} onClick={() => setMode('ovito')} type="button">
          <span className="engine-live" /> OVITO render
        </button>
        <button role="tab" aria-selected={mode === 'interactive'} aria-label="交互式 3D" onClick={() => setMode('interactive')} type="button">
          <Rotate3D size={14} /> Interactive 3D
        </button>
      </div>

      <div className="viewer-stage">
        {mode === 'ovito' ? (
          <>
            {!renderLoaded && !renderFailed && <div className="viewer-loading"><i /><span>OVITO 正在生成光线追踪图像</span></div>}
            {!renderFailed && (
              <img
                key={renderUrl}
                src={renderUrl}
                alt={`${structure.formula} 的 OVITO 晶体结构渲染`}
                onLoad={() => setRenderLoaded(true)}
                onError={() => setRenderFailed(true)}
              />
            )}
            {renderFailed && (
              <div className="viewer-unavailable" role="alert">
                <ImageOff size={28} />
                <strong>OVITO 渲染暂不可用</strong>
                <p>可以继续使用浏览器内的交互式结构视图。</p>
                <button type="button" onClick={() => setMode('interactive')}>切换到交互视图</button>
              </div>
            )}
            <span className="viewer-engine-label">OVITO · TACHYON</span>
          </>
        ) : (
          hasWebGL ? (
            <Suspense fallback={<div className="viewer-loading"><i /><span>载入交互式场景</span></div>}>
              <InteractiveCrystal structure={structure} showCell={showCell} representation={representation} />
            </Suspense>
          ) : (
            <div className="viewer-unavailable" role="status">
              <span>WEBGL OFFLINE</span>
              <strong>当前浏览器无法启动 WebGL</strong>
              <p>仍可使用上方 OVITO 高质量渲染浏览结构。</p>
            </div>
          )
        )}
      </div>

      <div className="viewer-controls">
        <ControlGroup icon={<Camera size={14} />} label="视角">
          {([['isometric', '等轴视图'], ['front', '前视图'], ['top', '顶视图']] as const).map(([value, label]) => (
            <button aria-label={label} data-active={view === value} key={value} onClick={() => updateRender(() => setView(value))} type="button">{label.slice(0, 1)}</button>
          ))}
        </ControlGroup>
        <ControlGroup icon={<Box size={14} />} label="模型">
          <select aria-label="结构表示" value={representation} onChange={(event) => updateRender(() => setRepresentation(event.target.value as Representation))}>
            <option value="ball_stick">球棍</option>
            <option value="spacefill">空间填充</option>
          </select>
        </ControlGroup>
        <ControlGroup icon={<Layers3 size={14} />} label="晶胞">
          <select aria-label="超晶胞" value={supercell} onChange={(event) => updateRender(() => setSupercell(event.target.value))}>
            <option value="1,1,1">1 × 1 × 1</option>
            <option value="2,2,2">2 × 2 × 2</option>
            <option value="3,3,3">3 × 3 × 3</option>
          </select>
        </ControlGroup>
        <label className="viewer-toggle"><input type="checkbox" checked={showCell} onChange={(event) => updateRender(() => setShowCell(event.target.checked))} /><span>晶胞边界</span></label>
        <label className="viewer-quality">质量<select value={quality} onChange={(event) => updateRender(() => setQuality(event.target.value as 'preview' | 'high'))}><option value="preview">PREVIEW</option><option value="high">HIGH</option></select></label>
      </div>
    </section>
  )
}

function ControlGroup({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return <div className="viewer-control"><span>{icon}{label}</span><div>{children}</div></div>
}
