import { Box, Cuboid, Maximize2 } from 'lucide-react';

export default function ModelViewer3D({ job }) {
  const geometry = job?.result?.geometry?.geometry || job?.result?.geometry || {};
  const x = geometry.length_x_mm || geometry.width || geometry.x;
  const y = geometry.width_y_mm || geometry.depth || geometry.y;
  const z = geometry.height_z_mm || geometry.height || geometry.z;
  return <div className="model-viewer"><div className="viewer-grid" /><div className="model-stage"><div className="model-shadow" /><div className="model-cube"><span /><span /><span /><span /><i /><b /></div><div className="axis axis-x">X</div><div className="axis axis-y">Y</div><div className="axis axis-z">Z</div></div><div className="viewer-toolbar"><span><Cuboid size={14} /> {job ? 'ANALYZED MESH' : 'NO MODEL LOADED'}</span><button title="Развернуть"><Maximize2 size={14} /></button></div><div className="dimensions"><span><small>X</small>{x ? `${Number(x).toFixed(1)} mm` : '—'}</span><span><small>Y</small>{y ? `${Number(y).toFixed(1)} mm` : '—'}</span><span><small>Z</small>{z ? `${Number(z).toFixed(1)} mm` : '—'}</span></div><div className="model-caption"><Box size={14} /> {job?.filename || 'Ожидается загрузка STL / 3MF / OBJ'}</div></div>;
}
