import { afterEach, describe, expect, it, vi } from 'vitest';
import { getThreadsByArtifact } from './artifactReviewClient';

const threadPayload = {
  id: 123,
  sub_path: 'relative/path.png',
  anchor_kind: 'page',
  anchor: null,
  resolved: false,
  author: 'name',
  created_at: 1720000000,
  created_at_iso: '2024-07-03T09:46:40Z',
  bd_ticket: null,
  replies: [
    {
      id: 456,
      body: 'comment text',
      author: 'name',
      created_at: 1720000001,
      created_at_iso: '2024-07-03T09:46:41Z',
      uploads: [],
    },
  ],
};

const jsonResponse = (payload: unknown, status = 200): Response =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('artifactReviewClient', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns ready threads for an artifact query', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        jsonResponse({
          artifact_id: 'demo/image-set',
          sub_path: 'relative/path.png',
          threads: [threadPayload],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = await getThreadsByArtifact({ artifact: 'demo/image-set', subPath: 'relative/path.png' });

    expect(fetchMock).toHaveBeenCalledWith('/_/api/threads?artifact=demo%2Fimage-set&sub_path=relative%2Fpath.png');
    expect(result.status).toBe('ready');
    if (result.status === 'ready') {
      expect(result.data.threads).toHaveLength(1);
      expect(result.data.threads[0]?.id).toBe(123);
    }
  });

  it('returns empty for a successful thread list with no rows', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        artifact_id: 'demo/image-set',
        sub_path: '',
        threads: [],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await getThreadsByArtifact({ artifact: 'demo/image-set' });

    expect(result).toEqual({
      status: 'empty',
      data: { artifact_id: 'demo/image-set', sub_path: '', threads: [] },
    });
  });

  it('returns a safe error when response validation fails', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        artifact_id: 'demo/image-set',
        sub_path: '',
        threads: [{ ...threadPayload, id: 'not-a-number' }],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await getThreadsByArtifact({ artifact: 'demo/image-set' });

    expect(result).toEqual({
      status: 'error',
      message: 'Response shape did not match the API contract.',
    });
    if (result.status === 'error') {
      expect(result.message).not.toContain('ZodError');
      expect(result.message).not.toContain('stack');
    }
  });
});
