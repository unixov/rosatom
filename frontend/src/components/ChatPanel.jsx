import { useEffect, useRef, useState } from 'react';
import { Bot, LoaderCircle, Paperclip, Send, Sparkles, UserRound } from 'lucide-react';

const API = '';

export default function ChatPanel({ job, onSelectJob, onAction }) {
  const [messages, setMessages] = useState([{ role: 'assistant', text: 'Здравствуйте. Я помогу подготовить модель к печати, подобрать параметры и проверить парк оборудования.' }]);
  const [value, setValue] = useState('');
  const [sending, setSending] = useState(false);
  const [attachedFile, setAttachedFile] = useState(null);
  const fileRef = useRef(null);
  const endRef = useRef(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages]);
  const send = async (preset) => {
    const text = (preset || value).trim();
    if (!text || sending) return;
    setValue(''); setMessages(current => [...current, { role: 'user', text: attachedFile ? `${text} [${attachedFile.name}]` : text }]); setSending(true);
    try {
      const requestBody = attachedFile ? (() => {
        const body = new FormData();
        body.append('message', text);
        body.append('file', attachedFile);
        return body;
      })() : JSON.stringify({ message: text, job_id: job?.job_id || null });
      const response = await fetch(`${API}/api/v1/${attachedFile ? 'chat/with-model' : 'chat'}`, { method: 'POST', headers: attachedFile ? undefined : { 'Content-Type': 'application/json' }, body: requestBody });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Не удалось отправить сообщение');
      const plan = data.plan;
      const planText = plan
        ? `\n\nПлан: ${plan.mode || '3D'} · ${plan.material || 'PLA'} · профиль ${plan.profile || 'standard'}\nОриентация: X ${plan.orientation?.x ?? 0}°, Y ${plan.orientation?.y ?? 0}°, Z ${plan.orientation?.z ?? 0}°\nРаскладка: ${plan.arrangement?.copies ?? 1} коп. · ${plan.arrangement?.spacing_mm ?? 0} мм\nОбоснование: ${plan.reasoning || 'не указано'}`
        : '';
      const sourceText = data.llm_configured
        ? `\nИсточник: настоящая OpenAI-compatible LLM (${data.planner_source}).`
        : '\nИсточник: локальный fallback planner. Настройте LLM_API_URL и LLM_API_KEY в .env.';
      setMessages(current => [...current, { role: 'assistant', text: `${data.message}${sourceText}${planText}` }]);
      (data.actions || []).forEach(onAction);
      const createdJobId = data.job_id || data.job?.job_id;
      if (createdJobId && createdJobId !== job?.job_id) onSelectJob(createdJobId);
    } catch (error) { setMessages(current => [...current, { role: 'assistant', text: `Не удалось обработать запрос: ${error.message}` }]); }
    finally { setSending(false); setAttachedFile(null); }
  };
  return <div className="chat-panel"><div className="chat-context"><Sparkles size={14} /> AI-ассистент подключён к оркестратору</div>{attachedFile && <div className="chat-attachment"><Paperclip size={13} /> {attachedFile.name}</div>}<div className="chat-messages">{messages.map((message, index) => <div className={`chat-message message-${message.role}`} key={`${message.role}-${index}`}><span className="message-avatar">{message.role === 'assistant' ? <Bot size={14} /> : <UserRound size={14} />}</span><span>{message.text}</span></div>)}{sending && <div className="chat-message message-assistant"><span className="message-avatar"><Bot size={14} /></span><LoaderCircle className="spin" size={15} /></div>}<div ref={endRef} /></div><div className="chat-suggestions"><button onClick={() => send('Покажи статус текущей задачи')}>Статус задачи</button><button onClick={() => send('Покажи принтеры флота')}>Парк принтеров</button></div><form className="chat-input" onSubmit={e => { e.preventDefault(); send(); }}><input ref={fileRef} type="file" accept=".stl,.3mf,.obj" hidden onChange={e => setAttachedFile(e.target.files?.[0] || null)} /><button type="button" className="attach-button" onClick={() => fileRef.current?.click()} aria-label="Прикрепить модель"><Paperclip size={16} /></button><input value={value} onChange={e => setValue(e.target.value)} placeholder={attachedFile ? 'Опишите задачу для прикреплённой модели…' : 'Спросите об инженерной задаче…'} disabled={sending} /><button type="submit" disabled={!value.trim() || sending} aria-label="Отправить"><Send size={16} /></button></form></div>;
}
