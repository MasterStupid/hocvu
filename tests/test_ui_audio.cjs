'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { loadUI } = require('./helpers/ui-harness.cjs');
function enabled(options = {}) {
  const ui = loadUI({ realSpeech: true, ...options });
  ui.state.ttsEnabled = true;
  return ui;
}

test('stopping Live pauses and releases MP3 playback, not only browser speech', () => {
  const ui = enabled();
  ui.state.liveEnabled = true;
  ui.speak('Xin chào', '/first.mp3');
  const audio = ui.state.audio;
  ui.stopLive();
  assert.equal(audio.pauses, 1);
  assert.equal(audio.src, '');
  assert.equal(audio.loads, 1);
  assert.equal(ui.state.audio, null);
  assert.equal(ui.state.isSpeaking, false);
  assert.equal(ui.state.liveEnabled, false);
});

test('a new MP3 stops the old one and ignores its late completion', () => {
  const ui = enabled();
  ui.speak('Câu một', '/first.mp3');
  const old = ui.state.audio, lateEnd = old.onended;
  ui.speak('Câu hai', '/second.mp3');
  const current = ui.state.audio;
  assert.equal(old.pauses, 1);
  assert.notEqual(old, current);
  lateEnd();
  assert.equal(ui.state.audio, current);
  assert.equal(ui.state.isSpeaking, true);
  current.onended();
  assert.equal(ui.state.audio, null);
  assert.equal(ui.state.isSpeaking, false);
});

test('switching from MP3 to browser synthesis stops the MP3 first', () => {
  const ui = enabled();
  ui.speak('Câu một', '/first.mp3');
  const old = ui.state.audio;
  ui.speak('Câu hai');
  assert.equal(old.pauses, 1);
  assert.equal(ui.state.audio, null);
  assert.equal(ui.synthesis.spoken.length, 1);
  assert.equal(ui.synthesis.spoken[0].text, 'Câu hai');
});

test('the TTS toggle stops playback even outside Live mode', () => {
  const ui = enabled();
  ui.bind();
  ui.speak('Xin chào', '/first.mp3');
  const old = ui.state.audio;
  ui.dom.tts.events.click();
  assert.equal(old.pauses, 1);
  assert.equal(ui.state.ttsEnabled, false);
  assert.equal(ui.state.isSpeaking, false);
});

test('sending a new question stops old playback before the response arrives', async () => {
  let finish;
  const ui = enabled({ fetch: () => new Promise(resolve => { finish = resolve; }) });
  ui.speak('Câu một', '/first.mp3');
  const old = ui.state.audio;
  const pending = ui.send('Xin chào');
  assert.equal(old.pauses, 1);
  assert.equal(ui.state.audio, null);
  finish({ ok: true, json: async () => ({ answer: 'Chào bạn!', intent: 'greeting', references: [] }) });
  await pending;
});

test('late play rejection and error cannot restart speech after stop', async () => {
  const ui = enabled({ deferPlay: true });
  ui.speak('Câu một', '/first.mp3');
  const old = ui.state.audio, lateError = old.onerror;
  ui.stopLive();
  lateError();
  old.reject(new Error('Aborted playback'));
  await Promise.resolve();
  assert.equal(ui.synthesis.spoken.length, 0);
  assert.equal(ui.state.isSpeaking, false);
});

test('MP3 error and rejected play promise trigger browser fallback only once', async () => {
  const ui = enabled({ deferPlay: true });
  ui.speak('Câu một', '/first.mp3');
  const old = ui.state.audio;
  old.onerror();
  old.reject(new Error('Playback failed'));
  await Promise.resolve();
  assert.equal(ui.synthesis.spoken.length, 1);
  assert.equal(ui.state.audio, null);
  assert.equal(old.pauses, 1);
});

test('a stale voice retry neither restarts speech nor clears the new retry handle', () => {
  const ui = enabled({ voices: [] });
  ui.speak('Câu một');
  const oldRetry = ui.timers.get(ui.state.speechTimer).callback;
  ui.speak('Câu hai');
  const currentTimer = ui.state.speechTimer;
  oldRetry();
  assert.equal(ui.state.speechTimer, currentTimer);
  ui.stopLive();
  assert.equal(ui.timers.size, 0);
  oldRetry();
  assert.equal(ui.synthesis.spoken.length, 0);
});

test('missing voices get one retry, then use the browser default without retrying forever', () => {
  const ui = enabled({ voices: [] });
  ui.speak('Xin chào');
  ui.runTimers();
  assert.equal(ui.synthesis.spoken.length, 1);
  ui.synthesis.spoken[0].onstart();
  assert.equal(ui.timers.size, 0);
});

test('opening a new conversation stops audio and pending speech', () => {
  const ui = enabled();
  ui.speak('Câu một', '/first.mp3');
  const old = ui.state.audio;
  ui.startNewConversation();
  assert.equal(old.pauses, 1);
  assert.equal(ui.state.audio, null);
  assert.equal(ui.state.isSpeaking, false);
});

test('blocked browser speech is reported and cannot leave Live stuck speaking', () => {
  const ui = enabled();
  ui.state.liveEnabled = true;
  ui.speak('Xin chào');
  const utterance = ui.synthesis.spoken[0];
  ui.runTimers();
  assert.equal(ui.state.isSpeaking, false);
  assert.equal(ui.dom.voiceHelp.hidden, false);
  assert.match(ui.dom.voiceHelpText.textContent, /chưa phát được giọng đọc/);
  const timer = ui.state.listenTimer;
  utterance.onerror();
  utterance.onend();
  assert.equal(ui.state.listenTimer, timer, 'late callbacks must not restart the listening timer');
});

test('browser speech that starts is not timed out while a long answer is playing', () => {
  const ui = enabled();
  ui.speak('Một câu trả lời dài');
  ui.synthesis.spoken[0].onstart();
  assert.equal(ui.timers.size, 0);
  ui.runTimers();
  assert.equal(ui.state.isSpeaking, true);
  ui.synthesis.spoken[0].onend();
  assert.equal(ui.state.isSpeaking, false);
});

test('a browser synthesis exception is visible rather than leaving speech active', () => {
  const ui = enabled({ speakError: new Error('Speech blocked') });
  ui.speak('Xin chào');
  assert.equal(ui.state.isSpeaking, false);
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.dom.voiceHelp.hidden, false);
});
