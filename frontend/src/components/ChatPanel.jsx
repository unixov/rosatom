import { useEffect, useRef, useState } from 'react';
import { Bot, LoaderCircle, Send, Sparkles, UserRound } from 'lucide-react';

const API = '';

export default function ChatPanel({ job, onSelectJob, onAction }) {
  const [messages, setMessages] = useState([{ role: 'assistant', text: 'Здравствуйте. Я помогу подготовить модель к печати, подобрать параметры и проверить парк оборудования.' }]);
  const [value, setValue] = useState('');
  const [sending, setSending] = useState(false);
  const endRef = useRef(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages]);
  const send = async (preset) => {
    const text = (preset || value).trim();
    if (!text || sending) return;
    setValue(''); setMessages(current => [...current, { role: 'user', text }]); setSending(true);
    try {
      const response = await fetch(`${API}/api/v1/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text, job_id: job?.job_id || null }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Не удалось отправить сообщение');
      setMessages(current => [...current, { role: 'assistant', text: data.message }]);
      (data.actions || []).forEach(onAction);
      if (data.job_id && data.job_id !== job?.job_id) onSelectJob(data.job_id);
    } catch (error) { setMessages(current => [...current, { role: 'assistant', text: `Не удалось обработать запрос: ${error.message}` }]); }
    finally { setSending(false); }
  };
  return <div className="chat-panel"><div className="chat-context"><Sparkles size={14} /> AI-ассистент подключён к оркестратору</div><div className="chat-messages">{messages.map((message, index) => <div className={`chat-message message-${message.role}`} key={`${message.role}-${index}`}><span className="message-avatar">{message.role === 'assistant' ? <Bot size={14} /> : <UserRound size={14} />}</span><span>{message.text}</span></div>)}{sending && <div className="chat-message message-assistant"><span className="message-avatar"><Bot size={14} /></span><LoaderCircle className="spin" size={15} /></div>}<div ref={endRef} /></div><div className="chat-suggestions"><button onClick={() => send('Покажи статус текущей задачи')}>Статус задачи</button><button onClick={() => send('Покажи принтеры флота')}>Парк принтеров</button></div><form className="chat-input" onSubmit={e => { e.preventDefault(); send(); }}><input value={value} onChange={e => setValue(e.target.value)} placeholder="Спросите об инженерной задаче…" disabled={sending} /><button type="submit" disabled={!value.trim() || sending} aria-label="Отправить"><Send size={16} /></button></form></div>;
}
