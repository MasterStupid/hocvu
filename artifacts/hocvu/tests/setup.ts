import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// No test may contact the running application or any external service.
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => {
    throw new Error('Unexpected HTTP request: install an explicit test handler');
  }));
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
