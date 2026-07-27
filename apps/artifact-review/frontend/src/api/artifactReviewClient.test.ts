import { afterEach, describe, expect, it, vi } from 'vitest';
import { createThread, getArtifacts, getThreadsByArtifact } from './artifactReviewClient';
import {
  ArtifactListResponseSchema,
  CreateReplyResponseSchema,
  CreateThreadResponseSchema,
  ResolveThreadResponseSchema,
  ThreadListResponseSchema,
} from './artifactReviewSchemas';

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

// Captured from a real running artifact review service.
const capturedArtifactListPayload = '{"artifacts": [{"project": "e2e", "subdir": "single", "artifact_id": "e2e/single", "last_pushed": 1785192638, "last_pushed_iso": "2026-07-27T22:50:38Z", "entry_count": 1}]}';

// Captured from a real running artifact review service.
const capturedThreadListPayload = '{"artifact_id": "e2e/single", "sub_path": "", "threads": [{"id": 1, "sub_path": "", "anchor_kind": "page", "anchor": null, "resolved": false, "author": "lead", "created_at": 1785192638, "created_at_iso": "2026-07-27T22:50:38Z", "bd_ticket": null, "replies": [{"id": 1, "body": "first note on single", "author": "lead", "created_at": 1785192638, "created_at_iso": "2026-07-27T22:50:38Z", "uploads": []}]}]}';

// Captured from a real running artifact review service.
const capturedCreateThreadPayload = '{"thread_id": 1, "reply_id": 1, "artifact_id": "e2e/single", "sub_path": "", "anchor_kind": "page", "uploads": []}';

// Captured from a real running artifact review service.
const capturedCreateReplyPayload = '{"reply_id": 2, "thread_id": 1, "uploads": []}';

// Captured from a real running artifact review service.
const capturedResolveThreadPayload = '{"id": 1, "resolved": true}';

const parsePayload = (payload: string): unknown => JSON.parse(payload);

describe('artifactReviewClient', () => {
  afterEach(() => {
    document.cookie = 'csrftoken=; Max-Age=0; path=/';
    vi.unstubAllGlobals();
  });

  it('returns ready artifacts for the index endpoint', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        artifacts: [
          {
            project: 'demo',
            subdir: 'image-set',
            artifact_id: 'demo/image-set',
            last_pushed: 1785153600,
            last_pushed_iso: '2026-07-27T12:00:00Z',
            entry_count: 1,
          },
        ],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await getArtifacts();

    expect(fetchMock).toHaveBeenCalledWith('/_/api/artifacts');
    expect(result.status).toBe('ready');
    if (result.status === 'ready') {
      expect(result.data.artifacts[0]?.artifact_id).toBe('demo/image-set');
    }
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

  it('parses captured backend response contracts through zod schemas', () => {
    expect(ArtifactListResponseSchema.safeParse(parsePayload(capturedArtifactListPayload)).success).toBe(true);
    expect(ThreadListResponseSchema.safeParse(parsePayload(capturedThreadListPayload)).success).toBe(true);
    expect(CreateThreadResponseSchema.safeParse(parsePayload(capturedCreateThreadPayload)).success).toBe(true);
    expect(CreateReplyResponseSchema.safeParse(parsePayload(capturedCreateReplyPayload)).success).toBe(true);
    expect(ResolveThreadResponseSchema.safeParse(parsePayload(capturedResolveThreadPayload)).success).toBe(true);
  });

  it('sends CSRF token from the cookie on POST requests', async () => {
    document.cookie = 'csrftoken=csrf-token-123; path=/';
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(parsePayload(capturedCreateThreadPayload), 201));
    vi.stubGlobal('fetch', fetchMock);

    await createThread({ artifact: 'demo/report', body: 'note' });

    expect(fetchMock).toHaveBeenCalledWith(
      '/_/api/threads',
      expect.objectContaining({
        method: 'POST',
        headers: { 'X-CSRFToken': 'csrf-token-123' },
      }),
    );
  });
});
