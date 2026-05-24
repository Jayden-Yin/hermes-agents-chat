/**
 * Hermes Chat — Main React Component (v0.2).
 *
 * Multi-agent chat UI with:
 *  • WeChat-style scroll-based lazy loading (50 initial, 30 per fetch)
 *  • Context boundary management (clear context = conversation divider)
 *  • Room cascade delete with proper confirmation modal
 *  • DOM recycling at 200 message cap
 */
import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';
import { initLang, getLang, setLang, t, availableLangs } from './i18n';

// ── Constants ──────────────────────────────────────────────────────────────

const API_BASE = '/api/plugins/hermes-chat';
// User profile stored on backend (plugin data dir), loaded on mount
const FIVE_MIN = 5 * 60 * 1000;
const INITIAL_LOAD = 50;
const PAGINATE_SIZE = 30;
const DOM_CAP = 200;

const AVATAR_COLORS = [
  '#e94d6b', '#f59e0b', '#10b981', '#6366f1', '#ec4899',
  '#06b6d4', '#84cc16', '#f43f5e', '#8b5cf6', '#14b8a6',
];

// ── Helpers ─────────────────────────────────────────────────────────────────

function avatarColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
}

// ── LocalStorage helpers ───────────────────────────────────────────────────

const AVATARS_KEY = 'hc_avatars';
const ALIAS_KEY = 'hc_aliases';

function loadAvatars() {
  try { return JSON.parse(localStorage.getItem(AVATARS_KEY) || '{}'); }
  catch { return {}; }
}
function saveAvatars(avatars) {
  localStorage.setItem(AVATARS_KEY, JSON.stringify(avatars));
}
function loadAliases() {
  try { return JSON.parse(localStorage.getItem(ALIAS_KEY) || '{}'); }
  catch { return {}; }
}
function saveAliases(aliases) {
  localStorage.setItem(ALIAS_KEY, JSON.stringify(aliases));
}

function displayName(name, aliases) {
  const a = aliases?.[name];
  return a ? a : name;
}

function fmtTime(iso) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function uid() {
  return 'c' + Math.random().toString(36).slice(2, 10);
}

// ── Avatar Component ───────────────────────────────────────────────────────

function Avatar({ name, size = 30, extraStyle = {}, src }) {
  const color = avatarColor(name);
  const initial = (name[0] || '?').toUpperCase();
  const base = {
    background: color,
    width: size,
    height: size,
    fontSize: size * 0.42,
    ...extraStyle,
  };
  if (src) {
    return (
      <div className="hc-avatar" style={{ ...base, background: 'transparent', padding: 0 }}>
        <img src={src} alt={name} style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} />
      </div>
    );
  }
  return (
    <div className="hc-avatar" style={base}>
      {initial}
    </div>
  );
}

// ── Toast Component ─────────────────────────────────────────────────────────

function Toast({ message, onDone }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3000);
    return () => clearTimeout(t);
  }, []);
  return <div className="hc-toast">{message}</div>;
}

// ── Mention Popup ───────────────────────────────────────────────────────────

function MentionPopup({ agents, query, selectedIdx, onSelect, aliases }) {
  if (!agents || agents.length === 0) return null;
  return (
    <div className="hc-mention-popup">
      {agents.map((a, i) => (
        <div
          key={a.name}
          className={`hc-mention-item${i === selectedIdx ? ' hc-selected' : ''}`}
          onMouseDown={(e) => { e.preventDefault(); onSelect(a.name); }}
        >
          <Avatar name={a.name} size={28} src={(aliases && aliases._avatars?.[a.name])} />
          <span className="hc-m-name">{esc(displayName(a.name, aliases))}</span>
        </div>
      ))}
    </div>
  );
}

// ── Settings Modal ──────────────────────────────────────────────────────────

function SettingsModal({ room, agents, onClose, onSave, onDelete }) {
  const [name, setName] = useState(room?.name || '');
  const [selected, setSelected] = useState(room?.agents || []);

  const toggleAgent = (agentName) => {
    setSelected((prev) =>
      prev.includes(agentName)
        ? prev.filter((n) => n !== agentName)
        : [...prev, agentName]
    );
  };

  return (
    <div className="hc-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="hc-modal">
        <h3>⚙ {t('roomSettingsTitle')}</h3>
        <label>{t('roomNameLabel')}</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={128}
          placeholder={t('roomNamePlaceholder')}
        />
        <label>{t('agentsLabel')}</label>
        <div className="hc-agent-checks">
          {agents.map((a) => (
            <div
              key={a.name}
              className={`hc-agent-chip${selected.includes(a.name) ? ' hc-checked' : ''}`}
              onClick={() => toggleAgent(a.name)}
            >
              <Avatar name={a.name} size={20} />
              <span>{esc(a.name)}</span>
            </div>
          ))}
        </div>
        <div className="hc-modal-actions">
          <button className="hc-btn hc-btn-danger" onClick={() => onDelete(room.id)}>
            {t('deleteBtn')}
          </button>
          <button className="hc-btn hc-btn-secondary" onClick={onClose}>
            {t('cancelBtn')}
          </button>
          <button className="hc-btn hc-btn-primary" onClick={() => onSave(name, selected)}>
            {t('saveBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Delete Confirm Modal ────────────────────────────────────────────────────

function DeleteConfirmModal({ roomName, onConfirm, onCancel }) {
  return (
    <div className="hc-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="hc-modal" style={{ maxWidth: 400 }}>
        <h3>⚠ {t('deleteTitle')}</h3>
        <p style={{ margin: '12px 0', lineHeight: 1.6, color: 'var(--hc-text-dim)' }}>
          {t('deleteBody', { name: roomName })}
        </p>
        <p style={{ margin: '8px 0', fontSize: 12, color: 'var(--hc-danger)' }}>
          {t('deleteWarning')}
        </p>
        <div className="hc-modal-actions">
          <button className="hc-btn hc-btn-secondary" onClick={onCancel}>
            {t('cancelBtn')}
          </button>
          <button className="hc-btn hc-btn-danger" onClick={onConfirm}>
            {t('deleteConfirmBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── New Room Modal ──────────────────────────────────────────────────────────

function NewRoomModal({ agents, onClose, onCreate }) {
  const [name, setName] = useState('');
  const [selected, setSelected] = useState(agents.map((a) => a.name));

  const toggleAgent = (agentName) => {
    setSelected((prev) =>
      prev.includes(agentName)
        ? prev.filter((n) => n !== agentName)
        : [...prev, agentName]
    );
  };

  return (
    <div className="hc-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="hc-modal">
        <h3>＋ {t('newRoomTitle')}</h3>
        <label>{t('roomNameLabel')}</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={128}
          placeholder={t('newRoomPlaceholder')}
        />
        <label>{t('selectAgentsLabel')}</label>
        <div className="hc-agent-checks">
          {agents.map((a) => (
            <div
              key={a.name}
              className={`hc-agent-chip${selected.includes(a.name) ? ' hc-checked' : ''}`}
              onClick={() => toggleAgent(a.name)}
            >
              <Avatar name={a.name} size={20} />
              <span>{esc(a.name)}</span>
            </div>
          ))}
        </div>
        <div className="hc-modal-actions">
          <button className="hc-btn hc-btn-secondary" onClick={onClose}>
            {t('cancelBtn')}
          </button>
          <button
            className="hc-btn hc-btn-primary"
            onClick={() => onCreate(name.trim(), selected)}
          >
            {t('createBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Agent Profile Modal ─────────────────────────────────────────────────────

function AgentProfileModal({ agent, onClose, onStartChat, api, onToast, onDelete }) {
  const [aliases, setAliases] = useState(loadAliases);
  const [avatars, setAvatars] = useState(loadAvatars);
  const [editing, setEditing] = useState(false);
  const [showDelConfirm, setShowDelConfirm] = useState(false);
  const [alias, setAlias] = useState(aliases[agent.name] || '');
  const [uploadPreview, setUploadPreview] = useState(null);
  const [soulText, setSoulText] = useState(agent.system_prompt || '');
  const [savingSoul, setSavingSoul] = useState(false);
  const fileRef = useRef(null);

  const saveAlias = () => {
    const next = { ...aliases, [agent.name]: alias.trim() };
    setAliases(next);
    saveAliases(next);
    setEditing(false);
  };

  // ── Avatar upload + crop ──
  const handleFilePick = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/gif'].includes(file.type)) {
      onToast && onToast('⚠ ' + t('agentAvatarTypeError'));
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      onToast && onToast('⚠ ' + t('agentAvatarSizeError'));
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const img = new Image();
      img.onload = () => {
        const size = Math.min(img.width, img.height);
        const sx = (img.width - size) / 2;
        const sy = (img.height - size) / 2;
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, sx, sy, size, size, 0, 0, 256, 256);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        setUploadPreview(dataUrl);
        const next = { ...loadAvatars(), [agent.name]: dataUrl };
        setAvatars(next);
        saveAvatars(next);
      };
      img.src = ev.target.result;
    };
    reader.readAsDataURL(file);
  };

  // ── Soul save ──
  const saveSoul = async () => {
    if (!api) return;
    setSavingSoul(true);
    try {
      const updated = await api('PUT', `/agents/${agent.name}`, {
        system_prompt: soulText,
      });
      agent.system_prompt = updated.system_prompt;
      onToast && onToast('✓ ' + t('soulSaved'));
    } catch (e) {
      onToast && onToast('❌ ' + (e.message || '同步失败'));
    } finally {
      setSavingSoul(false);
    }
  };

  const currentAvatar = avatars[agent.name];

  return (
    <div className="hc-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="hc-modal" style={{ maxWidth: 520 }}>
        <h3>⚙ {t('agentSettings')}</h3>

        {/* ── Avatar Section ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 8 }}>
          <Avatar name={agent.name} size={64} src={currentAvatar} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{esc(displayName(agent.name, aliases))}</div>
            {aliases[agent.name] && (
              <div style={{ fontSize: 11, color: 'var(--hc-text-dim)', marginTop: 2 }}>
                ID: {esc(agent.name)}
              </div>
            )}
          </div>
        </div>

        {/* Avatar — upload only, no preset */}
        <div style={{ marginBottom: 16 }}>
          <div className="hc-upload-area" onClick={() => fileRef.current?.click()}>
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/gif"
              style={{ display: 'none' }}
              onChange={handleFilePick}
            />
            {uploadPreview || currentAvatar ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                <img
                  src={uploadPreview || currentAvatar}
                  alt="preview"
                  style={{ width: 96, height: 96, borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--hc-accent)' }}
                />
                <span style={{ fontSize: 12, color: 'var(--hc-text-dim)' }}>
                  {uploadPreview ? t('clickToChange') : t('currentAvatar')}
                </span>
              </div>
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--hc-text-dim)' }}>
                <div style={{ fontSize: 32, marginBottom: 4 }}>📷</div>
                <div style={{ fontSize: 12 }}>{t('clickToUpload')}</div>
              </div>
            )}
          </div>
        </div>

        {/* ── Alias Section ── */}
        <label>{t('aliasLabel')}</label>
        {editing ? (
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="text" value={alias} onChange={(e) => setAlias(e.target.value)}
              maxLength={32} placeholder={t('aliasPlaceholder')} style={{ flex: 1 }} />
            <button className="hc-btn hc-btn-primary" onClick={saveAlias}
              style={{ padding: '6px 14px', fontSize: 12 }}>{t('aliasSave')}</button>
            <button className="hc-btn hc-btn-secondary" onClick={() => { setAlias(aliases[agent.name] || ''); setEditing(false); }}
              style={{ padding: '6px 14px', fontSize: 12 }}>{t('aliasCancel')}</button>
          </div>
        ) : (
          <div onClick={() => setEditing(true)}
            style={{ padding: '8px 12px', background: 'var(--hc-input-bg)',
              borderRadius: 8, cursor: 'pointer', fontSize: 13,
              color: aliases[agent.name] ? 'var(--hc-text)' : 'var(--hc-text-dim)' }}>
            {aliases[agent.name] || t('aliasEmpty')}
          </div>
        )}

        {/* ── Soul Section ── */}
        <label style={{ marginTop: 16 }}>{t('soulLabel')}</label>
        <textarea
          className="hc-soul-editor"
          value={soulText}
          onChange={(e) => setSoulText(e.target.value)}
          rows={6}
          maxLength={65536}
          placeholder={t('soulPlaceholder')}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--hc-text-dim)' }}>
            {t('soulSyncHint')}
          </span>
          <button
            className="hc-btn hc-btn-primary"
            onClick={saveSoul}
            disabled={savingSoul}
            style={{ padding: '5px 14px', fontSize: 12 }}
          >
            {savingSoul ? '⏳ ' + t('saving') : t('soulSave')}
          </button>
        </div>

        {/* ── Delete ── */}
        {!showDelConfirm ? (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--hc-border)' }}>
            <button
              className="hc-btn hc-btn-danger"
              onClick={() => setShowDelConfirm(true)}
              style={{ fontSize: 12 }}
            >
              🗑 {t('deleteBtn') || '删除 Agent'}
            </button>
          </div>
        ) : (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--hc-border)' }}>
            <p style={{ fontSize: 13, color: 'var(--hc-danger)', marginBottom: 10 }}>
              ⚠ 确定要删除 Agent「{esc(agent.name)}」吗？此操作不可撤销。
            </p>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="hc-btn hc-btn-secondary" onClick={() => setShowDelConfirm(false)} style={{ fontSize: 12 }}>
                {t('cancelBtn')}
              </button>
              <button className="hc-btn hc-btn-danger" onClick={async () => {
                try {
                  await api('DELETE', `/agents/${agent.name}`);
                  onDelete && onDelete(agent.name);
                  onClose();
                } catch (e) {
                  onToast && onToast('❌ ' + (e.message || '删除失败'));
                  setShowDelConfirm(false);
                }
              }} style={{ fontSize: 12 }}>
                确认删除
              </button>
            </div>
          </div>
        )}

        <div className="hc-modal-actions">
          <button className="hc-btn hc-btn-secondary" onClick={onClose}>{t('closeBtn')}</button>
          <button className="hc-btn hc-btn-primary" onClick={() => onStartChat(agent.name)}>
            {t('startChatBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Message Input ───────────────────────────────────────────────────────────

function MessageInput({ onSend, agents, disabled, aliases }) {
  const [value, setValue] = useState('');
  const [showMention, setShowMention] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionIdx, setMentionIdx] = useState(0);
  const textareaRef = useRef(null);

  const filteredAgents = agents.filter((a) =>
    a.name.toLowerCase().includes(mentionQuery.toLowerCase())
  );

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
  }, []);

  const detectMention = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    const val = el.value;
    const pos = el.selectionStart;
    const before = val.slice(0, pos);
    const atPos = before.lastIndexOf('@');
    if (atPos === -1 || (atPos > 0 && before[atPos - 1] !== ' ' && before[atPos - 1] !== '\n')) {
      setShowMention(false);
      return;
    }
    const q = before.slice(atPos + 1);
    if (q.includes(' ') || q.includes('\n')) {
      setShowMention(false);
      return;
    }
    setMentionQuery(q);
    setMentionIdx(0);
    setShowMention(true);
  }, []);

  const insertMention = useCallback((name) => {
    const el = textareaRef.current;
    if (!el) return;
    const val = el.value;
    const pos = el.selectionStart;
    const before = val.slice(0, pos);
    const atPos = before.lastIndexOf('@');
    const after = val.slice(pos);
    const newVal = val.slice(0, atPos) + '@' + name + ' ' + after;
    setValue(newVal);
    setShowMention(false);
    setTimeout(() => {
      el.focus();
      const newPos = atPos + name.length + 2;
      el.setSelectionRange(newPos, newPos);
      autoResize();
    }, 0);
  }, [autoResize]);

  const handleSend = useCallback(() => {
    const content = value.trim();
    if (!content || disabled) return;
    onSend(content);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, disabled, onSend]);

  const handleKeyDown = useCallback((e) => {
    if (showMention && filteredAgents.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIdx((i) => (i + 1) % filteredAgents.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIdx((i) => (i - 1 + filteredAgents.length) % filteredAgents.length);
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        insertMention(filteredAgents[mentionIdx]?.name);
        return;
      }
      if (e.key === 'Escape') {
        setShowMention(false);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [showMention, filteredAgents, mentionIdx, insertMention, handleSend]);

  return (
    <div className="hc-input-area">
      <div className="hc-input-wrapper">
        {showMention && filteredAgents.length > 0 && (
          <MentionPopup
            agents={filteredAgents}
            query={mentionQuery}
            selectedIdx={mentionIdx}
            onSelect={insertMention}
            aliases={aliases}
          />
        )}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); autoResize(); detectMention(); }}
          onKeyDown={handleKeyDown}
          placeholder={t('inputPlaceholder')}
          rows={1}
          disabled={disabled}
        />
        <button
          className="hc-btn-send"
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          title={t('sendTitle')}
        >
          ➤
        </button>
      </div>
    </div>
  );
}

// ── Typing Indicator ────────────────────────────────────────────────────────

function TypingIndicator({ agentNames, aliases }) {
  if (!agentNames || agentNames.length === 0) return null;
  const dNames = agentNames.map(n => displayName(n, aliases));
  let text;
  if (dNames.length === 1) {
    text = t('typingOne', { name: dNames[0] });
  } else if (dNames.length === 2) {
    text = t('typingTwo', { n1: dNames[0], n2: dNames[1] });
  } else {
    text = t('typingMany', { n1: dNames[0], n2: dNames[1], count: dNames.length - 2 });
  }
  return (
    <div className="hc-typing-bar hc-visible">
      <span className="hc-typing-dots"><span></span><span></span><span></span></span>
      <span>{text}</span>
    </div>
  );
}

// ── Message Bubble ──────────────────────────────────────────────────────────

function MessageBubble({ msg, showTime, onAvatarClick, aliases, user }) {
  const isSystem = msg.msg_type === 'system';
  const isUser = msg.msg_type === 'user' || msg.sender === 'user';
  const dName = displayName(msg.sender, aliases);
  const hasAlias = aliases?.[msg.sender] && aliases[msg.sender] !== msg.sender;

  if (isSystem) {
    return (
      <div className={`hc-msg hc-system${showTime ? ' hc-show-time' : ''}`}>
        <div className="hc-msg-body">
          <div className="hc-msg-bubble">{esc(msg.content)}</div>
          <div className="hc-msg-time">{fmtTime(msg.timestamp)}</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`hc-msg ${isUser ? 'hc-user' : 'hc-agent'}${showTime ? ' hc-show-time' : ''}`}>
      {!isUser && (
        <div onClick={() => onAvatarClick && onAvatarClick(msg.sender)} title={msg.sender} style={{ cursor: 'pointer' }}>
          <Avatar name={msg.sender} size={30} src={(aliases && aliases._avatars?.[msg.sender])} />
        </div>
      )}
      <div className="hc-msg-body">
        {!isUser && (
          <div className="hc-msg-sender">
            {esc(dName)}
            {hasAlias && <span className="hc-msg-sender-id"> ({esc(msg.sender)})</span>}
          </div>
        )}
        {isUser && user && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div className="hc-msg-sender" style={{ color: 'var(--hc-accent)' }}>
              {esc(user.name || '用户')}
            </div>
            <Avatar name={user.name || '?'} size={24} src={user.avatar} />
          </div>
        )}
        <div className="hc-msg-bubble">{esc(msg.content)}</div>
        <div className="hc-msg-time">{fmtTime(msg.timestamp)}</div>
      </div>
    </div>
  );
}

// ── Loading Indicator (for scroll-top pagination) ──────────────────────────

function LoadMoreIndicator({ loading, hasMore }) {
  if (!loading && !hasMore) return null;

  let text;
  if (loading) {
    text = (
      <span>
        <span className="hc-spinner" />
        {' ' + t('loadingMore')}
      </span>
    );
  } else if (!hasMore) {
    text = t('noMoreMessages');
  } else {
    return null;
  }

  return (
    <div className="hc-load-more">{text}</div>
  );
}

// ── Main App Component ─────────────────────────────────────────────────────

// ═══════════════════════════════════════════════════════════════════════════
// New Agent Modal — create new agent profile from the Dashboard
// ═══════════════════════════════════════════════════════════════════════════
function NewAgentModal({ api, onClose, onCreated, t }) {
  const [name, setName] = useState('');
  const [role, setRole] = useState('');
  const [soul, setSoul] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const handleCreate = async () => {
    const trimmed = name.trim().toLowerCase();  // Hermes profiles are lowercase-only
    if (!trimmed) { setError(t('newAgentNameRequired')); return; }
    if (!trimmed.replace(/_/g, '').match(/^[a-z0-9]+$/)) {
      setError('Agent 名称只能包含小写字母、数字和下划线'); return;
    }
    if (!soul.trim()) { setError(t('newAgentSoulRequired')); return; }
    setCreating(true);
    setError('');
    try {
      await api('POST', '/agents', {
        name: trimmed,
        role: role.trim() || trimmed,
        system_prompt: soul.trim(),
      });
      onCreated && onCreated(trimmed);
      onClose();
    } catch (e) {
      setError(e.message || '创建失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="hc-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="hc-modal" style={{ maxWidth: 480 }}>
        <h3>＋ {t('newAgentTitle')}</h3>

        <label>{t('agentNameLabel')}</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase())}
          maxLength={64}
          placeholder={t('agentNamePlaceholder')}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          style={{ textTransform: 'lowercase' }}
        />
        <div style={{ fontSize: 10, color: 'var(--hc-text-dim)', marginTop: 2 }}>
          名称自动转为小写（与 Hermes CLI Profile 命名规范一致）
        </div>

        <label>{t('agentRoleLabel')}</label>
        <input
          type="text"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          maxLength={128}
          placeholder={t('agentRolePlaceholder')}
        />

        <label>{t('agentSoulLabel')}</label>
        <textarea
          className="hc-soul-editor"
          value={soul}
          onChange={(e) => setSoul(e.target.value)}
          rows={4}
          maxLength={65536}
          placeholder={t('agentSoulPlaceholder')}
        />

        {error && (
          <div style={{ color: 'var(--hc-danger)', fontSize: 13, marginTop: 8 }}>{error}</div>
        )}

        <div className="hc-modal-actions">
          <button className="hc-btn hc-btn-secondary" onClick={onClose}>{t('cancelBtn')}</button>
          <button
            className="hc-btn hc-btn-primary"
            onClick={handleCreate}
            disabled={creating}
          >
            {creating ? '⏳ ' + t('saving') : t('createBtn')}
          </button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// User Profile Modal — user can set avatar, name, bio
// ═══════════════════════════════════════════════════════════════════════════
function UserProfileModal({ user, onClose, onSave, t }) {
  const [name, setName] = useState(user.name || '');
  const [bio, setBio] = useState(user.bio || '');
  const [preview, setPreview] = useState(user.avatar || null);
  const fileRef = useRef(null);

  const pickFile = (e) => {
    const file = e.target.files?.[0];
    if (!file || !['image/jpeg','image/png','image/gif'].includes(file.type) || file.size > 2*1024*1024) return;
    const r = new FileReader();
    r.onload = (ev) => { const img = new Image(); img.onload = () => { const s = Math.min(img.width,img.height); const sx=(img.width-s)/2; const sy=(img.height-s)/2; const c=document.createElement('canvas'); c.width=256;c.height=256;c.getContext('2d').drawImage(img,sx,sy,s,s,0,0,256,256); setPreview(c.toDataURL('image/jpeg',0.85)); }; img.src=ev.target.result; };
    r.readAsDataURL(file);
  };

  return (
    <div className="hc-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="hc-modal" style={{ maxWidth: 520 }}>
        <h3>👤 {t('userSettingsTitle')}</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
          <Avatar name={name || '?'} size={64} src={preview || user.avatar} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{esc(name || '董事长')}</div>
            <div style={{ fontSize: 13, color: 'var(--hc-text-dim)', marginTop: 2 }}>用户</div>
          </div>
        </div>
        <div style={{ marginBottom: 16 }}>
          <div className="hc-upload-area" onClick={() => fileRef.current?.click()}>
            <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/gif" style={{ display: 'none' }} onChange={pickFile} />
            {preview || user.avatar ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                <img src={preview || user.avatar} alt="" style={{ width: 96, height: 96, borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--hc-accent)' }} />
                <span style={{ fontSize: 12, color: 'var(--hc-text-dim)' }}>{preview ? '点击更换' : '当前头像'}</span>
              </div>
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--hc-text-dim)' }}>
                <div style={{ fontSize: 32, marginBottom: 4 }}>📷</div>
                <div style={{ fontSize: 12 }}>{t('clickToUpload')}</div>
              </div>
            )}
          </div>
        </div>
        <label>{t('userNameLabel')}</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} maxLength={32} placeholder={t('userNamePlaceholder')} style={{ width: '100%', background: 'var(--hc-input-bg)', border: '1px solid var(--hc-border)', borderRadius: 'var(--hc-radius)', padding: '8px 12px', color: 'var(--hc-text)', fontFamily: 'var(--hc-font)', fontSize: 13, outline: 'none', marginBottom: 14 }} />
        <label>{t('userBioLabel')}</label>
        <textarea className="hc-soul-editor" value={bio} onChange={(e) => setBio(e.target.value)} rows={4} maxLength={4096} placeholder="介绍你自己，例如：我是董事长，负责战略方向和最终决策..." />
        <div className="hc-modal-actions">
          <button className="hc-btn hc-btn-secondary" onClick={onClose}>{t('cancelBtn')}</button>
          <button className="hc-btn hc-btn-primary" onClick={() => { onSave({ name: name.trim() || '董事长', avatar: preview || user.avatar, bio: bio.trim() }); onClose(); }}>{t('saveBtn')}</button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Main App
// ═══════════════════════════════════════════════════════════════════════════
export default function App() {
  // ── State ──
  const [rooms, setRooms] = useState([]);
  const [agents, setAgents] = useState([]);
  const [activeRoomId, setActiveRoomId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesHasMore, setMessagesHasMore] = useState(true);
  const [messagesLoadingMore, setMessagesLoadingMore] = useState(false);
  const [sending, setSending] = useState(false);
  const [typingNames, setTypingNames] = useState([]);
  const [toast, setToast] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showNewRoom, setShowNewRoom] = useState(false);
  const [showNewAgent, setShowNewAgent] = useState(false);
  const [showAgentProfile, setShowAgentProfile] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(null);
  const [contextCleared, setContextCleared] = useState(false);
  const [lang, setLangState] = useState('zh-CN');
  const [user, setUser] = useState({ name: '董事长', avatar: '', bio: '' });
  const [showUserProfile, setShowUserProfile] = useState(false);
  const [displayMap, setDisplayMap] = useState(() => {
    const a = loadAliases();
    const v = loadAvatars();
    return { ...a, _avatars: v };
  });

  const messagesRef = useRef(null);
  const topSentinelRef = useRef(null);
  const prevRoomRef = useRef(null);
  const isLoadingMoreRef = useRef(false);

  // ── API ── (uses SDK fetchJSON which auto-includes auth token)
  const fetchJSON = window.__HERMES_PLUGIN_SDK__?.fetchJSON;
  const api = useCallback(async (method, path, body) => {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    if (fetchJSON) {
      try {
        const data = await fetchJSON(API_BASE + path, opts);
        return data ?? null;
      } catch (e) {
        if (method === 'DELETE' && e.message?.includes('JSON')) return null;
        throw e;
      }
    }
    const res = await fetch(API_BASE + path, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }, []);

  // ── Toast helper ──
  const showToast = useCallback((msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3100);
  }, []);

  // ── Init i18n ──
  useEffect(() => { setLangState(initLang()); }, []);

  // ── Load agents & user on mount ──
  useEffect(() => {
    api('GET', '/agents').then(setAgents).catch((e) => showToast('⚠ ' + e.message));
    api('GET', '/user').then(setUser).catch(() => {});
  }, []);

  // ── Load rooms on mount ──
  useEffect(() => {
    api('GET', '/rooms').then((data) => {
      const roomList = data.rooms || [];
      if (roomList.length === 0) {
        api('GET', '/rooms/default').then((def) => {
          setRooms([def]);
          setActiveRoomId(def.id);
        }).catch((e) => showToast('⚠ ' + e.message));
      } else {
        setRooms(roomList);
        setActiveRoomId((prev) => prev || roomList[0]?.id);
      }
    }).catch((e) => showToast('⚠ ' + e.message));
  }, []);

  // ── Load messages when active room changes ──
  const loadMessages = useCallback(async (roomId) => {
    if (!roomId) return;
    setMessagesLoading(true);
    setMessages([]);
    setMessagesHasMore(true);
    setContextCleared(false);
    prevRoomRef.current = roomId;
    try {
      const data = await api('GET',
        `/rooms/${roomId}/messages?limit=${INITIAL_LOAD}&since_clear=true`);
      const msgs = (data.messages || []).reverse(); // API returns DESC, we want ASC
      setMessages(msgs);
      setMessagesHasMore(data.has_more !== false);
    } catch (e) {
      setMessages([]);
      setMessagesHasMore(false);
    } finally {
      setMessagesLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (activeRoomId !== prevRoomRef.current) {
      loadMessages(activeRoomId);
    }
  }, [activeRoomId, loadMessages]);

  // ── Scroll to bottom on new messages (only if near bottom) ──
  const isNearBottom = useCallback(() => {
    const el = messagesRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (messagesRef.current) {
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
      }
    });
  }, []);

  useEffect(() => {
    if (isNearBottom()) scrollToBottom();
  }, [messages, scrollToBottom, isNearBottom]);

  // ── Load more (pagination on scroll to top) ──
  const loadMoreMessages = useCallback(async () => {
    if (!activeRoomId || !messagesHasMore || messagesLoadingMore || isLoadingMoreRef.current) return;
    if (messages.length === 0) return;

    isLoadingMoreRef.current = true;
    setMessagesLoadingMore(true);

    try {
      const oldestMsg = messages[0];
      const data = await api('GET',
        `/rooms/${activeRoomId}/messages?limit=${PAGINATE_SIZE}&before_id=${oldestMsg.id}&since_clear=true`);
      const olderMsgs = (data.messages || []).reverse();

      if (olderMsgs.length === 0) {
        setMessagesHasMore(false);
      } else {
        // Preserve scroll position: record old scrollHeight
        const el = messagesRef.current;
        const prevScrollHeight = el ? el.scrollHeight : 0;

        setMessages((prev) => {
          const next = [...olderMsgs, ...prev];
          // DOM cap: trim from bottom if > DOM_CAP
          if (next.length > DOM_CAP) {
            return next.slice(0, DOM_CAP);
          }
          return next;
        });

        // Restore scroll position after DOM update
        requestAnimationFrame(() => {
          if (el) {
            el.scrollTop = el.scrollHeight - prevScrollHeight;
          }
        });

        if (olderMsgs.length < PAGINATE_SIZE) {
          setMessagesHasMore(false);
        }
      }
    } catch (e) {
      // silent
    } finally {
      setMessagesLoadingMore(false);
      isLoadingMoreRef.current = false;
    }
  }, [activeRoomId, messages, messagesHasMore, messagesLoadingMore, api]);

  // ── IntersectionObserver for top sentinel ──
  useEffect(() => {
    const sentinel = topSentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && messagesHasMore && !messagesLoadingMore) {
          loadMoreMessages();
        }
      },
      { threshold: 0.1 }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [messagesHasMore, messagesLoadingMore, loadMoreMessages]);

  // ── Send message ──
  const sendMessage = useCallback(async (content) => {
    if (!activeRoomId || sending) return;
    setSending(true);

    const tempId = uid();
    const tempMsg = {
      id: tempId,
      room_id: activeRoomId,
      sender: 'user',
      content,
      msg_type: 'user',
      target_agent: null,
      reply_depth: 0,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempMsg]);

    const room = rooms.find((r) => r.id === activeRoomId);
    setTypingNames(room ? room.agents : []);

    try {
      const res = await api('POST', `/rooms/${activeRoomId}/messages`, {
        content,
        sender: 'user',
      });
      setTypingNames([]);

      setMessages((prev) => {
        const next = prev.map((m) => (m.id === tempId ? res.user_message : m));
        if (res.fan_out?.responses) {
          res.fan_out.responses.forEach((r) => {
            if (r.replied && r.content) {
              next.push({
                id: uid(),
                room_id: activeRoomId,
                sender: r.agent_name,
                content: r.content,
                msg_type: 'agent',
                target_agent: null,
                reply_depth: 1,
                timestamp: r.finished_at || new Date().toISOString(),
              });
            } else if (r.error) {
              // Show error as system message so user knows WHY agent didn't reply
              next.push({
                id: uid(),
                room_id: activeRoomId,
                sender: 'system',
                content: `[${r.agent_name}] ${r.error}`,
                msg_type: 'system',
                target_agent: null,
                reply_depth: 0,
                timestamp: r.finished_at || new Date().toISOString(),
              });
            }
          });
        }
        return next;
      });

      const updatedRoom = await api('GET', `/rooms/${activeRoomId}`);
      setRooms((prev) => prev.map((r) => (r.id === activeRoomId ? updatedRoom : r)));
    } catch (e) {
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      setTypingNames([]);
      showToast('❌ ' + e.message);
    } finally {
      setSending(false);
    }
  }, [activeRoomId, sending, rooms, api, showToast]);

  // ── Clear context ──
  const clearContext = useCallback(async () => {
    if (!activeRoomId) return;
    try {
      const result = await api('POST', `/rooms/${activeRoomId}/context/clear`);
      // Insert visual divider
      const divider = {
        id: uid(),
        room_id: activeRoomId,
        sender: 'system',
        content: t('contextClearedDivider'),
        msg_type: 'system',
        target_agent: null,
        reply_depth: 0,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, divider]);
      setContextCleared(true);
      showToast('✓ ' + t('contextClearedToast'));
    } catch (e) {
      showToast('❌ ' + e.message);
    }
  }, [activeRoomId, api, showToast]);

  // ── Delete room (with confirmation modal) ──
  const requestDeleteRoom = useCallback((roomId) => {
    setShowDeleteConfirm(roomId);
    setShowSettings(false);
  }, []);

  const confirmDeleteRoom = useCallback(async () => {
    const roomId = showDeleteConfirm;
    if (!roomId) return;
    try {
      await api('DELETE', `/rooms/${roomId}`);
      setShowDeleteConfirm(null);
      setRooms((prev) => prev.filter((r) => r.id !== roomId));
      if (activeRoomId === roomId) {
        setActiveRoomId(null);
        setMessages([]);
      }
      showToast('✓ ' + t('roomDeleted'));
    } catch (e) {
      setShowDeleteConfirm(null);
      showToast('❌ ' + e.message);
    }
  }, [showDeleteConfirm, activeRoomId, api, showToast]);

  // ── Save settings ──
  const saveSettings = useCallback(async (name, selectedAgents) => {
    if (!name) return showToast(t('roomNameRequired'));
    if (selectedAgents.length === 0) return showToast(t('atLeastOneAgent'));
    try {
      const updated = await api('PUT', `/rooms/${activeRoomId}`, {
        name,
        agents: selectedAgents,
      });
      setRooms((prev) => prev.map((r) => (r.id === activeRoomId ? updated : r)));
      setShowSettings(false);
      showToast(t('roomUpdated'));
    } catch (e) {
      showToast('❌ ' + e.message);
    }
  }, [activeRoomId, api, showToast]);

  // ── Create room ──
  const createRoom = useCallback(async (name, selectedAgents) => {
    if (!name) return showToast(t('roomNameRequired'));
    if (selectedAgents.length === 0) return showToast(t('selectOneAgent'));
    try {
      const room = await api('POST', '/rooms', { name, agents: selectedAgents });
      setRooms((prev) => [...prev, room]);
      setShowNewRoom(false);
      setActiveRoomId(room.id);
    } catch (e) {
      showToast('❌ ' + e.message);
    }
  }, [api, showToast]);

  // ── Start DM with agent ──
  const startDM = useCallback(async (agentName) => {
    const existing = rooms.find((r) =>
      r.agents && r.agents.length === 1 && r.agents[0] === agentName
    );
    if (existing) {
      setActiveRoomId(existing.id);
      return;
    }
    try {
      const room = await api('POST', '/rooms', {
        name: agentName,
        agents: [agentName],
      });
      setRooms((prev) => [...prev, room]);
      setActiveRoomId(room.id);
    } catch (e) {
      showToast('❌ ' + e.message);
    }
  }, [rooms, api, showToast]);

  // ── Language ──
  const switchLang = useCallback((code) => {
    setLang(code);
    setLangState(code);
  }, []);

  // ── Derived ──
  const activeRoom = rooms.find((r) => r.id === activeRoomId);

  const refreshDisplayMap = useCallback(() => {
    const a = loadAliases();
    const v = loadAvatars();
    setDisplayMap({ ...a, _avatars: v });
  }, []);

  const handleAvatarClick = useCallback((senderName) => {
    const agent = agents.find((a) => a.name === senderName);
    if (agent) setShowAgentProfile(agent);
  }, [agents]);

  // ── Render ──
  // Truncate displayed messages to DOM_CAP if they somehow exceed it
  const displayMessages = messages.length > DOM_CAP
    ? messages.slice(messages.length - DOM_CAP)
    : messages;

  return (
    <div className="hc-root">
      {/* ── Sidebar ── */}
      <aside className="hc-sidebar">
        <div className="hc-sidebar-header">
          <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
            {availableLangs().map((l) => (
              <button
                key={l.code}
                className="hc-btn-icon"
                onClick={() => switchLang(l.code)}
                title={l.label}
                style={{
                  width: 'auto', height: 22, fontSize: 11, padding: '0 8px',
                  fontWeight: lang === l.code ? 700 : 400,
                  color: lang === l.code ? 'var(--hc-accent)' : 'var(--hc-text-dim)',
                }}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
        <div className="hc-sidebar-section">{t('roomsSection')}</div>
        <div className="hc-sidebar-list">
          {rooms.filter((r) => r.agents?.length > 1).map((r) => (
            <div
              key={r.id}
              className={`hc-sidebar-item${r.id === activeRoomId ? ' hc-active' : ''}`}
              onClick={() => setActiveRoomId(r.id)}
            >
              <div
                className="hc-avatar"
                style={{
                  background: 'linear-gradient(135deg, var(--hc-accent), #0066cc)',
                  fontSize: '13px',
                  width: 32,
                  height: 32,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  flexShrink: 0,
                }}
              >
                💬
              </div>
              <div className="hc-info">
                <div className="hc-name">{esc(r.name)}</div>
                <div className="hc-meta">
                  {r.agents?.length || 0} {t('agentsUnit')} · {r.message_count || 0} {t('msgsUnit')}
                </div>
              </div>
            </div>
          ))}
        </div>
        <button
          className="hc-btn-icon hc-new-room-btn"
          onClick={() => setShowNewRoom(true)}
          style={{ width: 'auto', height: 32, fontSize: 12, padding: '0 12px', margin: '4px 8px' }}
        >
          {t('newRoomBtn')}
        </button>
        <div className="hc-sidebar-section">{t('contactsSection')}</div>
        <div className="hc-sidebar-list">
          {agents.map((a) => {
            const dmActive = activeRoom && activeRoom.agents?.length === 1 && activeRoom.agents[0] === a.name;
            return (
            <div
              key={a.name}
              className={`hc-sidebar-item${dmActive ? ' hc-active' : ''}`}
              onClick={() => startDM(a.name)}
              title={displayName(a.name, displayMap)}
              style={{ cursor: 'pointer' }}
            >
              <div onClick={(e) => { e.stopPropagation(); setShowAgentProfile(a); }} style={{ cursor: 'pointer' }}>
                <Avatar name={a.name} size={32} src={displayMap._avatars?.[a.name]} />
              </div>
              <div className="hc-info">
                <div className="hc-name">{esc(displayName(a.name, displayMap))}</div>
              </div>
              <button
                className="hc-btn-icon"
                onClick={(e) => { e.stopPropagation(); setShowAgentProfile(a); }}
                title={t('agentSettings')}
                style={{ width: 20, height: 20, fontSize: 11, flexShrink: 0, opacity: 0.35 }}
              >
                ℹ
              </button>
              {!a.is_active && <div className="hc-badge">{t('offline')}</div>}
            </div>
            );
          })}
        </div>
        <button
          className="hc-btn-icon hc-new-room-btn"
          onClick={() => setShowNewAgent(true)}
          style={{ width: 'auto', height: 32, fontSize: 12, padding: '0 12px', margin: '4px 8px' }}
        >
          {t('newAgentBtn')}
        </button>
        {/* ── User Section ── */}
        <div style={{ marginTop: 'auto', borderTop: '1px solid var(--hc-border)', padding: '8px' }}>
          <div
            className="hc-sidebar-item"
            onClick={() => setShowUserProfile(true)}
            style={{ cursor: 'pointer', margin: 0 }}
          >
            <Avatar name={user.name || '?'} size={28} src={user.avatar} />
            <div className="hc-info">
              <div className="hc-name">{esc(user.name || '董事长')}</div>
              <div className="hc-meta">用户</div>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Chat Area ── */}
      <main className="hc-chat">
        {activeRoom ? (
          <>
            <div className="hc-chat-header">
              <div
                className="hc-room-icon"
                onClick={() => {
                  if (activeRoom.agents?.length === 1) {
                    const a = agents.find(ag => ag.name === activeRoom.agents[0]);
                    if (a) setShowAgentProfile(a);
                  }
                }}
                style={{ cursor: activeRoom.agents?.length === 1 ? 'pointer' : 'default' }}
              >{activeRoom.name.slice(0, 1).toUpperCase()}</div>
              <div className="hc-room-info">
                <div
                  className="hc-room-name"
                  onClick={() => {
                    if (activeRoom.agents?.length === 1) {
                      const a = agents.find(ag => ag.name === activeRoom.agents[0]);
                      if (a) setShowAgentProfile(a);
                    }
                  }}
                  style={{ cursor: activeRoom.agents?.length === 1 ? 'pointer' : 'default' }}
                >{esc(activeRoom.name)}</div>
                <div className="hc-room-agents">
                  {esc(activeRoom.agents?.join(', ') || t('noAgents'))}
                </div>
              </div>
              <button
                className="hc-btn-icon"
                onClick={() => setShowSettings(true)}
                title={t('roomSettingsTitle')}
              >
                ⚙
              </button>
            </div>
            <div className="hc-messages" ref={messagesRef}>
              {/* Top sentinel for scroll-based pagination */}
              <div ref={topSentinelRef} style={{ height: 1 }} />
              <LoadMoreIndicator
                loading={messagesLoadingMore}
                hasMore={messagesHasMore}
              />
              {messagesLoading && displayMessages.length === 0 ? (
                <div className="hc-loading-state">
                  <span className="hc-spinner" />
                  <span>{t('loadingMessages')}</span>
                </div>
              ) : displayMessages.length === 0 ? (
                <div className="hc-empty-state">
                  <div className="hc-empty-text">{t('noMessages')}</div>
                </div>
              ) : (
                displayMessages.map((m, i) => {
                  const prev = displayMessages[i - 1];
                  const timeGap = prev
                    ? (new Date(m.timestamp) - new Date(prev.timestamp)) > FIVE_MIN
                    : false;
                  return <MessageBubble key={m.id || i} msg={m} showTime={timeGap} onAvatarClick={handleAvatarClick} aliases={displayMap} user={user} />;
                })
              )}
            </div>
            <TypingIndicator agentNames={typingNames} aliases={displayMap} />
            <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '0 20px 4px' }}>
              <button
                className="hc-btn hc-btn-secondary"
                onClick={clearContext}
                style={{ fontSize: 11, padding: '3px 12px' }}
              >
                {t('clearContext')}
              </button>
            </div>
            <MessageInput
              onSend={sendMessage}
              agents={agents}
              disabled={sending}
              aliases={displayMap}
            />
          </>
        ) : (
          <div className="hc-empty-state">
            <div className="hc-empty-icon">💬</div>
            <div className="hc-empty-text">{t('selectRoom')}</div>
            <div className="hc-empty-hint">{t('selectRoomHint')}</div>
          </div>
        )}
      </main>

      {/* ── Modals ── */}
      {showSettings && activeRoom && (
        <SettingsModal
          room={activeRoom}
          agents={agents}
          onClose={() => setShowSettings(false)}
          onSave={saveSettings}
          onDelete={requestDeleteRoom}
        />
      )}
      {showNewRoom && (
        <NewRoomModal
          agents={agents}
          onClose={() => setShowNewRoom(false)}
          onCreate={createRoom}
        />
      )}
      {showNewAgent && (
        <NewAgentModal
          api={api}
          t={t}
          onClose={() => setShowNewAgent(false)}
          onCreated={(name) => {
            api('GET', '/agents').then(setAgents).catch(() => {});
            showToast('✓ ' + t('agentCreated'));
          }}
        />
      )}
      {showUserProfile && (
        <UserProfileModal
          user={user}
          t={t}
          onClose={() => setShowUserProfile(false)}
          onSave={(newUser) => { setUser(newUser); api('PUT', '/user', newUser).catch(() => {}); }}
        />
      )}
      {showAgentProfile && (
        <AgentProfileModal
          agent={showAgentProfile}
          onClose={() => { setShowAgentProfile(null); refreshDisplayMap(); }}
          onStartChat={(name) => { setShowAgentProfile(null); startDM(name); }}
          onDelete={(name) => {
            setAgents((prev) => prev.filter((a) => a.name !== name));
            // Remove agent from rooms, delete empty DM rooms
            setRooms((prev) => {
              const next = [];
              for (const r of prev) {
                const newAgents = r.agents?.filter((a) => a !== name) || [];
                if (newAgents.length === 0 && r.agents?.length === 1) continue; // DM room: delete it
                if (newAgents.length === 0) continue; // empty room
                next.push({ ...r, agents: newAgents });
              }
              return next;
            });
            // If active room was the DM with this agent, clear it
            setActiveRoomId((prev) => {
              const room = rooms.find((r) => r.id === prev);
              if (room && room.agents?.length === 1 && room.agents[0] === name) return null;
              return prev;
            });
            showToast('✓ Agent 已删除');
          }}
          api={api}
          onToast={showToast}
        />
      )}
      {showDeleteConfirm && (
        <DeleteConfirmModal
          roomName={rooms.find((r) => r.id === showDeleteConfirm)?.name || ''}
          onConfirm={confirmDeleteRoom}
          onCancel={() => setShowDeleteConfirm(null)}
        />
      )}

      {/* ── Toast ── */}
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
    </div>
  );
}
