'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { loadUI } = require('./helpers/ui-harness.cjs');

function ready(options = {}) {
  const ui = loadUI({ realSpeech: true, ...options });
  ui.bind();
  ui.setupVoice();
  return ui;
}

test('Live requests the microphone in the click without waiting for a spoken greeting', () => {
  const ui = ready({ voices: [] });
  ui.dom.live.events.click();
  assert.equal(ui.state.liveEnabled, true);
  assert.equal(ui.state.ttsEnabled, true);
  assert.equal(ui.recognitions[0].starts, 1);
  assert.equal(ui.state.recognitionRequested, true);
  assert.equal(ui.state.isSpeaking, false);
  assert.equal(ui.synthesis.spoken.length, 0);
  ui.recognitions[0].onstart();
  assert.equal(ui.state.recognitionRunning, true);
  assert.match(ui.dom.liveStatus.textContent, /Đang nghe/);
  ui.dom.live.events.click();
  assert.equal(ui.state.liveEnabled, false);
  assert.equal(ui.recognitions[0].aborts, 1);
});

test('the mic button interrupts playback and starts listening immediately', () => {
  const ui = ready();
  ui.state.ttsEnabled = true;
  ui.speak('Câu trả lời', '/reply.mp3');
  const audio = ui.state.audio;
  ui.dom.mic.events.click();
  assert.equal(audio.pauses, 1);
  assert.equal(ui.state.isSpeaking, false);
  assert.equal(ui.recognitions[0].starts, 1);
});

test('an iframe that denies microphone access gives a same-page new-tab link', () => {
  const ui = ready({ microphoneAllowed: false });
  ui.dom.live.events.click();
  assert.equal(ui.recognitions[0].starts, 0);
  assert.equal(ui.state.liveEnabled, false);
  assert.equal(ui.dom.voiceHelp.hidden, false);
  assert.match(ui.dom.voiceHelpText.textContent, /Khung xem trước đang chặn micro/);
  assert.equal(ui.dom.voiceOpen.href, 'https://hocvu.example.test/');
});

test('unsupported recognition remains actionable instead of silently disabling Live', () => {
  const ui = ready({ noRecognition: true });
  ui.updateComposer();
  assert.equal(ui.dom.live.disabled, false);
  ui.dom.live.events.click();
  assert.equal(ui.state.liveEnabled, false);
  assert.match(ui.dom.voiceHelpText.textContent, /Chrome hoặc Edge/);
  ui.dom.mic.events.click();
  assert.match(ui.dom.voiceHelpText.textContent, /chưa hỗ trợ/);
});

test('an insecure page explains the HTTPS requirement', () => {
  const ui = ready({ secure: false });
  ui.dom.mic.events.click();
  assert.equal(ui.recognitions[0].starts, 0);
  assert.match(ui.dom.voiceHelpText.textContent, /HTTPS/);
});

for (const [error, expected] of [
  ['not-allowed', /cho phép micro/],
  ['service-not-allowed', /dịch vụ nhận dạng/],
  ['audio-capture', /thiết bị/],
  ['network', /Internet/],
  ['language-not-supported', /tiếng Việt/],
]) {
  test(`recognition ${error} stops Live and explains the actual failure`, () => {
    const ui = ready();
    ui.dom.live.events.click();
    const recognition = ui.recognitions[0];
    recognition.onstart();
    recognition.onerror({ error });
    recognition.onend();
    assert.equal(ui.state.liveEnabled, false);
    assert.equal(ui.state.isSpeaking, false);
    assert.equal(ui.timers.size, 0, 'must not retry forever after a recognition error');
    assert.equal(ui.dom.voiceHelp.hidden, false);
    assert.match(ui.dom.voiceHelpText.textContent, expected);
  });
}

test('synchronous microphone errors are reported without an infinite retry', () => {
  const ui = ready({ startError: new Error('Permission denied') });
  ui.dom.live.events.click();
  assert.equal(ui.state.recognitionRequested, false);
  assert.equal(ui.state.liveEnabled, false);
  assert.equal(ui.timers.size, 0);
  assert.match(ui.dom.voiceHelpText.textContent, /Chưa mở được micro/);
});

test('a recognized question is sent with audio enabled and listening resumes after playback', async () => {
  const ui = ready({ request: async url => url === '/api/ask'
    ? { answer: 'Chào bạn', intent: 'greeting', references: [], audio_url: '/reply.mp3' }
    : [] });
  ui.dom.live.events.click();
  const recognition = ui.recognitions[0];
  recognition.onstart();
  const results = [[{ transcript: 'Xin chào' }]];
  results[0].isFinal = true;
  recognition.onresult({ resultIndex: 0, results });
  recognition.onend();
  for (let i = 0; i < 20; i++) await Promise.resolve();
  assert.equal(JSON.parse(ui.calls.find(([url]) => url === '/api/ask')[1].body).with_audio, true);
  assert.equal(ui.state.audio?.src, '/reply.mp3');
  assert.equal(ui.state.livePaused, true);
  assert.equal(recognition.starts, 1, 'never capture the spoken answer');
  ui.state.audio.onended();
  assert.equal(ui.state.livePaused, false);
  assert.ok(ui.state.listenTimer);
});

test('retrying after a denial clears the help and starts a new recognition attempt', () => {
  const ui = ready();
  ui.dom.live.events.click();
  const recognition = ui.recognitions[0];
  recognition.onerror({ error: 'not-allowed' });
  recognition.onend();
  ui.dom.live.events.click();
  assert.equal(recognition.starts, 2);
  assert.equal(ui.dom.voiceHelp.hidden, true);
  assert.equal(ui.state.liveEnabled, true);
});

test('cancelling Live before recognition starts rejects a late start event', () => {
  const ui = ready();
  ui.dom.live.events.click();
  ui.dom.live.events.click();
  const recognition = ui.recognitions[0];
  recognition.onstart();
  recognition.onend();
  assert.equal(ui.state.ignoreRecognitionResults, true);
  assert.equal(ui.state.liveEnabled, false);
  assert.equal(ui.state.recognitionRunning, false);
  assert.equal(ui.timers.size, 0);
});

test('the mic button can cancel a pending microphone request without Live reopening it', () => {
  const ui = ready();
  ui.dom.live.events.click();
  ui.dom.mic.events.click();
  const recognition = ui.recognitions[0];
  recognition.onend();
  assert.equal(recognition.aborts, 1);
  assert.equal(ui.state.livePaused, true);
  assert.equal(ui.timers.size, 0);
  assert.match(ui.dom.liveStatus.textContent, /Đã dừng micro/);
});
