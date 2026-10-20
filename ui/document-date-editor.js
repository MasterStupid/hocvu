(function (root) {
  'use strict';

  function createDateEditor({ dialog, form, input, name, status, cancel, save, request, onSaved }) {
    let current = null;
    let saving = false;
    const message = (text, error = false) => {
      status.textContent = text;
      status.className = `upload-status${error ? ' error' : ''}`;
    };
    const close = () => { if (!saving) dialog.close(); };
    cancel.addEventListener('click', close);
    dialog.addEventListener('cancel', (event) => { if (saving) event.preventDefault(); });
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!current || saving) return;
      if (!input.value || !input.checkValidity()) {
        message('Hãy chọn ngày áp dụng hợp lệ.', true);
        input.reportValidity();
        return;
      }
      saving = true;
      input.disabled = cancel.disabled = save.disabled = true;
      message('Đang lưu ngày và cập nhật chỉ mục...');
      try {
        const item = await request(`/api/documents/${encodeURIComponent(current.id)}/date`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ document_date: input.value }),
        });
        try {
          await onSaved(item);
        } catch {
          message('Ngày đã được lưu, nhưng chưa tải lại được danh sách. Hãy tải lại trang.', true);
          return;
        }
        dialog.close();
      } catch (error) {
        message(error.message || 'Không thể lưu ngày áp dụng. Hãy thử lại.', true);
      } finally {
        saving = false;
        input.disabled = cancel.disabled = save.disabled = false;
      }
    });
    return {
      open(item) {
        if (saving) return;
        current = item;
        name.textContent = item.title;
        input.value = item.document_date || '';
        message('Chỉ thay đổi ngày áp dụng; mã tài liệu và tệp gốc được giữ nguyên.');
        dialog.showModal();
        input.focus();
      },
    };
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { createDateEditor };
  else root.HocVuDocumentDates = Object.freeze({ createDateEditor });
})(globalThis);
