import { useEffect, useRef, useState } from 'react';
import { Box, Cuboid, Maximize2, RotateCcw } from 'lucide-react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js';

function disposeObject(root) {
  root.traverse((object) => {
    object.geometry?.dispose();
    if (Array.isArray(object.material)) object.material.forEach((material) => material.dispose());
    else object.material?.dispose();
  });
}

export default function ModelViewer3D({ job, apiBase = '' }) {
  const mountRef = useRef(null);
  const controlsRef = useRef(null);
  const [loadState, setLoadState] = useState('empty');
  const [loadError, setLoadError] = useState('');
  const [dimensions, setDimensions] = useState(null);
  const geometryReport = job?.result?.geometry?.geometry || job?.result?.geometry || {};
  const x = geometryReport.length_x_mm || geometryReport.width || geometryReport.x;
  const y = geometryReport.width_y_mm || geometryReport.depth || geometryReport.y;
  const z = geometryReport.height_z_mm || geometryReport.height || geometryReport.z;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#0a1220');
    const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 10000);
    camera.position.set(150, 130, 170);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xd7efff, 0x172033, 2.1));
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
    keyLight.position.set(100, 150, 120);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0x50d9ec, 0.8);
    fillLight.position.set(-100, 40, -80);
    scene.add(fillLight);

    const grid = new THREE.GridHelper(200, 20, 0x3b6073, 0x203348);
    grid.position.y = -0.01;
    scene.add(grid);
    const axes = new THREE.AxesHelper(75);
    scene.add(axes);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controlsRef.current = controls;

    let model = null;
    let frameId;
    let disposed = false;
    const resize = () => {
      if (!mount.clientWidth || !mount.clientHeight) return;
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);

    const render = () => {
      if (disposed) return;
      frameId = requestAnimationFrame(render);
      controls.update();
      renderer.render(scene, camera);
    };
    render();

    const loadModel = async () => {
      if (!job?.job_id) {
        setLoadState('empty');
        setDimensions(null);
        return;
      }
      setLoadState('loading');
      setLoadError('');
      const extension = (job.filename || '').split('.').pop()?.toLowerCase();
      try {
        const response = await fetch(`${apiBase}/api/v1/jobs/${encodeURIComponent(job.job_id)}/model`);
        if (!response.ok) throw new Error(`Не удалось получить файл модели (${response.status})`);
        const buffer = await response.arrayBuffer();
        if (disposed) return;

        if (extension === 'stl') {
          const geometry = new STLLoader().parse(buffer);
          geometry.computeVertexNormals();
          model = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x53d8e8, metalness: 0.22, roughness: 0.38, side: THREE.DoubleSide }));
        } else if (extension === 'obj') {
          const text = new TextDecoder().decode(buffer);
          model = new OBJLoader().parse(text);
          model.traverse((object) => {
            if (object.isMesh) {
              object.material = new THREE.MeshStandardMaterial({ color: 0x53d8e8, metalness: 0.18, roughness: 0.42, side: THREE.DoubleSide });
              object.geometry.computeVertexNormals();
            }
          });
        } else if (extension === '3mf') {
          model = new ThreeMFLoader().parse(buffer);
          model.traverse((object) => {
            if (object.isMesh) {
              object.material = new THREE.MeshStandardMaterial({ color: 0x53d8e8, metalness: 0.18, roughness: 0.42, side: THREE.DoubleSide });
              object.geometry.computeVertexNormals();
            }
          });
        } else {
          throw new Error('Предпросмотр поддерживает STL, OBJ и 3MF.');
        }

        const bounds = new THREE.Box3().setFromObject(model);
        const size = bounds.getSize(new THREE.Vector3());
        const originalDimensions = { x: size.x, y: size.y, z: size.z };
        const center = bounds.getCenter(new THREE.Vector3());
        model.position.sub(center);
        const maxDimension = Math.max(size.x, size.y, size.z) || 1;
        const scale = 100 / maxDimension;
        model.scale.setScalar(scale);
        const scaledSize = size.clone().multiplyScalar(scale);
        const scaledBounds = new THREE.Box3().setFromObject(model);
        const scaledCenter = scaledBounds.getCenter(new THREE.Vector3());
        model.position.x -= scaledCenter.x;
        model.position.z -= scaledCenter.z;
        model.position.y -= scaledBounds.min.y;
        scene.add(model);
        grid.scale.setScalar(Math.max(1, maxDimension / 100));
        grid.position.y = -0.02;
        axes.scale.setScalar(Math.max(1, maxDimension / 100));
        controls.target.set(0, scaledSize.y / 2, 0);
        const span = Math.max(scaledSize.x, scaledSize.y, scaledSize.z, 1);
        camera.position.set(span * 1.55, span * 1.25, span * 1.7);
        camera.near = Math.max(span / 1000, 0.001);
        camera.far = span * 100;
        camera.updateProjectionMatrix();
        controls.update();
        setDimensions(originalDimensions);
        setLoadState('ready');
      } catch (error) {
        if (!disposed) {
          setLoadError(error.message || 'Ошибка загрузки 3D-модели');
          setLoadState('error');
        }
      }
    };
    loadModel();

    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      observer.disconnect();
      controls.dispose();
      controlsRef.current = null;
      if (model) disposeObject(model);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [job?.job_id, job?.filename, apiBase]);

  const resetView = () => {
    const controls = controlsRef.current;
    if (!controls) return;
    controls.reset();
  };

  const displayed = dimensions || { x: Number(x) || null, y: Number(y) || null, z: Number(z) || null };
  return (
    <div className="model-viewer">
      <div className="model-canvas-wrap">
        <div ref={mountRef} className="model-canvas" aria-label="Интерактивный 3D-предпросмотр модели" />
        {loadState !== 'ready' && <div className={`model-overlay ${loadState === 'error' ? 'model-overlay-error' : ''}`}>
          {!job?.job_id ? <><Box size={22} /><b>Загрузите модель для предпросмотра</b><span>STL · OBJ · 3MF</span></> : loadState === 'loading' ? <><span className="model-loader" /><b>Загрузка 3D-модели…</b></> : <><Box size={22} /><b>{loadError}</b></>}
        </div>}
        <div className="coordinate-legend"><span><i className="coord-x" />X</span><span><i className="coord-y" />Y</span><span><i className="coord-z" />Z</span><small>мм · система координат модели</small></div>
        <button className="model-reset" onClick={resetView} title="Сбросить вид" aria-label="Сбросить вид"><RotateCcw size={14} /></button>
      </div>
      <div className="viewer-toolbar"><span><Cuboid size={14} /> {loadState === 'ready' ? 'ЗАГРУЖЕННАЯ МОДЕЛЬ' : job ? 'ЗАГРУЗКА МОДЕЛИ' : 'МОДЕЛЬ НЕ ЗАГРУЖЕНА'}</span><button title="Сбросить вид" onClick={resetView}><Maximize2 size={14} /></button></div>
      <div className="dimensions"><span><small>X</small>{displayed.x ? `${Number(displayed.x).toFixed(1)} mm` : '—'}</span><span><small>Y</small>{displayed.y ? `${Number(displayed.y).toFixed(1)} mm` : '—'}</span><span><small>Z</small>{displayed.z ? `${Number(displayed.z).toFixed(1)} mm` : '—'}</span></div>
      <div className="model-caption"><Box size={14} /> {job?.filename || 'Ожидается загрузка STL / 3MF / OBJ'}</div>
    </div>
  );
}
