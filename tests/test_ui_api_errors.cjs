const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { errorMessage, readResponse } = require('../ui/api-errors.js');

const fallback = 'Không thể hoàn tất yêu cầu.';
const response = (payload, status = 400) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
});

test('FastAPI business errors keep their Vietnamese detail', async () => {
  for (const detail of [
    'Tài liệu này đã tồn tại.',
    'PDF được mã hóa nên chưa thể lập chỉ mục.',
    'Hãy bật OCR để đọc tệp ảnh.',
    'Văn bản trích xuất chưa đủ 20 ký tự.',
    'Không tìm thấy Tesseract OCR trên máy chủ.',
    'Kích thước tệp vượt quá 25 MB.',
  ]) {
    assert.equal(errorMessage({ detail }, fallback), detail);
    await assert.rejects(readResponse(response({ detail }), fallback), { message: detail });
  }
});

test('legacy middleware errors are still supported', async () => {
  const message = 'Too many requests; try again in a minute.';
  await assert.rejects(
    readResponse(response({ error: message }, 429), fallback), { message },
  );
});

test('FastAPI validation arrays show messages, not object strings or raw input', async () => {
  const data = { detail: [
    { type: 'string_too_long', loc: ['body', 'question'], msg: 'String should have at most 4000 characters',
      input: 'private input', ctx: { max_length: 4000 } },
    { type: 'missing', loc: ['body', 'file'], msg: 'Field required' },
  ] };
  const message = errorMessage(data, fallback);
  assert.equal(message, 'Câu hỏi không được vượt quá 4000 ký tự. Tệp tải lên là bắt buộc.');
  assert.ok(!message.includes('private input'));
  assert.ok(!message.includes('[object Object]'));
  await assert.rejects(readResponse(response(data, 422), fallback), { message });
});

test('other validation messages and string-list detail are preserved', () => {
  assert.equal(errorMessage({ detail: [
    { loc: ['query', 'date'], msg: 'Ngày không hợp lệ.' },
    { msg: 'Ngày không hợp lệ.' }, null, {}, 'Thiếu nội dung.',
  ] }, fallback), 'Ngày không hợp lệ. Thiếu nội dung.');
  assert.equal(errorMessage({ detail: [{ type: 'json_invalid', msg: 'JSON decode error' }] }, fallback),
    'Dữ liệu gửi lên không phải JSON hợp lệ.');
});

test('malformed error shapes use the supplied fallback', () => {
  for (const data of [null, {}, [], 'error', { detail: {} }, { detail: [null, {}] },
    { error: { stack: 'internal stack' } }, { error: ' ', detail: '' }]) {
    assert.equal(errorMessage(data, fallback), fallback);
  }
});

test('empty legacy error does not hide a valid detail', () => {
  assert.equal(errorMessage({ error: '', detail: 'PDF được mã hóa.' }, fallback), 'PDF được mã hóa.');
});

test('non-JSON server errors use each callers fallback', async () => {
  for (const message of [fallback, 'Không thể kết nối máy chủ.']) {
    await assert.rejects(readResponse({
      ok: false, json: async () => { throw new SyntaxError('Unexpected token <'); },
    }, message), { message });
  }
});

test('successful objects and arrays are unchanged and parsed only once', async () => {
  for (const data of [{ id: 'uploaded', chunks: 4 }, [], [{ id: 'document' }]]) {
    let calls = 0;
    const result = await readResponse({
      ok: true, json: async () => { calls++; return data; },
    }, fallback);
    assert.strictEqual(result, data);
    assert.equal(calls, 1);
  }
});

test('malformed successful JSON fails explicitly rather than silently returning an empty object', async () => {
  await assert.rejects(readResponse({
    ok: true, json: async () => { throw new SyntaxError('bad JSON'); },
  }, fallback), { message: 'Máy chủ trả về dữ liệu không hợp lệ.' });
});

test('browser script exports the same shared API', () => {
  const source = fs.readFileSync(path.join(__dirname, '../ui/api-errors.js'), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source, context);
  assert.equal(context.HocVuAPI.errorMessage({ detail: 'Lỗi tiếng Việt.' }, fallback), 'Lỗi tiếng Việt.');
});

test('both pages load the shared parser before their API client', () => {
  for (const [html, client] of [['index.html', 'main.js'], ['documents.html', 'documents.js']]) {
    const page = fs.readFileSync(path.join(__dirname, '../ui', html), 'utf8');
    assert.ok(page.indexOf('src="api-errors.js?') >= 0);
    assert.ok(page.indexOf('src="api-errors.js?') < page.indexOf(`src="${client}?`));
    const source = fs.readFileSync(path.join(__dirname, '../ui', client), 'utf8');
    assert.ok(source.includes('HocVuAPI.readResponse(response,'));
  }
});
