import type { ZodType } from 'zod';
import {
  ArtifactListResponseSchema,
  CreateReplyResponseSchema,
  CreateThreadResponseSchema,
  ResolveThreadResponseSchema,
  SettingsSchema,
  ThreadListResponseSchema,
  type ArtifactListResponse,
  type CreateReplyResponse,
  type CreateThreadResponse,
  type ResolveThreadResponse,
  type ThreadListResponse,
} from './artifactReviewSchemas';
import type { ReviewRequestState, Settings } from './artifactReviewTypes';
import {
  createReplyFormData,
  createThreadFormData,
  type CreateReplyFormInput,
  type CreateThreadFormInput,
} from './formData';

type ArtifactThreadQuery = {
  readonly artifact: string;
  readonly subPath?: string;
};

type JsonResult<T> = {
  readonly data: T;
  readonly empty: boolean;
};

const jsonHeaders = {
  'Content-Type': 'application/json',
} satisfies HeadersInit;

const csrfHeaders = (): Record<string, string> => {
  const cookie = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('csrftoken='));
  if (cookie === undefined) {
    return {};
  }
  return { 'X-CSRFToken': decodeURIComponent(cookie.slice('csrftoken='.length)) };
};

const postHeaders = (headers: Record<string, string> = {}): HeadersInit => ({
  ...csrfHeaders(),
  ...headers,
});

const errorState = <T>(message: string): ReviewRequestState<T> => ({ status: 'error', message });

type ParsedJsonState =
  | { readonly status: 'ready'; readonly data: unknown }
  | { readonly status: 'error'; readonly message: string };

const parseJson = async (response: Response): Promise<ParsedJsonState> => {
  try {
    const data: unknown = await response.json();
    return { status: 'ready', data };
  } catch {
    return { status: 'error', message: 'Response was not valid JSON.' };
  }
};

const requestJson = async <T>(
  request: Promise<Response>,
  schema: ZodType<T>,
  toJsonResult: (data: T) => JsonResult<T> = (data) => ({ data, empty: false }),
): Promise<ReviewRequestState<T>> => {
  try {
    const response = await request;
    if (!response.ok) {
      return errorState(`Request failed with status ${response.status}.`);
    }

    const jsonState = await parseJson(response);
    if (jsonState.status === 'error') {
      return jsonState;
    }

    const parsed = schema.safeParse(jsonState.data);
    if (!parsed.success) {
      return errorState('Response shape did not match the API contract.');
    }

    const result = toJsonResult(parsed.data);
    return result.empty ? { status: 'empty', data: result.data } : { status: 'ready', data: result.data };
  } catch {
    return errorState('Network request failed.');
  }
};

const requestResponse = async (request: Promise<Response>): Promise<ReviewRequestState<Response>> => {
  try {
    const response = await request;
    if (!response.ok) {
      return errorState(`Request failed with status ${response.status}.`);
    }
    return { status: 'ready', data: response };
  } catch {
    return errorState('Network request failed.');
  }
};

const appendArtifactQuery = (searchParams: URLSearchParams, input: ArtifactThreadQuery): void => {
  searchParams.set('artifact', input.artifact);
  if (input.subPath !== undefined) {
    searchParams.set('sub_path', input.subPath);
  }
};

const artifactListResult = (data: ArtifactListResponse): JsonResult<ArtifactListResponse> => ({
  data,
  empty: data.artifacts.length === 0,
});

const threadsUrl = (input: ArtifactThreadQuery): string => {
  const searchParams = new URLSearchParams();
  appendArtifactQuery(searchParams, input);
  return `/_/api/threads?${searchParams.toString()}`;
};

const threadListResult = (data: ThreadListResponse): JsonResult<ThreadListResponse> => ({
  data,
  empty: data.threads.length === 0,
});

export const getSettings = (): Promise<ReviewRequestState<Settings>> =>
  requestJson(fetch('/_/api/settings'), SettingsSchema);

export const getArtifacts = (): Promise<ReviewRequestState<ArtifactListResponse>> =>
  requestJson(fetch('/_/api/artifacts'), ArtifactListResponseSchema, artifactListResult);

export const getUpload = (id: number): Promise<ReviewRequestState<Response>> =>
  requestResponse(fetch(`/_/api/uploads/${encodeURIComponent(String(id))}`));

export const getThreadsByArtifact = (input: ArtifactThreadQuery): Promise<ReviewRequestState<ThreadListResponse>> =>
  requestJson(fetch(threadsUrl(input)), ThreadListResponseSchema, threadListResult);

export const createThread = (input: CreateThreadFormInput): Promise<ReviewRequestState<CreateThreadResponse>> =>
  requestJson(
    fetch('/_/api/threads', {
      method: 'POST',
      headers: postHeaders(),
      body: createThreadFormData(input),
    }),
    CreateThreadResponseSchema,
  );

export const createReply = (
  threadId: number,
  input: CreateReplyFormInput,
): Promise<ReviewRequestState<CreateReplyResponse>> =>
  requestJson(
    fetch(`/_/api/threads/${encodeURIComponent(String(threadId))}/replies`, {
      method: 'POST',
      headers: postHeaders(),
      body: createReplyFormData(input),
    }),
    CreateReplyResponseSchema,
  );

export const setThreadResolved = (
  id: number,
  resolved: boolean,
): Promise<ReviewRequestState<ResolveThreadResponse>> =>
  requestJson(
    fetch(`/_/api/threads/${encodeURIComponent(String(id))}/resolve`, {
      method: 'POST',
      headers: postHeaders(jsonHeaders),
      body: JSON.stringify({ resolved }),
    }),
    ResolveThreadResponseSchema,
  );

export const toggleThreadResolved = (id: number): Promise<ReviewRequestState<ResolveThreadResponse>> =>
  requestJson(
    fetch(`/_/api/threads/${encodeURIComponent(String(id))}/resolve`, {
      method: 'POST',
      headers: postHeaders(),
    }),
    ResolveThreadResponseSchema,
  );

export const getArtifactBytes = (url: string): Promise<ReviewRequestState<Response>> => requestResponse(fetch(url));
