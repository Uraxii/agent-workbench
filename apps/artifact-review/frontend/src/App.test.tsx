import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

const artifact = {
  project: 'demo',
  subdir: 'report',
  artifact_id: 'demo/report',
  last_pushed: 1785153600,
  last_pushed_iso: '2026-07-27T12:00:00Z',
  entry_count: 1,
};

const jsonResponse = (payload: unknown, status = 200): Response =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const threadListResponse = {
  artifact_id: artifact.artifact_id,
  sub_path: '',
  threads: [],
};

const sandboxTokenCount = (frame: HTMLIFrameElement): number => {
  if (frame.sandbox !== undefined) {
    return frame.sandbox.length;
  }
  return frame.getAttribute('sandbox')?.trim().split(/\s+/).filter(Boolean).length ?? 0;
};

describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the artifact index list', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      if (input === '/_/api/artifacts') {
        return Promise.resolve(jsonResponse({ artifacts: [artifact] }));
      }
      return Promise.resolve(jsonResponse(threadListResponse));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(await screen.findByText('demo/report', { selector: '.artifact-title' })).not.toBeNull();
    expect(screen.getByText('demo/report', { selector: '.artifact-meta' })).not.toBeNull();
    expect(screen.getByText('1 entry')).not.toBeNull();
  });

  it('renders an empty artifact index state', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ artifacts: [] })));

    render(<App />);

    expect(await screen.findByText(/No staged artifacts are available/)).not.toBeNull();
    expect(screen.getByText(/artifact publish verb/)).not.toBeNull();
  });

  it('renders an artifact index error naming the endpoint', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(new Error('down')));

    render(<App />);

    expect(await screen.findByText('/_/api/artifacts failed: Network request failed.')).not.toBeNull();
  });

  it('renders artifact iframe with an empty sandbox attribute', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      if (input === '/_/api/artifacts') {
        return Promise.resolve(jsonResponse({ artifacts: [artifact] }));
      }
      return Promise.resolve(jsonResponse(threadListResponse));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    const frame = (await screen.findByTitle('Artifact demo/report')) as HTMLIFrameElement;
    expect(frame.hasAttribute('sandbox')).toBe(true);
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(frame.getAttribute('sandbox')?.trim()).toBe('');
    expect(sandboxTokenCount(frame)).toBe(0);
  });
});
