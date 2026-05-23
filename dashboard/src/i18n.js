/**
 * Hermes Chat — i18n (zh-CN / en).
 *
 * Pure module — no React dependency.  All UI strings in one place.
 * Language persisted in localStorage under key `hc_lang`.
 */

const LS_KEY = 'hc_lang';

const DICT = {
  'zh-CN': {
    // ── Sidebar ──
    appTitle: 'HERMES AGENTS CHAT',
    appSubtitle: '多 Agent 实时协作',
    roomsSection: '群聊',
    contactsSection: '联系人',
    newRoomBtn: '＋ 新建房间',
    offline: '离线',
    agentsUnit: '位 Agent',
    msgsUnit: '条消息',
    noAgents: '无 Agent',

    // ── Chat Area ──
    selectRoom: '选择一个房间开始聊天',
    selectRoomHint: '或从左侧边栏新建',
    inputPlaceholder: '输入消息...（@ 提及 Agent）',
    sendTitle: '发送 (Enter)',
    roomSettingsTitle: '房间设置',

    // ── Typing ──
    typingOne: '{name} 正在输入...',
    typingTwo: '{n1}、{n2} 正在输入...',
    typingMany: '{n1}、{n2} 等 {count} 人正在输入...',

    // ── Modals: Settings ──
    roomNameLabel: '房间名称',
    agentsLabel: 'Agent',
    deleteBtn: '删除',
    cancelBtn: '取消',
    saveBtn: '保存',
    roomNamePlaceholder: '房间名',
    newRoomPlaceholder: '输入房间名...',

    // ── Modals: New Room ──
    newRoomTitle: '新建房间',
    selectAgentsLabel: '选择 Agent',
    createBtn: '创建',

    // ── Modals: Agent Profile ──
    aliasLabel: '备注',
    aliasPlaceholder: '输入别名...',
    aliasEmpty: '点击设置备注...',
    aliasSave: '保存',
    aliasCancel: '取消',
    soulLabel: 'SOUL',
    noSoul: '未定义 SOUL。',
    soulPlaceholder: '输入 Agent 的角色描述...',
    soulSave: '同步到 Profile',
    soulSaved: 'Soul 已同步到 profile',
    saving: '同步中...',
    soulSyncHint: '修改后点击右侧按钮，立即生效',
    closeBtn: '关闭',
    startChatBtn: '💬 开始聊天',
    presetAvatar: '预设',
    uploadAvatar: '上传',
    useDefaultAvatar: '使用默认头像',
    clickToUpload: '点击选择图片',
    clickToChange: '点击更换图片',
    currentAvatar: '当前头像',
    agentAvatarSizeError: '图片不能超过 2MB',
    agentAvatarTypeError: '仅支持 JPG/PNG/GIF 格式',

    // ── Modals: New Agent ──
    newAgentBtn: '＋ 新建 Agent',
    newAgentTitle: '新建 Agent',
    agentNameLabel: 'Agent 名称',
    agentNamePlaceholder: '输入 Agent 名称（仅字母、数字、下划线）...',
    agentRoleLabel: '角色 / 显示名',
    agentRolePlaceholder: '例如：CTO & 算法架构师',
    agentSoulLabel: 'SOUL / 系统提示词',
    agentSoulPlaceholder: '描述 Agent 的角色和行为...',
    newAgentNameRequired: 'Agent 名称不能为空',
    newAgentSoulRequired: 'SOUL 不能为空',
    agentCreated: '✓ Agent 已创建，已加入全员作战室',

    // ── Validation / Toasts ──
    roomNameRequired: '房间名称不能为空',
    atLeastOneAgent: '至少选择一个 Agent',
    selectOneAgent: '请至少选择一个 Agent',
    deleteConfirm: '确定要永久删除此房间？',
    roomUpdated: '✓ 房间已更新',
    roomDeleted: '✓ 房间已删除',
    chatWith: '与 {name} 私聊',
    agentSettings: 'Agent 设置',
    clearContext: '清除上下文',
    contextClearedDivider: '── ✨ 上下文已清除 ✨ ──',
    contextClearedToast: '上下文已清除，之前的内容已存档',

    // ── Scroll / Pagination ──
    loadingMessages: '加载消息中...',
    loadingMore: '加载更多...',
    noMoreMessages: '—— 已经到底了 ——',
    noMessages: '暂无消息，发送第一条吧',

    // ── Delete Confirm ──
    deleteTitle: '删除房间',
    deleteBody: '确定要永久删除「{name}」吗？',
    deleteWarning: '删除后，该房间的所有聊天记录将永久丢失，不可恢复。',
    deleteConfirmBtn: '确认删除',

    // ── Error ──
    unknownAgents: '未知 Agent：',

    // ── User Settings ──
    userSettingsTitle: '个人设置',
    userAvatarLabel: '头像',
    userNameLabel: '显示名称',
    userNamePlaceholder: '输入你的名称...',
    userBioLabel: '自我介绍',
    userBioPlaceholder: '写一段关于自己的介绍，Agent 会读取...',
    userBioHint: 'Agent 会在对话中读取此内容来了解你。',
    avatarTooBig: '图片不能超过 2MB',
    avatarBadFormat: '仅支持 JPG / PNG / GIF / WebP 格式',
    uploadBtn: '上传',
    presetBtn: '预设',
    removeBtn: '移除',
    profileSaved: '个人资料已保存',
  },

  en: {
    // ── Sidebar ──
    appTitle: 'HERMES AGENTS CHAT',
    appSubtitle: 'Multi-agent Collaboration',
    roomsSection: 'Rooms',
    contactsSection: 'Contacts',
    newRoomBtn: '＋ New Room',
    offline: 'offline',
    agentsUnit: 'agents',
    msgsUnit: 'msgs',
    noAgents: 'No agents',

    // ── Chat Area ──
    selectRoom: 'Select a room to start chatting',
    selectRoomHint: 'Or create a new one from the sidebar',
    inputPlaceholder: 'Type a message... (@ to mention agents)',
    sendTitle: 'Send (Enter)',
    roomSettingsTitle: 'Room Settings',

    // ── Typing ──
    typingOne: '{name} is typing...',
    typingTwo: '{n1}, {n2} are typing...',
    typingMany: '{n1}, {n2} and {count} others are typing...',

    // ── Modals: Settings ──
    roomNameLabel: 'Room Name',
    agentsLabel: 'Agents',
    deleteBtn: 'Delete',
    cancelBtn: 'Cancel',
    saveBtn: 'Save',
    roomNamePlaceholder: 'Room name',
    newRoomPlaceholder: 'Enter room name...',

    // ── Modals: New Room ──
    newRoomTitle: 'New Room',
    selectAgentsLabel: 'Select Agents',
    createBtn: 'Create',

    // ── Modals: Agent Profile ──
    aliasLabel: 'Alias',
    aliasPlaceholder: 'Enter alias...',
    aliasEmpty: 'Click to set alias...',
    aliasSave: 'Save',
    aliasCancel: 'Cancel',
    soulLabel: 'SOUL',
    noSoul: 'No soul defined.',
    soulPlaceholder: 'Enter agent role description...',
    soulSave: 'Sync to Profile',
    soulSaved: 'Soul synced to profile',
    saving: 'Saving...',
    soulSyncHint: 'Click save to take effect immediately',
    closeBtn: 'Close',
    startChatBtn: '💬 Start Chat',
    presetAvatar: 'Preset',
    uploadAvatar: 'Upload',
    useDefaultAvatar: 'Use default avatar',
    clickToUpload: 'Click to upload',
    clickToChange: 'Click to change',
    currentAvatar: 'Current avatar',
    agentAvatarSizeError: 'Image must be ≤ 2MB',
    agentAvatarTypeError: 'Only JPG/PNG/GIF supported',

    // ── Modals: New Agent ──
    newAgentBtn: '＋ New Agent',
    newAgentTitle: 'New Agent',
    agentNameLabel: 'Agent Name',
    agentNamePlaceholder: 'Enter agent name (letters, digits, underscores)...',
    agentRoleLabel: 'Role / Display Name',
    agentRolePlaceholder: 'e.g. CTO & Algorithm Architect',
    agentSoulLabel: 'SOUL / System Prompt',
    agentSoulPlaceholder: 'Describe the agent role and behavior...',
    newAgentNameRequired: 'Agent name is required',
    newAgentSoulRequired: 'SOUL is required',
    agentCreated: '✓ Agent created, joined War Room',

    // ── Validation / Toasts ──
    roomNameRequired: 'Room name is required',
    atLeastOneAgent: 'At least one agent required',
    selectOneAgent: 'Select at least one agent',
    deleteConfirm: 'Delete this room permanently?',
    roomUpdated: '✓ Room updated',
    roomDeleted: '✓ Room deleted',
    chatWith: 'Chat with {name}',
    agentSettings: 'Agent Settings',
    clearContext: 'Clear context',
    contextClearedDivider: '── ✨ Context cleared ✨ ──',
    contextClearedToast: 'Context cleared, previous content archived',

    // ── Scroll / Pagination ──
    loadingMessages: 'Loading messages...',
    loadingMore: 'Loading more...',
    noMoreMessages: '—— No more messages ——',
    noMessages: 'No messages yet. Send the first one!',

    // ── Delete Confirm ──
    deleteTitle: 'Delete Room',
    deleteBody: 'Permanently delete "{name}"?',
    deleteWarning: 'All chat records in this room will be permanently deleted and cannot be recovered.',
    deleteConfirmBtn: 'Confirm Delete',

    // ── Error ──
    unknownAgents: 'Unknown agents: ',

    // ── User Settings ──
    userSettingsTitle: 'My Profile',
    userAvatarLabel: 'Avatar',
    userNameLabel: 'Display Name',
    userNamePlaceholder: 'Enter your name...',
    userBioLabel: 'About Me',
    userBioPlaceholder: 'Write something about yourself. Agents will read this...',
    userBioHint: 'Agents will read this to understand you.',
    avatarTooBig: 'Image must be under 2MB',
    avatarBadFormat: 'Only JPG / PNG / GIF / WebP supported',
    uploadBtn: 'Upload',
    presetBtn: 'Presets',
    removeBtn: 'Remove',
    profileSaved: 'Profile saved',
  },
};

// ── API ──

let _lang = 'zh-CN';

/** Load persisted language or detect from browser. */
export function initLang() {
  try {
    const stored = localStorage.getItem(LS_KEY);
    if (stored && DICT[stored]) {
      _lang = stored;
      return _lang;
    }
  } catch (_) { /* noop */ }

  // Detect browser language
  const nav = (typeof navigator !== 'undefined' && navigator.language) || '';
  _lang = nav.startsWith('zh') ? 'zh-CN' : 'en';
  return _lang;
}

/** Get current language code. */
export function getLang() {
  return _lang;
}

/** Set language and persist. */
export function setLang(code) {
  if (!DICT[code]) return;
  _lang = code;
  try { localStorage.setItem(LS_KEY, code); } catch (_) { /* noop */ }
}

/** Translate a key, with optional template vars. */
export function t(key, vars = {}) {
  let template = (DICT[_lang] && DICT[_lang][key]) || DICT['en'][key] || key;
  return template.replace(/\{(\w+)\}/g, (_, k) =>
    vars[k] !== undefined ? vars[k] : `{${k}}`
  );
}

/** Get available languages. */
export function availableLangs() {
  return Object.keys(DICT).map(code => ({
    code,
    label: code === 'zh-CN' ? '中文' : 'English',
  }));
}

export default { initLang, getLang, setLang, t, availableLangs };
