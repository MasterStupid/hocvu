import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Welcome } from '@/components/chat/welcome';

vi.mock('@/hooks/use-public', () => ({
  useSuggestions: () => ({ isSuccess: true, data: [] }),
}));

describe('Welcome quick actions', () => {
  it('focuses the question input without submitting or starting the microphone', () => {
    const onAsk = vi.fn();
    const onVoice = vi.fn();
    render(<><Welcome onAsk={onAsk} onVoice={onVoice} disabled={false} micSupported={false} />
      <textarea id="composer" aria-label="Câu hỏi" defaultValue="Bản nháp" /></>);
    fireEvent.click(screen.getByTestId('button-type-cta'));
    expect(screen.getByLabelText('Câu hỏi')).toHaveFocus();
    expect(screen.getByLabelText('Câu hỏi')).toHaveValue('Bản nháp');
    expect(onAsk).not.toHaveBeenCalled();
    expect(onVoice).not.toHaveBeenCalled();
  });

  it('toggles the compact technical explanation with accessible state', () => {
    render(<Welcome onAsk={vi.fn()} onVoice={vi.fn()} disabled={false} micSupported />);
    const button = screen.getByRole('button', { name: 'Cách một câu hỏi được xử lý' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById('voice-flow')).not.toHaveClass('hidden');
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });
});
