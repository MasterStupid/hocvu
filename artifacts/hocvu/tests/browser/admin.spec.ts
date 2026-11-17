import { test, expect, login, dropFiles, pdf, reply } from './admin-fixture';

test('file chooser accepts multiple files and resets so the same file can be chosen again', async ({ page }) => {
  await login(page);
  const input = page.locator('input[type=file]');
  await expect(input).toHaveAttribute('multiple', '');
  await expect(input).toHaveAttribute('accept', '.pdf,.docx,.png,.jpg,.jpeg,.webp');
  const chooser = page.waitForEvent('filechooser');
  await page.getByTestId('button-choose-files').click();
  await (await chooser).setFiles([pdf, { ...pdf, name: 'second.docx' }]);
  await expect(page.getByTestId('input-order-1')).toHaveValue('2');
  await expect(input).toHaveValue('');
  await page.getByTestId('button-remove-queued-0').click();
  await input.setInputFiles(pdf);
  await expect(page.getByText('synthetic.pdf', { exact: true })).toHaveCount(1);
  await page.getByTestId('button-clear-queue').click();
  await expect(page.getByTestId('button-upload')).toHaveCount(0);
  await input.setInputFiles(pdf);
  await expect(page.getByText('synthetic.pdf', { exact: true })).toBeVisible();
});

test('native drag-and-drop validates file types and the 20-file limit', async ({ page }) => {
  await login(page);
  await dropFiles(page, ['dropped.pdf', 'unsafe.exe']);
  await expect(page.getByText('dropped.pdf', { exact: true })).toBeVisible();
  await expect(page.getByText(/unsafe.exe: chỉ nhận/)).toBeVisible();
  await expect(page.getByTestId('input-order-1')).toHaveCount(0);
  await dropFiles(page, Array.from({ length: 20 }, (_, i) => `extra-${i}.pdf`));
  await expect(page.getByTestId('input-order-19')).toBeVisible();
  await expect(page.getByTestId('input-order-20')).toHaveCount(0);
  await expect(page.getByText(/Hàng đợi tối đa 20 tệp/)).toBeVisible();
});

test('multipart upload contains native file bytes, ISO date and per-file metadata; locks the queue in flight', async ({ page, api }) => {
  const release = api.hold('POST', '/api/documents/upload-batch', { items: [] });
  await login(page);
  await page.locator('input[type=file]').setInputFiles(pdf);
  await page.getByTestId('input-date-0').fill('2028-02-29');
  await page.getByTestId('input-decision-0').fill('123/QĐ-test');
  await page.getByTestId('input-article-0').fill('Điều 2');
  await page.getByTestId('switch-ocr-0').click();
  await page.getByTestId('button-upload').click();
  await expect.poll(() => api.count('POST', '/api/documents/upload-batch')).toBe(1);
  await expect(page.locator('input[type=file]')).toBeDisabled();
  for (const id of ['button-upload', 'button-choose-files', 'button-clear-queue', 'button-remove-queued-0',
    'input-order-0', 'input-decision-0', 'input-article-0', 'input-date-0', 'switch-ocr-0',
    'switch-default-ocr', 'button-sign-out', 'button-reindex', 'button-backup', 'button-edit-date-a', 'button-delete-a', 'checkbox-select-all']) {
    await expect(page.getByTestId(id)).toBeDisabled();
  }
  await dropFiles(page, ['must-not-appear.pdf']);
  await expect(page.getByText('must-not-appear.pdf', { exact: true })).toHaveCount(0);
  const body = api.calls.find((c) => c.path.endsWith('/upload-batch'))!.body!;
  expect(body).toContain('name="files"; filename="synthetic.pdf"');
  expect(body).toContain('%PDF-1.4');
  expect(body).toContain('"document_date":"2028-02-29"');
  expect(body).toContain('"decision_number":"123/QĐ-test"');
  expect(body).toContain('"article_clause":"Điều 2"');
  expect(body).toContain('"ocr":true');
  release();
  await expect(page.getByTestId('button-upload')).toHaveCount(0);
  await expect(page.getByText(/Đã tải lên và lập chỉ mục/)).toBeVisible();
  expect(api.count('POST', '/api/documents/upload-batch')).toBe(1);
});

test('failed upload keeps native file and date for an explicit retry', async ({ page, api }) => {
  api.handle('POST', '/api/documents/upload-batch', (route) => reply(route, {}, 503));
  await login(page);
  await page.locator('input[type=file]').setInputFiles(pdf);
  await page.getByTestId('input-date-0').fill('2028-02-29');
  await page.getByTestId('button-upload').click();
  await expect(page.getByText(/Hàng đợi được giữ lại/)).toBeVisible();
  await expect(page.getByTestId('input-date-0')).toHaveValue('2028-02-29');
  await expect(page.getByText('synthetic.pdf', { exact: true })).toBeVisible();
  await expect(page.getByTestId('button-upload')).toBeEnabled();
  expect(api.count('POST', '/api/documents/upload-batch')).toBe(1);
  api.handle('POST', '/api/documents/upload-batch', (route) => reply(route, { items: [] }));
  await page.getByTestId('button-upload').click();
  await expect(page.getByTestId('button-upload')).toHaveCount(0);
  expect(api.count('POST', '/api/documents/upload-batch')).toBe(2);
  const attempts = api.calls.filter((c) => c.path.endsWith('/upload-batch'));
  for (const attempt of attempts) {
    expect(attempt.body).toContain('%PDF-1.4');
    expect(attempt.body).toContain('"document_date":"2028-02-29"');
  }
});

test('date dialog enforces native required validation, traps keyboard focus and returns it on Escape', async ({ page, api }) => {
  await login(page);
  const trigger = page.getByTestId('button-edit-date-a');
  await trigger.click();
  const dialog = page.getByRole('dialog');
  const date = page.getByTestId('input-edit-date');
  await expect(date).toBeFocused();
  await expect(date).toHaveValue('2026-01-01');
  await date.fill('');
  await page.getByTestId('button-date-save').click();
  expect(await date.evaluate((el: HTMLInputElement) => el.validity.valueMissing)).toBe(true);
  expect(api.count('PATCH', '/api/documents/a/date')).toBe(0);
  await date.fill('2028-02-29');
  await dialog.getByRole('button', { name: 'Close', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(date).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.getByTestId('button-edit-date-b').click();
  await expect(date).toHaveValue('2026-02-01');
});

test('date save locks dismissal and keyboard resubmission until response; reopening reads updated date', async ({ page, api }) => {
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => { finish = resolve; });
  api.handle('PATCH', '/api/documents/a/date', async (route) => {
    await gate;
    const value = route.request().postDataJSON().document_date;
    api.rows = api.rows.map((d) => d.id === 'a' ? { ...d, document_date: value } : d);
    await reply(route, api.rows.find((d) => d.id === 'a'));
  });
  await login(page);
  await page.getByTestId('button-edit-date-a').click();
  await page.getByTestId('input-edit-date').fill('2028-02-29');
  await page.getByTestId('button-date-save').focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => api.count('PATCH', '/api/documents/a/date')).toBe(1);
  await expect(page.getByTestId('button-date-save')).toBeDisabled();
  await expect(page.getByTestId('button-date-cancel')).toBeDisabled();
  await expect(page.getByTestId('input-edit-date')).toBeDisabled();
  await page.keyboard.press('Enter');
  await page.keyboard.press('Escape');
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.mouse.click(5, 5);
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(api.count('PATCH', '/api/documents/a/date')).toBe(1);
  finish();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByTestId('button-edit-date-a').click();
  await expect(page.getByTestId('input-edit-date')).toHaveValue('2028-02-29');
});

test('delete confirmation initially focuses Cancel, traps Tab, cancels by keyboard and restores trigger focus', async ({ page, api }) => {
  await login(page);
  const trigger = page.getByTestId('button-delete-a');
  await trigger.click();
  await expect(page.getByTestId('button-confirm-cancel')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.getByTestId('button-confirm-ok')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByTestId('button-confirm-cancel')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(api.count('DELETE', '/api/documents/a')).toBe(0);
  await trigger.click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

for (const action of ['delete', 'batch-delete', 'backup'] as const) {
  test(`${action} confirmation cannot dismiss or submit again while pending`, async ({ page, api }) => {
    const method = action === 'delete' ? 'DELETE' : 'POST';
    const path = action === 'delete' ? '/api/documents/a' : action === 'batch-delete'
      ? '/api/documents/delete-batch' : '/api/admin/storage/backup';
    const release = api.hold(method, path, action === 'delete'
      ? { status: 'ok' } : action === 'batch-delete'
        ? { deleted: ['a', 'b'] } : { filename: 'synthetic.zip', persistent_copy: false });
    await login(page);
    if (action === 'batch-delete') await page.getByTestId('checkbox-select-all').check();
    await page.getByTestId(action === 'delete' ? 'button-delete-a'
      : action === 'batch-delete' ? 'button-delete-selected' : 'button-backup').click();
    expect(api.count(method, path)).toBe(0);
    await page.getByTestId('button-confirm-ok').click();
    await expect.poll(() => api.count(method, path)).toBe(1);
    await expect(page.getByTestId('button-confirm-ok')).toBeDisabled();
    await expect(page.getByTestId('button-confirm-cancel')).toBeDisabled();
    await expect(page.getByTestId('button-sign-out')).toBeDisabled();
    await page.keyboard.press('Enter');
    await page.keyboard.press('Escape');
    await page.mouse.click(5, 5);
    await expect(page.getByRole('alertdialog')).toBeVisible();
    expect(api.count(method, path)).toBe(1);
    release();
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(page.getByTestId('button-sign-out')).toBeEnabled();
  });
}

test('preview dialog traps keyboard focus and restores it without leaking text after logout', async ({ page, api }) => {
  api.handle('GET', '/api/documents/a/text', (route) => reply(route, {
    title: 'Quy chế thử A', text: 'Nội dung tổng hợp riêng tư', chunk_count: 1,
  }));
  await login(page);
  const trigger = page.getByTestId('button-preview-a');
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Nội dung tổng hợp riêng tư')).toBeVisible();
  const close = dialog.getByRole('button', { name: 'Close', exact: true });
  await expect(close).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(close).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.getByTestId('button-sign-out').click();
  await expect(page.getByTestId('input-admin-password')).toBeVisible();
  await expect(page.getByText('Nội dung tổng hợp riêng tư')).toHaveCount(0);
});
