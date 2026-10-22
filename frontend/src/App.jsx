import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowDownToLine, ArrowUpRight, Bot, Check, ChevronDown,
  CircleAlert, Cpu, FileBox, FileCode2, Gauge, LoaderCircle, MessageCircle,
  Pause, Play, Plus, RefreshCw, Send, ShieldCheck, Sparkles, Upload,
  X, Zap,
} from 'lucide-react';
import ChatPanel from './components/ChatPanel.jsx';
import FleetDashboard from './components/FleetDashboard.jsx';
import GCodeViewer from './components/GCodeViewer.jsx';
import ModelViewer3D from './components/ModelViewer3D.jsx';
import './index.css';

const API = '';
const request = async (path, options = {}) => {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); message = body.detail || message; } catch { /* use status */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
};
const STEPS = [
  ['analyze_geometry', 'Анализ геометрии'],
  ['recommend_parameters', 'Подбор параметров'],
  ['select_printer', 'Проверка парка'],
  ['slice_model', 'Генерация G-code'],
  ['start_print', 'Запуск печати'],
];
const formatBytes = (bytes) => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export default function App() {
  const [job, setJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [printers, setPrinters] = useState([]);
  const [loadingFleet, setLoadingFleet] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [material, setMaterial] = useState('PLA');
  const [quality, setQuality] = useState('standard');
  const [printerId, setPrinterId] = useState('');
  const [startPrint, setStartPrint] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [toast, setToast] = useState('');
  const inputRef = useRef(null);
  const sourceRef = useRef(null);

  const refreshJobs = useCallback(async () => {
    try { setJobs(await request('/api/v1/jobs?limit=20')); } catch { /* API health banner handles outages */ }
  }, []);

  const refreshPrinters = useCallback(async () => {
    setLoadingFleet(true);
    try {
      const data = await request('/api/v1/printers');
      setPrinters(Array.isArray(data) ? data : data?.printers || []);
    } catch (e) { setError(`Не удалось получить телеметрию: ${e.message}`); }
    finally { setLoadingFleet(false); }
  }, []);

  useEffect(() => { refreshJobs(); refreshPrinters(); }, [refreshJobs, refreshPrinters]);
  useEffect(() => {
    if (!job?.job_id || ['succeeded', 'failed', 'cancelled'].includes(job.status)) return undefined;
    const source = new EventSource(`${API}/api/v1/jobs/${job.job_id}/events`);
    sourceRef.current = source;
    const update = async (event) => {
      try {
        const payload = JSON.parse(event.data);
        const current = await request(`/api/v1/jobs/${job.job_id}`);
        setJob(current);
        await refreshJobs();
        if (payload.event_type === 'job_succeeded') setToast('Задача завершена — G-code готов');
      } catch (e) { console.error('Job event processing failed', e); }
    };
    ['job_queued', 'job_started', 'step_started', 'step_finished', 'job_succeeded', 'job_failed', 'job_cancelled', 'job_cancelling'].forEach((name) => source.addEventListener(name, update));
    source.onerror = () => { /* EventSource reconnects automatically */ };
    return () => { source.close(); sourceRef.current = null; };
  }, [job?.job_id, job?.status, refreshJobs]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(''), 3800);
    return () => clearTimeout(timer);
  }, [toast]);

  const activeStep = useMemo(() => STEPS.findIndex(([id]) => id === job?.current_step), [job?.current_step]);
  const handleUpload = async (file) => {
    if (!file) return;
    setError('');
    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      body.append('material', material);
      body.append('quality', quality);
      body.append('printer_id', printerId);
      body.append('start_print', String(startPrint));
      const created = await request('/api/v1/jobs', { method: 'POST', body });
      setJob(created);
      await refreshJobs();
      setToast('Модель поставлена в очередь');
    } catch (e) { setError(e.message); }
    finally { setUploading(false); if (inputRef.current) inputRef.current.value = ''; }
  };
  const cancelJob = async () => {
    if (!job) return;
    try { setJob(await request(`/api/v1/jobs/${job.job_id}/cancel`, { method: 'POST' })); }
    catch (e) { setError(e.message); }
  };
  const loadJob = async (id) => {
    try { setJob(await request(`/api/v1/jobs/${id}`)); setError(''); }
    catch (e) { setError(e.message); }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="На главную"><span className="brand-mark"><Zap size={19} fill="currentColor" /></span><span><b>ROSATOM</b><small>PRINT ORCHESTRATOR</small></span></a>
        <nav className="top-nav"><a className="nav-active" href="#workspace">Рабочая область</a><a href="#fleet">Парк принтеров</a><a href="#history">История задач</a></nav>
        <div className="top-actions"><span className="system-status"><i /> SYSTEM ONLINE</span><button className="icon-button" title="Обновить данные" onClick={() => { refreshPrinters(); refreshJobs(); }}><RefreshCw size={17} /></button><div className="avatar">И</div></div>
      </header>

      <main id="workspace" className="workspace">
        <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> ИНЖЕНЕРНАЯ ПЛАТФОРМА <span className="eyebrow-dot">·</span> 3D / 5D MANUFACTURING</div><h1>Производство <span>под контролем.</span></h1><p>От цифровой модели до готовой детали — в едином инженерном контуре.</p></div><div className="heading-meta"><span className="meta-icon"><ShieldCheck size={19} /></span><span>ЗАЩИЩЁННЫЙ КОНТУР<small>Все системы в норме</small></span></div></div>

        {error && <div className="alert-banner"><CircleAlert size={17} /><span>{error}</span><button onClick={() => setError('')} aria-label="Закрыть"><X size={16} /></button></div>}
        <section className="stats-grid" aria-label="Сводка системы">
          <article className="stat-card"><div className="stat-top"><span>ПРИНТЕРЫ В СЕТИ</span><span className="stat-icon cyan"><Cpu size={17} /></span></div><div className="stat-value">{printers.length.toString().padStart(2, '0')}<small> / 08</small></div><div className="stat-foot"><i className="live-dot" /> {printers.filter(p => ['idle', 'ready', 'online'].includes(String(p.status).toLowerCase())).length} доступны для запуска</div><div className="stat-spark spark-cyan" /></article>
          <article className="stat-card"><div className="stat-top"><span>АКТИВНЫЕ ЗАДАЧИ</span><span className="stat-icon violet"><Activity size={17} /></span></div><div className="stat-value">{jobs.filter(j => ['queued', 'running', 'cancelling'].includes(j.status)).length.toString().padStart(2, '0')}<small> / 12</small></div><div className="stat-foot"><span className="spark-label">Очередь обновляется в реальном времени</span></div><div className="stat-spark spark-violet" /></article>
          <article className="stat-card"><div className="stat-top"><span>ВЫПОЛНЕНО СЕГОДНЯ</span><span className="stat-icon amber"><Gauge size={17} /></span></div><div className="stat-value">{jobs.filter(j => j.status === 'succeeded').length.toString().padStart(2, '0')}<small> задач</small></div><div className="stat-foot"><span className="positive">●</span> Завершённые задачи</div><div className="stat-spark spark-amber" /></article>
          <article className="stat-card"><div className="stat-top"><span>UPTIME СИСТЕМЫ</span><span className="stat-icon green"><ShieldCheck size={17} /></span></div><div className="stat-value">99.98<small>%</small></div><div className="stat-foot">API и очередь задач доступны</div><div className="stat-spark spark-green" /></article>
        </section>

        <div className="content-grid">
          <section className="panel production-panel">
            <div className="panel-header"><div><div className="panel-kicker"><span className="kicker-square" /> ПРОИЗВОДСТВО</div><h2>Новая задача печати</h2><p>Настройте параметры и загрузите 3D-модель для подготовки производства.</p></div><span className="panel-index">01 <span>/ 03</span></span></div>
            <div className="config-row">
              <label className="field"><span>МАТЕРИАЛ <span className="required">*</span></span><span className="select-wrap"><select value={material} onChange={e => setMaterial(e.target.value)}><option value="PLA">PLA · стандартный</option><option value="ABS">ABS · термостойкий</option><option value="PA12-CF">PA12-CF · композит</option><option value="PEEK">PEEK · высокотемпературный</option></select><ChevronDown size={15} /></span></label>
              <label className="field"><span>КАЧЕСТВО ПЕЧАТИ</span><span className="select-wrap"><select value={quality} onChange={e => setQuality(e.target.value)}><option value="draft">Черновое · быстро</option><option value="standard">Стандартное</option><option value="high">Высокое · детально</option></select><ChevronDown size={15} /></span></label>
              <label className="field"><span>ПРИНТЕР</span><span className="select-wrap"><select value={printerId} onChange={e => setPrinterId(e.target.value)}><option value="">Автоматический выбор</option>{printers.map(p => <option key={p.printer_id || p.id} value={p.printer_id || p.id}>{p.printer_id || p.id} · {p.status}</option>)}</select><ChevronDown size={15} /></span></label>
            </div>
            <button className={`toggle-row ${startPrint ? 'toggle-enabled' : ''}`} onClick={() => setStartPrint(v => !v)} aria-pressed={startPrint}><span className="toggle-icon"><Play size={15} /></span><span><b>Запустить печать автоматически</b><small>Отправить G-code на выбранный принтер после подготовки</small></span><span className={`switch ${startPrint ? 'switch-on' : ''}`}><i /></span></button>
            <div className="dropzone" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); handleUpload(e.dataTransfer.files[0]); }} onClick={() => !uploading && inputRef.current?.click()} role="button" tabIndex={0} onKeyDown={e => e.key === 'Enter' && inputRef.current?.click()}><input ref={inputRef} type="file" accept=".stl,.3mf,.obj" hidden onChange={e => handleUpload(e.target.files?.[0])} /><div className="upload-icon">{uploading ? <LoaderCircle className="spin" size={24} /> : <Upload size={23} />}</div><div className="drop-title">{uploading ? 'Загружаем модель…' : 'Перетащите 3D-модель сюда'}</div><div className="drop-subtitle">или <span>выберите файл на устройстве</span></div><div className="file-specs"><span>STL</span><span>3MF</span><span>OBJ</span><i /> МАКС. 100 MB</div></div>
            <div className="form-foot"><span><ShieldCheck size={14} /> Файл хранится в защищённом контуре</span><span>Поддерживаемые форматы: STL, 3MF, OBJ</span></div>
          </section>

          <section className="panel job-panel">
            <div className="panel-header compact"><div><div className="panel-kicker"><span className="kicker-square violet-square" /> МОНИТОРИНГ</div><h2>Статус задачи</h2></div><span className={`job-status ${job?.status || 'waiting'}`}><i />{job?.status ? ({ queued: 'В ОЧЕРЕДИ', running: 'В РАБОТЕ', succeeded: 'ГОТОВО', failed: 'ОШИБКА', cancelling: 'ОТМЕНА', cancelled: 'ОТМЕНЕНО', created: 'СОЗДАНА' }[job.status] || job.status.toUpperCase()) : 'ОЖИДАНИЕ'}</span></div>
            {job ? <><div className="job-file"><span className="file-icon"><FileBox size={19} /></span><span className="job-file-name"><b>{job.filename}</b><small>ID: {job.job_id?.slice(0, 8)} · {job.created_at ? new Date(job.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : 'сейчас'}</small></span>{!['succeeded', 'failed', 'cancelled'].includes(job.status) && <button className="cancel-button" onClick={cancelJob} title="Отменить задачу"><Pause size={15} /></button>}</div><div className="progress-heading"><span>ОБЩИЙ ПРОГРЕСС</span><b>{job.progress || 0}<small>%</small></b></div><div className="progress-track"><i style={{ width: `${Math.max(0, Math.min(job.progress || 0, 100))}%` }} /></div><div className="steps-list">{STEPS.map(([id, label], index) => { const done = (job.progress || 0) >= ([25, 40, 55, 80, 100][index]); const current = job.current_step === id; return <div className={`step-item ${done ? 'step-done' : ''} ${current ? 'step-current' : ''}`} key={id}><span className="step-marker">{done ? <Check size={12} /> : current ? <LoaderCircle className="spin" size={12} /> : <i />}</span><span>{label}</span>{current && <small>ВЫПОЛНЯЕТСЯ</small>}</div>; })}</div>{job.error && <div className="job-error"><CircleAlert size={15} />{job.error}</div>}{job.status === 'succeeded' && <div className="job-complete"><Check size={15} /> Модель обработана. G-code готов к скачиванию.</div>}{job.status === 'succeeded' && <a className="download-button" href={`${API}/api/v1/jobs/${job.job_id}/gcode`}><ArrowDownToLine size={16} /> Скачать G-code</a>}</> : <div className="empty-job"><div className="empty-ring"><Activity size={24} /></div><b>Задача не выбрана</b><span>Загрузите модель, чтобы начать обработку</span><div className="empty-lines"><i /><i /><i /></div></div>}
            {job?.result?.recommendation && <div className="recommendation"><div className="subsection-heading"><Sparkles size={15} /> РЕКОМЕНДАЦИЯ ПАРАМЕТРОВ</div><div className="param-chips">{Object.entries(job.result.recommendation.parameters || {}).slice(0, 5).map(([k, v]) => <span key={k}><small>{k.replaceAll('_', ' ')}</small><b>{String(v)}</b></span>)}</div></div>}
          </section>
        </div>

        <section id="fleet" className="panel fleet-panel"><div className="section-heading"><div><div className="panel-kicker"><span className="kicker-square green-square" /> ОБОРУДОВАНИЕ</div><h2>Парк принтеров</h2></div><button className="subtle-button" onClick={refreshPrinters} disabled={loadingFleet}>{loadingFleet ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} Обновить <ArrowUpRight size={14} /></button></div><FleetDashboard printers={printers} loading={loadingFleet} onRefresh={refreshPrinters} /></section>

        <section className="visual-grid"><div className="panel visual-panel"><div className="section-heading"><div><div className="panel-kicker"><span className="kicker-square cyan-square" /> ПРЕДПРОСМОТР</div><h2>3D-модель</h2></div><span className="mini-label">{job?.filename || 'ОЖИДАНИЕ ФАЙЛА'}</span></div><ModelViewer3D job={job} apiBase={API} /></div><div className="panel visual-panel"><div className="section-heading"><div><div className="panel-kicker"><span className="kicker-square amber-square" /> ПРОИЗВОДСТВЕННЫЕ ДАННЫЕ</div><h2>G-code и анализ</h2></div><span className="mini-label">{job?.status === 'succeeded' ? 'ГОТОВО' : 'ОЖИДАНИЕ'}</span></div><GCodeViewer job={job} apiBase={API} /></div></section>

        <section id="history" className="panel history-panel"><div className="section-heading"><div><div className="panel-kicker"><span className="kicker-square violet-square" /> ПРОИЗВОДСТВО</div><h2>Последние задачи</h2></div><button className="subtle-button" onClick={refreshJobs}>Обновить <RefreshCw size={14} /></button></div><div className="history-list">{jobs.length ? jobs.slice(0, 6).map(item => <button className={`history-row ${job?.job_id === item.job_id ? 'history-selected' : ''}`} key={item.job_id} onClick={() => loadJob(item.job_id)}><span className="history-file"><FileCode2 size={17} /></span><span className="history-name"><b>{item.filename}</b><small>{item.job_id.slice(0, 8)} · {item.created_at ? new Date(item.created_at).toLocaleString('ru-RU') : ''}</small></span><span className={`history-state state-${item.status}`}><i />{{ succeeded: 'Завершена', failed: 'Ошибка', running: 'В работе', queued: 'В очереди', cancelled: 'Отменена' }[item.status] || item.status}</span><span className="history-progress">{item.progress || 0}%</span><ArrowUpRight size={15} /></button>) : <div className="history-empty">Задач пока нет. Загрузите первую модель, чтобы начать.</div>}</div></section>
        <footer className="footer"><span>ROSATOM <b>·</b> PRINT ORCHESTRATOR</span><span>Инженерный контур аддитивного производства <i /> SYSTEM ONLINE</span><span>v1.0.0</span></footer>
      </main>
      <aside className={`chat-drawer ${chatOpen ? 'chat-open' : ''}`}><div className="chat-drawer-head"><div className="chat-bot"><Bot size={17} /></div><span><b>Инженерный ассистент</b><small>ROSATOM AI · ГОТОВ К РАБОТЕ</small></span><button className="icon-button" onClick={() => setChatOpen(false)} aria-label="Свернуть чат"><X size={17} /></button></div><ChatPanel job={job} onSelectJob={loadJob} printers={printers} onAction={(action) => { if (action === 'load_printers') refreshPrinters(); if (action === 'upload_model') inputRef.current?.click(); }} /></aside>
      {!chatOpen && <button className="chat-launcher" onClick={() => setChatOpen(true)} aria-label="Открыть ассистента"><MessageCircle size={20} /><span>ASSISTANT</span><Plus size={15} /></button>}
      {toast && <div className="toast"><Check size={16} />{toast}</div>}
    </div>
  );
}
