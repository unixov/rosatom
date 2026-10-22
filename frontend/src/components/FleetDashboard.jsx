import { Cpu, LoaderCircle, RefreshCw, Thermometer, Wind } from 'lucide-react';

const statusLabels = { idle: 'ГОТОВ', ready: 'ГОТОВ', online: 'В СЕТИ', printing: 'ПЕЧАТЬ', paused: 'ПАУЗА', error: 'ОШИБКА', offline: 'НЕ В СЕТИ' };

export default function FleetDashboard({ printers = [], loading, onRefresh }) {
  if (loading && !printers.length) return <div className="fleet-loading"><LoaderCircle className="spin" size={21} /> Получение телеметрии принтеров…</div>;
  if (!printers.length) return <div className="fleet-empty"><Cpu size={19} /> Нет данных о принтерах. Проверьте подключение MCP-сервера.<button onClick={onRefresh}><RefreshCw size={14} /> Повторить</button></div>;
  return <div className="fleet-grid">
    {printers.map((printer, index) => {
      const id = printer.printer_id || printer.id || `PRINTER-${index + 1}`;
      const status = String(printer.status || 'offline').toLowerCase();
      const progress = Number(printer.progress || 0);
      return <article className={`printer-card printer-${status}`} key={id}>
        <div className="printer-top"><div className="printer-symbol"><Cpu size={19} /></div><span className={`printer-status status-${status}`}><i />{statusLabels[status] || status.toUpperCase()}</span></div>
        <b className="printer-id">{id}</b><span className="printer-type">{printer.type || '3D / 5D PRINTER'}</span>
        <div className="printer-metrics"><span><Thermometer size={14} /> NOZZLE <b>{printer.nozzle_temp ?? '—'}°</b></span><span><Wind size={14} /> BED <b>{printer.bed_temp ?? '—'}°</b></span></div>
        <div className="printer-progress"><span><small>{printer.current_file || 'ТЕКУЩАЯ ЗАДАЧА'}</small><b>{status === 'printing' ? `${progress.toFixed(0)}%` : status === 'idle' || status === 'ready' ? 'ОЖИДАНИЕ' : '—'}</b></span><i><em style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }} /></i></div>
      </article>;
    })}
  </div>;
}
