(() => {
  'use strict';

  // A per-browser bearer capability, independent of shared document login.
  // Only its hash is stored server-side; never put it in URLs or exports.
  const ownerKey = localStorage.getItem('hv_conversation_owner')
    || (crypto.randomUUID() + crypto.randomUUID()).replaceAll('-', '');
  localStorage.setItem('hv_conversation_owner', ownerKey);
  const state = {
    sessionId: localStorage.getItem('hv_session_id') || crypto.randomUUID(),
    theme: localStorage.getItem('hv_theme') || 'light',
    aiEnabled: localStorage.getItem('hv_ai_enabled') === 'true',
    ttsEnabled: false, liveEnabled: false, isLoading: false, isSpeaking: false,
    recognition: null, recognitionRunning: false, recognitionRequested: false, turn: 0, listenTimer: null, transcript: [], speechRetry: false, livePaused: false,
    ignoreRecognitionResults: false, listenAfter: 0, speechId: 0, audio: null, speechTimer: null,
    lastAssistantSpeech: '', echoGuardUntil: 0,
    isDeleting: false, isRestoring: false, viewVersion: 0,
    conversations: [], listVersion: 0,
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
    deleteHistory: $('delete-history'),
    conversationSelect: $('conversation-select'), conversationRefresh: $('conversation-refresh'),
    conversationStatus: $('conversation-status'),
    refDate: $('ref-date'),
  };
  const escapeHTML = (value) => { const box = document.createElement('div'); box.textContent = value || ''; return box.innerHTML; };
  const scrollBottom = () => { dom.thread.scrollTop = dom.thread.scrollHeight; };
  const api = async (url, options = {}) => {
    const response = await fetch(url, { ...options, cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-HocVu-Owner': ownerKey, ...(options.headers || {}) } });
    return HocVuAPI.readResponse(response, 'Không thể kết nối máy chủ.');
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
    dom.send.disabled = !dom.input.value.trim() || state.isLoading || state.isDeleting || state.isRestoring;
    dom.newConversation.disabled = state.isDeleting;
    dom.deleteHistory.disabled = state.isLoading || state.isDeleting || state.isRestoring;
    dom.exportConversation.disabled = state.isDeleting;
    dom.mic.disabled = state.isDeleting || state.isRestoring;
    dom.live.disabled = !state.recognition || state.isDeleting || state.isRestoring;
    dom.conversationSelect.disabled = state.isDeleting;
    dom.conversationRefresh.disabled = state.isDeleting;
  };
  const updateFeatureControls = () => {
    dom.ai.classList.toggle('active', state.aiEnabled); dom.ai.setAttribute('aria-pressed', String(state.aiEnabled));
    dom.ai.title = state.aiEnabled ? 'AI diễn đạt theo nguồn: bật' : 'AI diễn đạt theo nguồn: tắt';
    dom.live.classList.toggle('active', state.liveEnabled); dom.live.setAttribute('aria-pressed', String(state.liveEnabled));
    dom.live.textContent = state.liveEnabled ? 'Live đang bật' : 'Live';
    dom.tts.classList.toggle('active', state.ttsEnabled);
  };
  function remember(role, text, extra = {}) {
    // Keep the evidence as it was displayed, independent of later responses.
    state.transcript.push({ role, text, ...JSON.parse(JSON.stringify(extra)) });
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
    item.innerHTML = '<div class="avatar">AI</div><div class="bubble"><div class="typing-indicator" role="status" aria-label="Đang trả lời"><i class="typing-dot" aria-hidden="true"></i><i class="typing-dot" aria-hidden="true"></i><i class="typing-dot" aria-hidden="true"></i></div></div>';
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
    dom.suggestions.innerHTML = topics.length ? topics.map((topic, index) => `<section class="topic-card"><button class="topic-toggle" type="button" data-topic="${index}" aria-expanded="false"><span>${escapeHTML(topic.topic)}</span><small>${topic.questions.length} câu hỏi</small></button><div class="topic-questions" data-topic-questions="${index}" hidden>${topic.questions.map((question) => `<button class="suggestion-chip" type="button">${escapeHTML(question)}</button>`).join('')}</div></section>`).join('') : '<span class="loading-pulse">Chưa có câu hỏi gợi ý.</span>';
  }
  function scheduleListening() {
    clearTimeout(state.listenTimer);
    if (!state.liveEnabled || state.livePaused || state.isLoading || state.isDeleting || state.isRestoring || state.isSpeaking || state.recognitionRunning) return;
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
  function releaseAudio(audio) {
    audio.onended = null; audio.onerror = null;
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
  }
  function stopSpeech() {
    // Invalidate callbacks before cancel/load can deliver asynchronous events.
    state.speechId++;
    clearTimeout(state.speechTimer); state.speechTimer = null; state.speechRetry = false;
    const audio = state.audio; state.audio = null;
    if (audio) releaseAudio(audio);
    window.speechSynthesis?.cancel();
    state.isSpeaking = false;
  }
  function speak(text, audioUrl = null) {
    stopSpeech();
    if (!(state.ttsEnabled || state.liveEnabled)) {
      if (state.liveEnabled) state.livePaused = false;
      scheduleListening();
      return;
    }
    const speechId = state.speechId;
    const spoken = speechText(text);
    state.lastAssistantSpeech = spoken;
    state.isSpeaking = true; setLiveStatus('AI đang đọc câu trả lời', 'working');
    const done = () => {
      if (speechId !== state.speechId || !state.isSpeaking) return;
      const audio = state.audio; state.audio = null;
      if (audio) releaseAudio(audio);
      clearTimeout(state.speechTimer); state.speechTimer = null; state.speechRetry = false;
      state.isSpeaking = false;
      if (!state.liveEnabled) setLiveStatus('Sẵn sàng nhập câu hỏi');
      else {
        state.livePaused = false;
        state.listenAfter = Date.now() + 1100;
        state.echoGuardUntil = Date.now() + 9000;
      }
      scheduleListening();
    };

    if (audioUrl) {
      const audio = new Audio(audioUrl);
      state.audio = audio;
      audio.onended = done;
      const fallback = () => {
        if (speechId !== state.speechId || state.audio !== audio) return;
        state.audio = null; releaseAudio(audio);
        speakBrowser(spoken, speechId, done);
      };
      audio.onerror = fallback;
      try { audio.play().catch(fallback); } catch (_) { fallback(); }
      return;
    }
    speakBrowser(spoken, speechId, done);
  }

  function speakBrowser(spoken, speechId, done) {
    if (speechId !== state.speechId || !state.isSpeaking) return;
    if (!('speechSynthesis' in window)) { done(); return; }
    if (!speechSynthesis.getVoices().length && !state.speechRetry) {
      state.speechRetry = true;
      state.speechTimer = setTimeout(() => {
        if (speechId !== state.speechId) return;
        state.speechTimer = null;
        speakBrowser(spoken, speechId, done);
      }, 180);
      return;
    }
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.lang = 'vi-VN';
    utterance.rate = state.liveEnabled ? .94 : 1;
    const voice = preferredVietnameseVoice();
    if (voice) utterance.voice = voice;
    utterance.onend = done;
    utterance.onerror = done;
    speechSynthesis.speak(utterance);
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
  function hasSavedEvidence(response) {
    const grounding = response.card?.grounding;
    return typeof response.refused === 'boolean' && Array.isArray(response.references)
      && grounding && Number.isFinite(grounding.level) && Number.isFinite(grounding.source_count)
      && typeof grounding.label === 'string';
  }
  function renderAnswerCard(response, refs, restore, cardId) {
    const card = response.card || {};
    const segments = card.verdict_segments?.length ? card.verdict_segments : [{ text: response.answer, cites: [] }];
    if (response.refused) return `<section class="refusal-card"><h3>Chưa tìm thấy căn cứ</h3><p>${escapeHTML(response.answer)}</p><p class="refusal-hint">Tôi không đoán mò khi nguồn chưa đủ rõ. Bạn có thể thử một trong các câu hỏi có căn cứ sau:</p><div class="follow-up-row">${(card.suggestions || []).map((question) => `<button class="follow-up-chip" type="button">${escapeHTML(question)}</button>`).join('')}</div></section>`;
    if (response.intent === 'greeting') return `<p class="greeting-message">${escapeHTML(response.answer).replace(/\n/g, '<br>')}</p>`;
    if (restore && !hasSavedEvidence(response)) {
      return `<section class="history-message"><p>${escapeHTML(response.answer).replace(/\n/g, '<br>')}</p><p class="history-hint">Lượt đã lưu · Chi tiết căn cứ không có trong bản lưu này.</p></section>`;
    }
    return `<section class="answer-card"><header class="answer-card-header"><div><span class="card-kicker">Phiếu kết quả tra cứu</span><h3>Kết luận</h3></div>${meter(card.grounding)}</header><div class="verdict-list">${segments.map((segment) => `<p>${escapeHTML(segment.text).replace(/\n/g, '<br>')} ${segment.cites.map((cite) => `<button class="citation-chip" type="button" data-citation="${cite}" aria-label="Xem nguồn ${cite}">[${cite}]</button>`).join('')}</p>`).join('')}</div>${card.notes?.length ? `<section class="card-notes"><h4>Lưu ý</h4>${card.notes.map((note) => `<p><span>${noteIcon(note.icon)}</span>${escapeHTML(note.text)}</p>`).join('')}</section>` : ''}<footer class="message-footer"><span class="intent-badge">${restore ? 'Lượt đã lưu' : 'Nguồn đã đối chiếu'}</span><button class="copy-btn" type="button" aria-label="Sao chép kèm nguồn">Sao chép kèm nguồn</button></footer></section>`;
  }
  function appendAnswer(response, { restore = false } = {}) {
    state.turn++; const refs = response.references || [];
    const segments = response.card?.verdict_segments || [{ text: response.answer, cites: [] }];
    const item = document.createElement('article'); item.className = `message bot${response.refused ? ' refused' : ''}`;
    const plain = !response.refused && (response.intent === 'greeting' || (restore && !hasSavedEvidence(response)));
    item.innerHTML = `<div class="avatar">AI</div><div class="bubble${plain ? '' : ' card-bubble'}">${renderAnswerCard(response, refs, restore, state.turn)}</div>`;
    item.querySelectorAll('[data-citation]').forEach((button) => button.addEventListener('click', () => { updateEvidence(refs); const source = item.querySelector(`[data-source-index="${button.dataset.citation}"]`) || document.getElementById(`evidence-src-${button.dataset.citation}`); source?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); flashSource(button.dataset.citation); }));
    item.querySelectorAll('[data-source-index]').forEach((card) => card.addEventListener('click', () => flashSource(card.dataset.sourceIndex)));
    item.querySelector('.copy-btn')?.addEventListener('click', () => copyAnswer(item.querySelector('.copy-btn'), cardMarkdown(segments, refs)));
    item.querySelectorAll('.follow-up-chip').forEach((button) => button.addEventListener('click', () => send(button.textContent)));
    dom.thread.appendChild(item);
    remember('assistant', response.answer, {
      references: refs, card: response.card || {}, intent: response.intent,
      refused: response.refused ?? null, refusal_reason: response.refusal_reason || '',
      presentation: response.refused ? 'refusal' : response.intent === 'greeting' ? 'greeting'
        : restore && !hasSavedEvidence(response) ? 'legacy' : 'answer',
    });
    updateEvidence(refs); scrollBottom(); if (!restore) speak(segments.map((segment) => segment.text).join('. '), response.audio_url);
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
    const question = text.trim(); if (!question || state.isLoading || state.isDeleting || state.isRestoring) return;
    const sessionId = state.sessionId, viewVersion = state.viewVersion;
    stopSpeech();
    if (source === 'text') pauseRecognitionForTextTurn();
    else { clearTimeout(state.listenTimer); state.livePaused = true; }
    state.isLoading = true; dom.input.value = ''; updateComposer(); setLiveStatus('Đang tìm trong tài liệu', 'working'); appendUser(question); appendTyping();
    try {
      const response = await api('/api/ask', { method: 'POST', body: JSON.stringify({ question, session_id: sessionId, use_ai: state.aiEnabled, ref_date: dom.refDate.value || null, with_audio: Boolean(state.ttsEnabled || state.liveEnabled) }) });
      // Update the list even if the user left while the answer was generated.
      void refreshConversations();
      if (viewVersion !== state.viewVersion) return;
      removeTyping(); appendAnswer(response);
    } catch (error) {
      if (viewVersion !== state.viewVersion) return;
      if (error.status === 410 && error.code === 'session_closed' && error.sessionId === sessionId) {
        forgetDeletedConversation(sessionId);
        return;
      }
      if (error.code === 'session_unavailable') {
        resetConversation(crypto.randomUUID());
        setLiveStatus('Không có quyền truy cập hội thoại cũ. Đã mở hội thoại mới; bản lưu cũ không bị xóa.', 'error');
        return;
      }
      removeTyping(); appendError(error.message);
      if (state.liveEnabled) state.livePaused = false;
      scheduleListening();
    }
    finally {
      if (viewVersion === state.viewVersion) {
        state.isLoading = false; updateComposer();
        if (!state.liveEnabled && !state.isSpeaking) setLiveStatus('Sẵn sàng nhập câu hỏi');
      }
    }
  }
  function startListening(fromLive = false) {
    if (!state.recognition || state.recognitionRunning || state.recognitionRequested || state.isLoading || state.isDeleting || state.isRestoring || state.isSpeaking) return;
    if (!fromLive) state.livePaused = false;
    state.recognitionRequested = true;
    try { state.recognition.start(); } catch (_) { state.recognitionRequested = false; if (fromLive) scheduleListening(); }
  }
  function stopLive() {
    state.liveEnabled = false; state.livePaused = false; clearTimeout(state.listenTimer); stopSpeech();
    state.ignoreRecognitionResults = true;
    if (state.recognitionRunning || state.recognitionRequested) state.recognition.abort(); updateFeatureControls(); setLiveStatus('Sẵn sàng nhập câu hỏi');
  }
  function setupVoice() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) { dom.mic.title = 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói'; dom.live.disabled = true; return; }
    const recognition = new Recognition(); recognition.lang = 'vi-VN'; recognition.interimResults = true; recognition.continuous = false;
    recognition.onstart = () => {
      state.recognitionRunning = true;
      if (state.livePaused || state.isLoading || state.isDeleting || state.isRestoring || state.isSpeaking) {
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
      if (state.ignoreRecognitionResults || state.isSpeaking || state.isLoading || state.isDeleting || state.isRestoring) return;
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
    if (state.isDeleting) return;
    resetConversation(crypto.randomUUID());
  }

  function renderConversations() {
    dom.conversationSelect.innerHTML = '';
    const currentSaved = state.conversations.some(item => item.session_id === state.sessionId);
    const addOption = (id, title) => {
      const option = document.createElement('option');
      option.value = id; option.textContent = title;
      dom.conversationSelect.appendChild(option);
    };
    if (!currentSaved) addOption(state.sessionId, 'Hội thoại hiện tại · chưa có lượt được lưu');
    state.conversations.forEach(item => {
      const date = item.updated_at ? new Date(item.updated_at).toLocaleString('vi-VN') : 'Bản lưu cũ';
      addOption(item.session_id, `${item.title} · ${item.turn_count} lượt · ${date}`);
    });
    dom.conversationSelect.value = state.sessionId;
  }

  async function refreshConversations() {
    const version = ++state.listVersion;
    dom.conversationStatus.textContent = 'Đang tải danh sách…';
    try {
      const conversations = await api('/api/conversations');
      if (!Array.isArray(conversations)) throw new Error('Danh sách hội thoại không hợp lệ.');
      if (version !== state.listVersion) return;
      state.conversations = conversations;
      renderConversations();
      dom.conversationStatus.textContent = conversations.length
        ? `${conversations.length} hội thoại đã lưu. Chọn để xem; dùng “Xóa lịch sử” để xóa hội thoại đã chọn.`
        : 'Chưa có hội thoại đã lưu trong trình duyệt này.';
    } catch (error) {
      if (version === state.listVersion) dom.conversationStatus.textContent = `Không thể tải danh sách: ${error.message} Nhấn Làm mới để thử lại.`;
    }
  }

  async function selectConversation(sessionId) {
    if (!sessionId || state.isDeleting) return;
    resetConversation(sessionId);
    const version = state.viewVersion;
    state.isRestoring = true; updateComposer();
    setLiveStatus('Đang tải hội thoại…', 'working');
    try {
      const [history, status] = await Promise.all([
        api(`/api/history?session_id=${encodeURIComponent(sessionId)}`),
        api(`/api/history/status?session_id=${encodeURIComponent(sessionId)}`),
      ]);
      if (version !== state.viewVersion) return;
      if (status.closed === true) { forgetDeletedConversation(sessionId); return; }
      restoreHistory(history);
      state.isRestoring = false; updateComposer();
      if (!history.length) setLiveStatus('Hội thoại chưa có lượt được lưu.');
    } catch (error) {
      if (version !== state.viewVersion) return;
      if (error.code === 'session_unavailable') {
        resetConversation(crypto.randomUUID());
        setLiveStatus('Không có quyền truy cập hội thoại cũ. Đã mở hội thoại mới; bản lưu cũ không bị xóa.', 'error');
        void refreshConversations();
      } else {
        // Do not send into hidden context after a failed restoration.
        setLiveStatus(`Chưa tải được hội thoại: ${error.message} Nhấn Làm mới hoặc chọn Mới.`, 'error');
      }
    }
  }

  function resetConversation(sessionId) {
    stopLive();
    state.viewVersion++;
    state.sessionId = sessionId; state.isLoading = false; state.isRestoring = false; state.isDeleting = false;
    state.turn = 0; state.transcript = [];
    localStorage.setItem('hv_session_id', state.sessionId);
    dom.thread.querySelectorAll('.message:not(.welcome-message)').forEach((item) => item.remove());
    dom.input.value = ''; updateComposer();
    dom.welcome.hidden = false; updateEvidence([]); setLiveStatus('Hội thoại mới đã sẵn sàng');
    renderConversations();
    dom.input.focus();
  }

  function forgetDeletedConversation(sessionId) {
    state.listVersion++; // Invalidate list snapshots fetched before deletion.
    state.conversations = state.conversations.filter(item => item.session_id !== sessionId);
    renderConversations();
    if (sessionId !== state.sessionId) return;
    resetConversation(crypto.randomUUID());
    setLiveStatus('Hội thoại này đã bị xóa. Hội thoại mới đã sẵn sàng.');
  }

  function announceDeletion(sessionId) {
    // No questions, answers or credentials are shared; the nonce also makes a
    // repeated deletion observable. Other tabs keep their own active session.
    try {
      localStorage.setItem('hv_deleted_session', JSON.stringify({ sessionId, nonce: crypto.randomUUID() }));
    } catch (_) { /* Server tombstones and focus checks remain authoritative. */ }
  }

  async function checkConversationStatus() {
    const sessionId = state.sessionId, viewVersion = state.viewVersion;
    try {
      const status = await api(`/api/history/status?session_id=${encodeURIComponent(sessionId)}`);
      if (viewVersion === state.viewVersion && status.session_id === sessionId && status.closed === true) {
        forgetDeletedConversation(sessionId);
      }
    } catch (_) { /* Keep the current view on connection/authentication failure. */ }
  }

  async function deleteHistory() {
    if (state.isLoading || state.isDeleting || state.isRestoring) return;
    const sessionId = state.sessionId, viewVersion = state.viewVersion;
    if (!window.confirm('Xóa vĩnh viễn toàn bộ lịch sử đã lưu của hội thoại hiện tại? Dữ liệu phiên này sẽ không thể khôi phục. Các hội thoại khác không bị xóa.')) return;
    // Allocate before deleting so success always has a fresh destination.
    const nextSessionId = crypto.randomUUID();
    state.isDeleting = true; stopLive(); updateComposer();
    setLiveStatus('Đang xóa lịch sử…', 'working');
    try {
      await api(`/api/history?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
      state.listVersion++;
      state.conversations = state.conversations.filter(item => item.session_id !== sessionId);
      renderConversations();
      dom.conversationStatus.textContent = `${state.conversations.length} hội thoại đã lưu.`;
      announceDeletion(sessionId);
      if (viewVersion !== state.viewVersion) return;
      resetConversation(nextSessionId);
      setLiveStatus('Đã xóa vĩnh viễn lịch sử. Hội thoại mới đã sẵn sàng.');
    } catch (error) {
      if (viewVersion !== state.viewVersion) return;
      // Keep the ID, transcript and sources intact so a failed request is retryable.
      setLiveStatus(`Chưa thể xác nhận xóa lịch sử: ${error.message}`, 'error');
    } finally {
      if (viewVersion === state.viewVersion) { state.isDeleting = false; updateComposer(); }
    }
  }
  function exportAnswer(entry) {
    if (entry.presentation === 'greeting') {
      return ['Trạng thái: Lời chào — không sử dụng căn cứ.', entry.text];
    }
    if (entry.presentation === 'refusal') {
      return [
        'Trạng thái: Từ chối trả lời — chưa đủ căn cứ.', entry.text,
        ...(entry.refusal_reason ? [`Lý do từ chối: ${entry.refusal_reason}`] : []),
      ];
    }
    if (entry.presentation === 'legacy') {
      return ['Trạng thái: Lượt đã lưu — chi tiết căn cứ không có trong bản lưu này.', entry.text];
    }
    const card = entry.card || {}, refs = entry.references || [];
    const segments = card.verdict_segments?.length ? card.verdict_segments : [{ text: entry.text, cites: [] }];
    return [
      ...segments.map((segment) => [
        segment.text, ...(segment.cites || []).map((cite) => `[${cite}]`),
      ].join(' ')),
      ...(hasSavedEvidence(entry) ? [
        `Căn cứ ${card.grounding.label} · ${card.grounding.source_count} nguồn · Mức ${card.grounding.level}/5`,
      ] : []),
      ...(card.notes?.length ? ['Lưu ý:', ...card.notes.map((note) => note.text)] : []),
      ...(refs.length ? [
        'Nguồn của lượt này (số [n] chỉ áp dụng trong lượt):',
        ...refs.flatMap((ref, index) => [
          `Nguồn [${index + 1}]: ${ref.reg_title || ''}`,
          ...(ref.rid ? [`Mã văn bản: ${ref.rid}`] : []),
          ...(ref.version ? [`Phiên bản: ${ref.version}`] : []),
          ...(ref.aid ? [`Điều/mục: ${ref.aid}`] : []),
          ...(ref.art_heading ? [`Tiêu đề: ${ref.art_heading}`] : []),
          ...(ref.clause_ids?.length ? [`Khoản: ${ref.clause_ids.join(', ')}`] : []),
          'Trích dẫn:', ref.excerpt || '', '',
        ]),
      ] : []),
    ];
  }
  function exportConversation() {
    if (!state.transcript.length) { setLiveStatus('Chưa có hội thoại để xuất'); return; }
    let answerTurn = 0;
    const content = [
      'HOCVU AI — LỊCH SỬ HỘI THOẠI',
      `Xuất lúc: ${new Date().toLocaleString('vi-VN')}`,
      '',
      ...state.transcript.flatMap((entry) => [
        entry.role === 'user' ? 'BẠN:' : `HOCVU AI (lượt ${++answerTurn}):`,
        ...(entry.role === 'user' ? [entry.text] : exportAnswer(entry)),
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
      // Old engine rows used empty source IDs for academic refusals. Keep
      // source-backed legacy rows unknown: their citations were never saved.
      const legacyRefusal = turn.intent === 'unsafe'
        || (turn.intent === 'academic_rules' && turn.article_id === '' && turn.rid === '');
      appendAnswer({
        ...turn,
        refused: typeof turn.refused === 'boolean' ? turn.refused : (legacyRefusal ? true : null),
      }, { restore: true });
    });
    setLiveStatus(`Đã khôi phục ${turns.length} lượt gần nhất`);
  }
  function bind() {
    window.addEventListener('storage', (event) => {
      if (event.storageArea !== localStorage || event.key !== 'hv_deleted_session' || !event.newValue) return;
      try {
        const notice = JSON.parse(event.newValue);
        if (typeof notice.sessionId === 'string') forgetDeletedConversation(notice.sessionId);
      } catch (_) { /* Ignore malformed or unrelated storage events. */ }
    });
    // Catch deletion by an API client, or notifications missed while suspended.
    window.addEventListener('focus', checkConversationStatus);
    window.addEventListener('pageshow', checkConversationStatus);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') checkConversationStatus();
    });
    dom.theme.addEventListener('click', () => { state.theme = state.theme === 'light' ? 'dark' : 'light'; document.documentElement.dataset.theme = state.theme; localStorage.setItem('hv_theme', state.theme); });
    dom.ai.addEventListener('click', () => { state.aiEnabled = !state.aiEnabled; localStorage.setItem('hv_ai_enabled', String(state.aiEnabled)); updateFeatureControls(); });
    dom.newConversation.addEventListener('click', startNewConversation);
    dom.conversationSelect.addEventListener('change', () => {
      void selectConversation(dom.conversationSelect.value);
    });
    dom.conversationRefresh.addEventListener('click', () => {
      void refreshConversations();
      if (state.isRestoring) void selectConversation(state.sessionId);
    });
    dom.deleteHistory.addEventListener('click', deleteHistory);
    dom.exportConversation.addEventListener('click', exportConversation);
    dom.live.addEventListener('click', () => {
      if (state.isDeleting || state.isRestoring) return;
      if (state.liveEnabled) { stopLive(); appendSystem('Đã dừng hội thoại Live.'); return; }
      state.liveEnabled = true; state.livePaused = false; state.ttsEnabled = true; updateFeatureControls(); appendSystem('Chế độ Live đã bật. Tôi sẽ lắng nghe, trả lời và tự mở micro cho lượt tiếp theo. Bạn có thể bắt đầu nói.'); speak('Chế độ hội thoại Live đã bật. Bạn có thể bắt đầu nói.');
    });
    dom.input.addEventListener('input', updateComposer);
    dom.input.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } });
    dom.form.addEventListener('submit', (event) => { event.preventDefault(); send(); });
    dom.tts.addEventListener('click', () => { state.ttsEnabled = !state.ttsEnabled; if (!state.ttsEnabled) { if (state.liveEnabled) stopLive(); else stopSpeech(); } updateFeatureControls(); });
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
    // Independent loads prevent a history permission/network error from
    // hiding documents, or a document error from discarding the conversation.
    const restoring = selectConversation(state.sessionId);
    const listing = refreshConversations();
    try {
      const [health, documents, topics] = await Promise.all([
        api('/api/health'), api('/api/documents'), api('/api/suggestions'),
      ]);
      setStatus(true, `Trực tuyến · ${health.documents} văn bản`);
      dom.documents.innerHTML = documents.map((doc) => `<article class="doc-item"><div class="doc-title">${escapeHTML(doc.title)}</div><div class="doc-meta">${escapeHTML(doc.rid)} · Bản ${escapeHTML(doc.version)}</div></article>`).join('');
      renderSuggestionTopics(topics);
    } catch (_) { setStatus(false, 'Mất kết nối'); dom.documents.innerHTML = '<p class="error">Không thể tải cơ sở tri thức.</p>'; }
    await Promise.all([restoring, listing]);
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
