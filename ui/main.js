(() => {
  'use strict';

  const state = {
    sessionId: localStorage.getItem('hv_session_id') || crypto.randomUUID(),
    theme: localStorage.getItem('hv_theme') || 'light',
    aiEnabled: localStorage.getItem('hv_ai_enabled') === 'true',
    ttsEnabled: false, liveEnabled: false, isLoading: false, isSpeaking: false,
    recognition: null, recognitionRunning: false, turn: 0, listenTimer: null, transcript: [],
  };
  localStorage.setItem('hv_session_id', state.sessionId);

  const $ = (name) => document.querySelector(`[data-hv="${name}"]`);
  const dom = {
    theme: $('theme-toggle'), ai: $('ai-toggle'), live: $('live-toggle'),
    statusDot: $('status-dot'), statusText: $('status-text'), documents: $('doc-list'),
    thread: $('thread'), input: $('chat-input'), send: $('send-btn'), mic: $('mic-btn'),
    tts: $('tts-toggle'), form: $('composer-form'), evidence: $('evidence-list'),
    suggestions: $('suggestions'), menu: $('menu-btn'), left: $('left-sidebar'),
    right: $('right-sidebar'), closeLeft: $('close-left'), closeRight: $('close-right'),
    overlay: $('overlay'), welcome: $('welcome'), liveStatus: $('live-status'),
    newConversation: $('new-conversation'), exportConversation: $('export-conversation'),
  };
  const escapeHTML = (value) => { const box = document.createElement('div'); box.textContent = value || ''; return box.innerHTML; };
  const scrollBottom = () => { dom.thread.scrollTop = dom.thread.scrollHeight; };
  const api = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'Không thể kết nối máy chủ.');
    return response.json();
  };
  const setStatus = (online, message) => {
    dom.statusDot.className = `status-indicator ${online ? 'online' : 'offline'}`;
    dom.statusText.textContent = message;
  };
  const setLiveStatus = (message, kind = '') => {
    dom.liveStatus.textContent = message;
    dom.liveStatus.className = `live-status ${kind}`.trim();
  };
  const updateComposer = () => {
    dom.input.style.height = 'auto'; dom.input.style.height = `${Math.min(dom.input.scrollHeight, 180)}px`;
    dom.send.disabled = !dom.input.value.trim() || state.isLoading;
  };
  const updateFeatureControls = () => {
    dom.ai.classList.toggle('active', state.aiEnabled); dom.ai.setAttribute('aria-pressed', String(state.aiEnabled));
    dom.ai.title = state.aiEnabled ? 'AI diễn đạt theo nguồn: bật' : 'AI diễn đạt theo nguồn: tắt';
    dom.live.classList.toggle('active', state.liveEnabled); dom.live.setAttribute('aria-pressed', String(state.liveEnabled));
    dom.live.textContent = state.liveEnabled ? 'Live đang bật' : 'Live';
    dom.tts.classList.toggle('active', state.ttsEnabled);
  };
  function remember(role, text, extra = {}) {
    state.transcript.push({ role, text, ...extra });
  }
  function appendUser(text, { restore = false } = {}) {
    dom.welcome.hidden = true;
    const item = document.createElement('article'); item.className = 'message user';
    item.innerHTML = `<div class="bubble"><p>${escapeHTML(text)}</p></div>`; dom.thread.appendChild(item);
    remember('user', text); scrollBottom();
  }
  function appendSystem(text) {
    const item = document.createElement('article'); item.className = 'message bot live-note';
    item.innerHTML = `<div class="avatar">Live</div><div class="bubble"><p>${escapeHTML(text)}</p></div>`;
    dom.thread.appendChild(item); scrollBottom();
  }
  function appendTyping() {
    const item = document.createElement('article'); item.id = 'typing-indicator'; item.className = 'message bot typing';
    item.innerHTML = '<div class="avatar">AI</div><div class="bubble"><div class="typing-indicator"><i></i><i></i><i></i></div></div>';
    dom.thread.appendChild(item); scrollBottom();
  }
  const removeTyping = () => document.getElementById('typing-indicator')?.remove();
  function updateEvidence(refs = []) {
    dom.evidence.innerHTML = refs.length ? refs.map((ref, index) => `<article class="evidence-card" id="evidence-${index + 1}"><div class="evidence-title">[${index + 1}] ${escapeHTML(ref.reg_title)}</div><div class="evidence-meta">${escapeHTML(ref.art_heading)}</div><p class="evidence-excerpt">${escapeHTML(ref.excerpt)}</p></article>`).join('') : '<div class="empty-state"><p>Không có trích dẫn cho phản hồi này.</p></div>';
  }
  function scheduleListening() {
    clearTimeout(state.listenTimer);
    if (!state.liveEnabled || state.isLoading || state.isSpeaking || state.recognitionRunning) return;
    setLiveStatus('Live sẵn sàng lắng nghe', 'listening');
    state.listenTimer = setTimeout(() => startListening(true), 450);
  }
  function speechText(text) {
    const replacements = [
      [/\bCCCD\b/gi, 'căn cước công dân'],
      [/\bHEMIS\b/gi, 'hệ thống hê mít'],
      [/\bCITADT\b/gi, 'Trung tâm Ứng dụng Công nghệ thông tin và Chuyển đổi số'],
      [/\bCT\s*-\s*CTSV\b/gi, 'Công tác sinh viên'],
      [/\bQLĐT\b/gi, 'Quản lý đào tạo'],
      [/\bĐHHP\b/gi, 'Đại học Hải Phòng'],
      [/\bQĐ\b/gi, 'quyết định'],
      [/\bSTT\b/gi, 'số thứ tự'],
      [/\bLLM\b/gi, 'mô hình ngôn ngữ lớn'],
      [/\bRAG\b/gi, 'rờ a gờ'],
      [/\bOCR\b/gi, 'nhận dạng ký tự quang học'],
      [/\bTTS\b/gi, 'chuyển văn bản thành giọng nói'],
      [/\bASR\b/gi, 'nhận dạng giọng nói'],
      [/\bPDF\b/gi, 'tệp pi đi ép'],
      [/\bDOCX\b/gi, 'tệp Word'],
      [/\bAI\b/g, 'trí tuệ nhân tạo'],
    ];
    let normalized = String(text || '');
    for (const [pattern, spoken] of replacements) normalized = normalized.replace(pattern, spoken);
    // Unknown uppercase codes are read as separate letters rather than a
    // made-up Vietnamese word (for example: BGDĐT -> B. G. D. Đ. T.).
    return normalized.replace(/\b[A-ZĐ]{2,}\b/g, (code) => code.split('').join('. ') + '.');
  }
  function preferredVietnameseVoice() {
    const voices = speechSynthesis.getVoices();
    return voices.find((voice) => /^vi(-|_)/i.test(voice.lang) && /hoaimy|namminh|vietnamese|việt/i.test(voice.name))
      || voices.find((voice) => /^vi(-|_)/i.test(voice.lang));
  }
  function speak(text) {
    if (!(state.ttsEnabled || state.liveEnabled) || !('speechSynthesis' in window)) { scheduleListening(); return; }
    speechSynthesis.cancel(); state.isSpeaking = true; setLiveStatus('AI đang đọc câu trả lời', 'working');
    const utterance = new SpeechSynthesisUtterance(speechText(text)); utterance.lang = 'vi-VN'; utterance.rate = state.liveEnabled ? .94 : 1;
    const voice = preferredVietnameseVoice(); if (voice) utterance.voice = voice;
    const done = () => { state.isSpeaking = false; if (!state.liveEnabled) setLiveStatus('Sẵn sàng nhập câu hỏi'); scheduleListening(); };
    utterance.onend = done; utterance.onerror = done; speechSynthesis.speak(utterance);
  }
  function copyAnswer(button, answer) {
    const copied = () => { button.textContent = 'Đã chép'; setTimeout(() => { button.textContent = 'Sao chép'; }, 1600); };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(answer).then(copied).catch(() => window.prompt('Sao chép câu trả lời:', answer));
    else window.prompt('Sao chép câu trả lời:', answer);
  }
  function appendAnswer(response, { restore = false } = {}) {
    state.turn++; const refs = response.references || [];
    const mode = response.metadata?.ai_mode || 'off';
    const modeLabel = mode === 'on' ? 'AI + nguồn' : mode === 'fallback' ? 'Nguồn trực tiếp · AI chưa sẵn sàng' : 'Nguồn trực tiếp';
    const followUps = !response.refused && !restore ? ['Nội dung này áp dụng trong trường hợp nào?', 'Có mốc thời gian hoặc điều kiện nào cần lưu ý?'] : [];
    const item = document.createElement('article'); item.className = `message bot${response.refused ? ' refused' : ''}`;
    item.innerHTML = `<div class="avatar">AI</div><div class="bubble"><p>${escapeHTML(response.answer).replace(/\n/g, '<br>')}</p><div class="citation-row">${refs.map((_, i) => `<button class="citation-chip" data-citation="${i + 1}" aria-label="Xem nguồn ${i + 1}">[${i + 1}]</button>`).join('')}</div>${followUps.length ? `<div class="follow-up-row">${followUps.map((question) => `<button class="follow-up-chip">${escapeHTML(question)}</button>`).join('')}</div>` : ''}<footer class="message-footer"><span class="intent-badge">${restore ? 'Lượt đã lưu' : modeLabel}</span><button class="copy-btn" aria-label="Sao chép câu trả lời">Sao chép</button></footer></div>`;
    item.querySelectorAll('[data-citation]').forEach((button) => button.addEventListener('click', () => document.getElementById(`evidence-${button.dataset.citation}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })));
    item.querySelector('.copy-btn').addEventListener('click', () => copyAnswer(item.querySelector('.copy-btn'), response.answer));
    item.querySelectorAll('.follow-up-chip').forEach((button) => button.addEventListener('click', () => send(button.textContent)));
    dom.thread.appendChild(item); remember('assistant', response.answer, { rid: refs[0]?.rid || response.rid || '' }); updateEvidence(refs); scrollBottom(); if (!restore) speak(response.answer);
  }
  function appendError(message) {
    const item = document.createElement('article'); item.className = 'message bot error';
    item.innerHTML = `<div class="avatar">!</div><div class="bubble"><p>${escapeHTML(message)}</p></div>`; dom.thread.appendChild(item); scrollBottom();
  }
  async function send(text = dom.input.value.trim()) {
    const question = text.trim(); if (!question || state.isLoading) return;
    state.isLoading = true; dom.input.value = ''; updateComposer(); setLiveStatus('Đang tìm trong tài liệu', 'working'); appendUser(question); appendTyping();
    try {
      const response = await api('/api/ask', { method: 'POST', body: JSON.stringify({ question, session_id: state.sessionId, use_ai: state.aiEnabled }) });
      removeTyping(); appendAnswer(response);
    } catch (error) { removeTyping(); appendError(error.message); scheduleListening(); }
    finally { state.isLoading = false; updateComposer(); if (!state.liveEnabled && !state.isSpeaking) setLiveStatus('Sẵn sàng nhập câu hỏi'); }
  }
  function startListening(fromLive = false) {
    if (!state.recognition || state.recognitionRunning || state.isLoading || state.isSpeaking) return;
    try { state.recognition.start(); } catch (_) { if (fromLive) scheduleListening(); }
  }
  function stopLive() {
    state.liveEnabled = false; clearTimeout(state.listenTimer); speechSynthesis?.cancel();
    if (state.recognitionRunning) state.recognition.stop(); updateFeatureControls(); setLiveStatus('Sẵn sàng nhập câu hỏi');
  }
  function setupVoice() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) { dom.mic.title = 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói'; dom.live.disabled = true; return; }
    const recognition = new Recognition(); recognition.lang = 'vi-VN'; recognition.interimResults = true; recognition.continuous = false;
    recognition.onstart = () => { state.recognitionRunning = true; dom.mic.classList.add('active'); dom.mic.setAttribute('aria-label', 'Dừng ghi âm'); setLiveStatus('Đang nghe…', 'listening'); };
    recognition.onend = () => { state.recognitionRunning = false; dom.mic.classList.remove('active'); dom.mic.setAttribute('aria-label', 'Nhập bằng giọng nói'); scheduleListening(); };
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') { stopLive(); appendError('Trình duyệt chưa được cấp quyền micro. Hãy cho phép micro rồi bật Live lại.'); }
      else if (event.error !== 'aborted' && event.error !== 'no-speech') appendError('Không thể nhận dạng giọng nói. Bạn có thể nói lại hoặc nhập bằng văn bản.');
    };
    recognition.onresult = (event) => {
      let transcript = ''; let isFinal = false;
      for (let index = event.resultIndex; index < event.results.length; index += 1) { transcript += event.results[index][0].transcript; isFinal ||= event.results[index].isFinal; }
      dom.input.value = transcript.trim(); updateComposer();
      if (isFinal && transcript.trim()) { recognition.stop(); send(transcript); }
    };
    state.recognition = recognition;
  }
  function startNewConversation() {
    stopLive();
    state.sessionId = crypto.randomUUID();
    state.turn = 0; state.transcript = [];
    localStorage.setItem('hv_session_id', state.sessionId);
    dom.thread.querySelectorAll('.message:not(.welcome-message)').forEach((item) => item.remove());
    dom.welcome.hidden = false; updateEvidence([]); setLiveStatus('Hội thoại mới đã sẵn sàng');
    dom.input.focus();
  }
  function exportConversation() {
    if (!state.transcript.length) { setLiveStatus('Chưa có hội thoại để xuất'); return; }
    const content = [
      'HOCVU AI — LỊCH SỬ HỘI THOẠI',
      `Xuất lúc: ${new Date().toLocaleString('vi-VN')}`,
      '',
      ...state.transcript.flatMap((entry) => [`${entry.role === 'user' ? 'BẠN' : 'HOCVU AI'}:`, entry.text, '']),
    ].join('\n');
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob);
    link.download = `hocvu-ai-${new Date().toISOString().slice(0, 10)}.txt`;
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(link.href);
    setLiveStatus('Đã tải tệp hội thoại về máy');
  }
  function restoreHistory(turns) {
    if (!Array.isArray(turns) || !turns.length) return;
    turns.forEach((turn) => {
      appendUser(turn.question, { restore: true });
      appendAnswer({ answer: turn.answer, intent: turn.intent }, { restore: true });
    });
    setLiveStatus(`Đã khôi phục ${turns.length} lượt gần nhất`);
  }
  function bind() {
    dom.theme.addEventListener('click', () => { state.theme = state.theme === 'light' ? 'dark' : 'light'; document.documentElement.dataset.theme = state.theme; localStorage.setItem('hv_theme', state.theme); });
    dom.ai.addEventListener('click', () => { state.aiEnabled = !state.aiEnabled; localStorage.setItem('hv_ai_enabled', String(state.aiEnabled)); updateFeatureControls(); });
    dom.newConversation.addEventListener('click', startNewConversation);
    dom.exportConversation.addEventListener('click', exportConversation);
    dom.live.addEventListener('click', () => {
      if (state.liveEnabled) { stopLive(); appendSystem('Đã dừng hội thoại Live.'); return; }
      state.liveEnabled = true; state.ttsEnabled = true; updateFeatureControls(); appendSystem('Chế độ Live đã bật. Tôi sẽ lắng nghe, trả lời và tự mở micro cho lượt tiếp theo. Bạn có thể bắt đầu nói.'); speak('Chế độ hội thoại Live đã bật. Bạn có thể bắt đầu nói.');
    });
    dom.input.addEventListener('input', updateComposer);
    dom.input.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } });
    dom.form.addEventListener('submit', (event) => { event.preventDefault(); send(); });
    dom.tts.addEventListener('click', () => { state.ttsEnabled = !state.ttsEnabled; if (!state.ttsEnabled && state.liveEnabled) stopLive(); else updateFeatureControls(); });
    dom.mic.addEventListener('click', () => { state.recognitionRunning ? state.recognition.stop() : startListening(false); });
    dom.suggestions.addEventListener('click', (event) => { if (event.target.matches('.suggestion-chip')) send(event.target.textContent); });
    const closeMenus = () => { dom.left.classList.remove('open'); dom.right.classList.remove('open'); dom.overlay.classList.remove('active'); };
    dom.menu.addEventListener('click', () => { dom.left.classList.toggle('open'); dom.overlay.classList.toggle('active'); });
    dom.closeLeft.addEventListener('click', closeMenus); dom.closeRight.addEventListener('click', closeMenus); dom.overlay.addEventListener('click', closeMenus);
  }
  async function boot() {
    document.documentElement.dataset.theme = state.theme; updateFeatureControls(); bind(); setupVoice();
    try {
      const [health, documents, history] = await Promise.all([
        api('/api/health'), api('/api/documents'), api(`/api/history?session_id=${encodeURIComponent(state.sessionId)}`),
      ]);
      setStatus(true, `Trực tuyến · ${health.documents} văn bản`);
      dom.documents.innerHTML = documents.map((doc) => `<article class="doc-item"><div class="doc-title">${escapeHTML(doc.title)}</div><div class="doc-meta">${escapeHTML(doc.rid)} · Bản ${escapeHTML(doc.version)}</div></article>`).join('');
      restoreHistory(history);
    } catch (_) { setStatus(false, 'Mất kết nối'); dom.documents.innerHTML = '<p class="error">Không thể tải cơ sở tri thức.</p>'; }
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
