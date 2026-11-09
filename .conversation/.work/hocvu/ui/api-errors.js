(function (root) {
  'use strict';

  const nonEmptyString = (value) => typeof value === 'string' && value.trim() ? value.trim() : '';

  function validationMessage(item) {
    if (typeof item === 'string') return nonEmptyString(item);
    if (!item || typeof item !== 'object') return '';
    const message = nonEmptyString(item.msg);
    if (!message) return '';
    const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : '';
    const label = {
      question: 'Câu hỏi', file: 'Tệp tải lên', ref_date: 'Ngày tra cứu',
      text: 'Nội dung', session_id: 'Mã phiên hội thoại',
    }[field] || 'Dữ liệu';
    if (item.type === 'string_too_long' && Number.isFinite(item.ctx?.max_length)) {
      return `${label} không được vượt quá ${item.ctx.max_length} ký tự.`;
    }
    if (item.type === 'missing') return `${label} là bắt buộc.`;
    if (item.type === 'json_invalid') return 'Dữ liệu gửi lên không phải JSON hợp lệ.';
    // Only the human-readable message is shown, never input/ctx/trace objects.
    return message;
  }

  function errorMessage(data, fallback) {
    if (!data || typeof data !== 'object') return fallback;
    const legacy = nonEmptyString(data.error);
    if (legacy) return legacy;
    const detail = nonEmptyString(data.detail);
    if (detail) return detail;
    if (Array.isArray(data.detail)) {
      const messages = [...new Set(data.detail.map(validationMessage).filter(Boolean))];
      if (messages.length) return messages.join(' ');
    }
    return fallback;
  }

  async function readResponse(response, fallback) {
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(response.ok ? 'Máy chủ trả về dữ liệu không hợp lệ.' : fallback);
    }
    if (!response.ok) {
      const error = new Error(errorMessage(data, fallback));
      error.status = response.status;
      error.code = typeof data?.code === 'string' ? data.code : '';
      error.sessionId = typeof data?.session_id === 'string' ? data.session_id : '';
      throw error;
    }
    return data;
  }

  const api = Object.freeze({ errorMessage, readResponse });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HocVuAPI = api;
})(globalThis);
