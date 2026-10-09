(() => {
  'use strict';

  const state = {
    sessionId: localStorage.getItem('hv_session_id') || crypto.randomUUID(),
    theme: localStorage.getItem('hv_theme') || 'light',
    aiEnabled: localStorage.getItem('hv_ai_enabled') === 'true',
    ttsEnabled: false, liveEnabled: false, isLoading: false, isSpeaking: false,
    recognition: null, recognitionRunning: false, recognitionRequested: false, turn: 0, listenTimer: null, transcript: [], speechRetry: false, livePaused: false,
    ignoreRecognitionResults: false, listenAfter: 0, speechId: 0,
    lastAssistantSpeech: '', echoGuardUntil: 0,
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
    refDate: $('ref-date'),
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
  const citeLabel = (ref) => `${ref.aid || 'Nguồn'}, ${ref.clause_ids?.length ? `Khoản ${ref.clause_ids.join(', ')}` : 'nội dung liên quan'}`;
  const sourceCard = (ref, index, place) => `<article class="evidence-card source-card" id="${place}-src-${index + 1}" data-source-index="${index + 1}" tabindex="0"><div class="evidence-title">[${index + 1}] ${escapeHTML(citeLabel(ref))}</div><div class="evidence-meta">${escapeHTML(ref.reg_title)}</div><div class="source-heading">${escapeHTML(ref.art_heading)}</div><p class="evidence-excerpt">${escapeHTML(ref.excerpt)}</p></article>`;
  function flashSource(index) {
    document.querySelectorAll(`[data-source-index="${index}"]`).forEach((card) => { card.classList.add('flash'); setTimeout(() => card.classList.remove('flash'), 2000); });
    document.querySelectorAll(`[data-citation="${index}"]`).forEach((chip) => chip.classList.add('active'));
    setTimeout(() => document.querySelectorAll(`[data-citation="${index}"]`).forEach((chip) => chip.classList.remove('active')), 2000);
  }
  function updateEvidence(refs = []) {
    dom.evidence.innerHTML = refs.length ? refs.map((ref, index) => sourceCard(ref, index, 'evidence')).join('') : '<div class="empty-state"><p>Các căn cứ được dùng để trả lời sẽ hiển thị tại đây.</p></div>';
    dom.evidence.querySelectorAll('[data-source-index]').forEach((card) => card.addEventListener('click', () => flashSource(card.dataset.sourceIndex)));
  }
  function renderSuggestionTopics(topics = []) {
    dom.suggestions.innerHTML = topics.length ? topics.map((topic, index) => `<section class="topic-card"><button class="topic-toggle" data-topic="${index}" aria-expanded="false"><span>${escapeHTML(topic.topic)}</span><small>${topic.questions.length} câu hỏi</small></button><div class="topic-questions" data-topic-questions="${index}" hidden>${topic.questions.map((question) => `<button class="suggestion-chip">${escapeHTML(question)}</button>`).join('')}</div></section>`).join('') : '<span class="loading-pulse">Chưa có câu hỏi gợi ý.</span>';
  }
  function scheduleListening() {
    clearTimeout(state.listenTimer);
    if (!state.liveEnabled || state.livePaused || state.isLoading || state.isSpeaking || state.recognitionRunning) return;
    setLiveStatus('Live sẵn sàng lắng nghe', 'listening');
    // Leave a short acoustic gap after TTS finishes. Without it, Chromium can
    // feed the last syllables from the speaker back into SpeechRecognition.
    const delay = Math.max(450, state.listenAfter - Date.now());
    state.listenTimer = setTimeout(() => {
      state.listenTimer = null;
      if (Date.now() < state.listenAfter) { scheduleListening(); return; }
      startListening(true);
    }, delay);
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
    if (!(state.ttsEnabled || state.liveEnabled) || !('speechSynthesis' in window)) {
      if (state.liveEnabled) state.livePaused = false;
      scheduleListening();
      return;
    }
    // Chromium may populate voices asynchronously just after page load.
    // Retry once so the first Vietnamese answer does not use a random voice.
    if (!speechSynthesis.getVoices().length && !state.speechRetry) {
      state.speechRetry = true;
      setTimeout(() => { state.speechRetry = false; speak(text); }, 180);
      return;
    }
    const speechId = ++state.speechId;
    const spoken = speechText(text);
    state.lastAssistantSpeech = spoken;
    speechSynthesis.cancel(); state.isSpeaking = true; setLiveStatus('AI đang đọc câu trả lời', 'working');
    const utterance = new SpeechSynthesisUtterance(spoken); utterance.lang = 'vi-VN'; utterance.rate = state.liveEnabled ? .94 : 1;
    const voice = preferredVietnameseVoice(); if (voice) utterance.voice = voice;
    const done = () => {
      // cancel() emits an end event for the previous utterance. Only the
      // currently active utterance is allowed to reopen the microphone.
      if (speechId !== state.speechId) return;
      state.isSpeaking = false;
      if (!state.liveEnabled) setLiveStatus('Sẵn sàng nhập câu hỏi');
      else {
        state.livePaused = false;
        state.listenAfter = Date.now() + 1100;
        state.echoGuardUntil = Date.now() + 9000;
      }
      scheduleListening();
    };
    utterance.onend = done; utterance.onerror = done; speechSynthesis.speak(utterance);
  }
  function copyAnswer(button, answer) {
    const copied = () => { button.textContent = 'Đã chép'; setTimeout(() => { button.textContent = 'Sao chép'; }, 1600); };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(answer).then(copied).catch(() => window.prompt('Sao chép câu trả lời:', answer));
    else window.prompt('Sao chép câu trả lời:', answer);
  }
  const meter = (grounding = {}) => `<span class="grounding-meter ${escapeHTML(grounding.label || 'yếu')}">${[1, 2, 3, 4, 5].map((step) => `<i class="${step <= (grounding.level || 0) ? 'on' : ''}"></i>`).join('')}<b>Căn cứ ${escapeHTML(grounding.label || 'yếu')} · ${grounding.source_count || 0} nguồn</b></span>`;
  const noteIcon = (icon) => ({ calendar: '◷', document: '▤', scope: '◎', replace: '↔' }[icon] || '•');
  function cardMarkdown(segments, refs) {
    return [segments.map((segment) => segment.text).join('\n\n'), '', ...refs.map((ref, index) => `Nguồn [${index + 1}]: ${citeLabel(ref)} — ${ref.reg_title}\n${ref.excerpt}`)].join('\n');
  }
  function renderAnswerCard(response, refs, restore, cardId) {
    const card = response.card || {};
    const segments = card.verdict_segments?.length ? card.verdict_segments : [{ text: response.answer, cites: [] }];
    if (response.refused) return `<section class="refusal-card"><h3>Chưa tìm thấy căn cứ</h3><p>${escapeHTML(response.answer)}</p><p class="refusal-hint">Tôi không đoán mò khi nguồn chưa đủ rõ. Bạn có thể thử một trong các câu hỏi có căn cứ sau:</p><div class="follow-up-row">${(card.suggestions || []).map((question) => `<button class="follow-up-chip">${escapeHTML(question)}</button>`).join('')}</div></section>`;
    return `<section class="answer-card"><header class="answer-card-header"><div><span class="card-kicker">Phiếu kết quả tra cứu</span><h3>Kết luận</h3></div>${meter(card.grounding)}</header><div class="verdict-list">${segments.map((segment) => `<p>${escapeHTML(segment.text).replace(/\n/g, '<br>')} ${segment.cites.map((cite) => `<button class="citation-chip" data-citation="${cite}" aria-label="Xem nguồn ${cite}">[${cite}]</button>`).join('')}</p>`).join('')}</div>${card.notes?.length ? `<section class="card-notes"><h4>Lưu ý</h4>${card.notes.map((note) => `<p><span>${noteIcon(note.icon)}</span>${escapeHTML(note.text)}</p>`).join('')}</section>` : ''}<footer class="message-footer"><span class="intent-badge">${restore ? 'Lượt đã lưu' : 'Nguồn đã đối chiếu'}</span><button class="copy-btn" aria-label="Sao chép kèm nguồn">Sao chép kèm nguồn</button></footer></section>`;
  }
  function appendAnswer(response, { restore = false } = {}) {
    state.turn++; const refs = response.references || [];
    const segments = response.card?.verdict_segments || [{ text: response.answer, cites: [] }];
    const item = document.createElement('article'); item.className = `message bot${response.refused ? ' refused' : ''}`;
    item.innerHTML = `<div class="avatar">AI</div><div class="bubble card-bubble">${renderAnswerCard(response, refs, restore, state.turn)}</div>`;
    item.querySelectorAll('[data-citation]').forEach((button) => button.addEventListener('click', () => { const source = item.querySelector(`[data-source-index="${button.dataset.citation}"]`) || document.getElementById(`evidence-src-${button.dataset.citation}`); source?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); flashSource(button.dataset.citation); }));
    item.querySelectorAll('[data-source-index]').forEach((card) => card.addEventListener('click', () => flashSource(card.dataset.sourceIndex)));
    item.querySelector('.copy-btn')?.addEventListener('click', () => copyAnswer(item.querySelector('.copy-btn'), cardMarkdown(segments, refs)));
    item.querySelectorAll('.follow-up-chip').forEach((button) => button.addEventListener('click', () => send(button.textContent)));
    dom.thread.appendChild(item); remember('assistant', response.answer, { references: refs.map((ref) => ({ reg_title: ref.reg_title, art_heading: ref.art_heading, rid: ref.rid })) }); updateEvidence(refs); scrollBottom(); if (!restore) speak(segments.map((segment) => segment.text).join('. '));
  }
  function appendError(message) {
    const item = document.createElement('article'); item.className = 'message bot error';
    item.innerHTML = `<div class="avatar">!</div><div class="bubble"><p>${escapeHTML(message)}</p></div>`; dom.thread.appendChild(item); scrollBottom();
  }
  function pauseRecognitionForTextTurn() {
    clearTimeout(state.listenTimer);
    state.livePaused = true;
    if (!state.recognitionRunning && !state.recognitionRequested) return;
    // Abort rather than wait for a final result: a clicked suggestion or typed
    // question must never share a listening turn with the bot's answer.
    state.ignoreRecognitionResults = true;
    try { state.recognition.abort(); } catch (_) { /* recognition already ended */ }
  }
  function speechWords(value) {
    return speechText(value).toLocaleLowerCase('vi-VN').normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '').match(/[a-zđ0-9]+/g) || [];
  }
  function isLikelySpeakerEcho(text) {
    if (!state.liveEnabled || Date.now() > state.echoGuardUntil) return false;
    const heard = speechWords(text); const spoken = speechWords(state.lastAssistantSpeech);
    if (heard.length < 4 || !spoken.length) return false;
    const spokenSet = new Set(spoken); const uniqueHeard = new Set(heard);
    let shared = 0; uniqueHeard.forEach((word) => { if (spokenSet.has(word)) shared += 1; });
    return shared / uniqueHeard.size >= 0.8;
  }
  async function send(text = dom.input.value.trim(), { source = 'text' } = {}) {
    const question = text.trim(); if (!question || state.isLoading) return;
    if (source === 'text') pauseRecognitionForTextTurn();
    else { clearTimeout(state.listenTimer); state.livePaused = true; }
    state.isLoading = true; dom.input.value = ''; updateComposer(); setLiveStatus('Đang tìm trong tài liệu', 'working'); appendUser(question); appendTyping();
    try {
      const response = await api('/api/ask', { method: 'POST', body: JSON.stringify({ question, session_id: state.sessionId, use_ai: state.aiEnabled, ref_date: dom.refDate.value || null }) });
      removeTyping(); appendAnswer(response);
    } catch (error) {
      removeTyping(); appendError(error.message);
      if (state.liveEnabled) state.livePaused = false;
      scheduleListening();
    }
    finally { state.isLoading = false; updateComposer(); if (!state.liveEnabled && !state.isSpeaking) setLiveStatus('Sẵn sàng nhập câu hỏi'); }
  }
  function startListening(fromLive = false) {
    if (!state.recognition || state.recognitionRunning || state.recognitionRequested || state.isLoading || state.isSpeaking) return;
    if (!fromLive) state.livePaused = false;
    state.recognitionRequested = true;
    try { state.recognition.start(); } catch (_) { state.recognitionRequested = false; if (fromLive) scheduleListening(); }
  }
  function stopLive() {
    state.liveEnabled = false; state.livePaused = false; clearTimeout(state.listenTimer); speechSynthesis?.cancel();
    if (state.recognitionRunning || state.recognitionRequested) state.recognition.abort(); updateFeatureControls(); setLiveStatus('Sẵn sàng nhập câu hỏi');
  }
  function setupVoice() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) { dom.mic.title = 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói'; dom.live.disabled = true; return; }
    const recognition = new Recognition(); recognition.lang = 'vi-VN'; recognition.interimResults = true; recognition.continuous = false;
    recognition.onstart = () => {
      state.recognitionRunning = true;
      if (state.livePaused || state.isLoading || state.isSpeaking) {
        state.ignoreRecognitionResults = true; recognition.abort(); return;
      }
      state.ignoreRecognitionResults = false; dom.mic.classList.add('active'); dom.mic.setAttribute('aria-label', 'Dừng ghi âm'); setLiveStatus('Đang nghe…', 'listening');
    };
    recognition.onend = () => { state.recognitionRunning = false; state.recognitionRequested = false; dom.mic.classList.remove('active'); dom.mic.setAttribute('aria-label', 'Nhập bằng giọng nói'); scheduleListening(); };
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') { stopLive(); appendError('Trình duyệt chưa được cấp quyền micro. Hãy cho phép micro rồi bật Live lại.'); }
      else if (event.error === 'no-speech') {
        state.livePaused = state.liveEnabled;
        setLiveStatus(state.liveEnabled ? 'Không nghe thấy lời nói. Nhấn micro để nói tiếp.' : 'Không nghe thấy lời nói.');
      } else if (event.error !== 'aborted') {
        state.livePaused = state.liveEnabled;
        appendError('Không thể nhận dạng giọng nói. Hãy bấm micro để thử lại hoặc nhập bằng văn bản.');
      }
    };
    recognition.onresult = (event) => {
      let transcript = ''; let isFinal = false;
      for (let index = event.resultIndex; index < event.results.length; index += 1) { transcript += event.results[index][0].transcript; isFinal ||= event.results[index].isFinal; }
      if (state.ignoreRecognitionResults || state.isSpeaking || state.isLoading) return;
      dom.input.value = transcript.trim(); updateComposer();
      if (isFinal && transcript.trim()) {
        if (isLikelySpeakerEcho(transcript)) {
          state.livePaused = true;
          recognition.stop();
          setLiveStatus('Đã bỏ qua âm thanh của AI. Nhấn micro để nói tiếp.');
          return;
        }
        state.livePaused = true; recognition.stop(); send(transcript, { source: 'speech' });
      }
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
      ...state.transcript.flatMap((entry) => [
        `${entry.role === 'user' ? 'BẠN' : 'HOCVU AI'}:`, entry.text,
        ...(entry.references?.length ? ['Nguồn: ' + entry.references.map((ref) => `${ref.reg_title} — ${ref.art_heading}`).join('; ')] : []),
        '',
      ]),
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
      state.liveEnabled = true; state.livePaused = false; state.ttsEnabled = true; updateFeatureControls(); appendSystem('Chế độ Live đã bật. Tôi sẽ lắng nghe, trả lời và tự mở micro cho lượt tiếp theo. Bạn có thể bắt đầu nói.'); speak('Chế độ hội thoại Live đã bật. Bạn có thể bắt đầu nói.');
    });
    dom.input.addEventListener('input', updateComposer);
    dom.input.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } });
    dom.form.addEventListener('submit', (event) => { event.preventDefault(); send(); });
    dom.tts.addEventListener('click', () => { state.ttsEnabled = !state.ttsEnabled; if (!state.ttsEnabled && state.liveEnabled) stopLive(); else updateFeatureControls(); });
    dom.mic.addEventListener('click', () => { state.recognitionRunning ? state.recognition.stop() : startListening(false); });
    dom.suggestions.addEventListener('click', (event) => {
      const topic = event.target.closest('[data-topic]');
      if (topic) { const questions = dom.suggestions.querySelector(`[data-topic-questions="${topic.dataset.topic}"]`); const open = questions.hidden; questions.hidden = !open; topic.setAttribute('aria-expanded', String(open)); }
      if (event.target.matches('.suggestion-chip')) send(event.target.textContent, { source: 'text' });
    });
    document.addEventListener('keydown', (event) => {
      const editable = event.target.matches('input, textarea, select, [contenteditable="true"]');
      if (event.key === '/' && !event.ctrlKey && !event.altKey && !event.metaKey && !editable) {
        event.preventDefault(); dom.input.focus();
      }
    });
    const closeMenus = () => { dom.left.classList.remove('open'); dom.right.classList.remove('open'); dom.overlay.classList.remove('active'); };
    dom.menu.addEventListener('click', () => { dom.left.classList.toggle('open'); dom.overlay.classList.toggle('active'); });
    dom.closeLeft.addEventListener('click', closeMenus); dom.closeRight.addEventListener('click', closeMenus); dom.overlay.addEventListener('click', closeMenus);
  }
  async function boot() {
    document.documentElement.dataset.theme = state.theme; updateFeatureControls(); bind(); setupVoice();
    try {
      const [health, documents, history, topics] = await Promise.all([
        api('/api/health'), api('/api/documents'), api(`/api/history?session_id=${encodeURIComponent(state.sessionId)}`), api('/api/suggestions'),
      ]);
      setStatus(true, `Trực tuyến · ${health.documents} văn bản`);
      dom.documents.innerHTML = documents.map((doc) => `<article class="doc-item"><div class="doc-title">${escapeHTML(doc.title)}</div><div class="doc-meta">${escapeHTML(doc.rid)} · Bản ${escapeHTML(doc.version)}</div></article>`).join('');
      renderSuggestionTopics(topics);
      restoreHistory(history);
    } catch (_) { setStatus(false, 'Mất kết nối'); dom.documents.innerHTML = '<p class="error">Không thể tải cơ sở tri thức.</p>'; }
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
