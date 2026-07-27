import type { ZodType } from 'zod';
import {
  CommentListResponseSchema,
  CreateCommentResponseSchema,
  CreateReplyResponseSchema,
  CreateThreadResponseSchema,
  ResolveThreadResponseSchema,
  SettingsSchema,
  ThreadListResponseSchema,
  type CommentListResponse,
  type CreateCommentResponse,
  type CreateReplyResponse,
  type CreateThreadResponse,
  type ResolveThreadResponse,
  type ThreadListResponse,
} from './artifactReviewSchemas';
import type { ReviewRequestState, Settings } from './artifactReviewTypes';
import {
  createCommentFormData,
  createReplyFormData,
  createThreadFormData,
  type CreateCommentFormInput,
  type CreateReplyFormInput,
  type CreateThreadFormInput,
} from './formData';

type ArtifactThreadQuery = {
  readonly artifact: string;
  readonly subPath?: string;
};

type CommentQuery = ArtifactThreadQuery | { readonly url: string };

type JsonResult<T> = {
  readonly data: T;
  readonly empty: boolean;
};

const jsonHeaders = {
  'Content-Type': 'application/json',
} satisfies HeadersInit;

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

const threadsUrl = (input: ArtifactThreadQuery | { readonly url: string }): string => {
  const searchParams = new URLSearchParams();
  if ('url' in input) {
    searchParams.set('url', input.url);
  } else {
    appendArtifactQuery(searchParams, input);
  }
  return `/_/api/threads?${searchParams.toString()}`;
};

const commentsUrl = (input: CommentQuery): string => {
  const searchParams = new URLSearchParams();
  if ('url' in input) {
    searchParams.set('url', input.url);
  } else {
    appendArtifactQuery(searchParams, input);
  }
  return `/_/api/comments?${searchParams.toString()}`;
};

const threadListResult = (data: ThreadListResponse): JsonResult<ThreadListResponse> => ({
  data,
  empty: data.threads.length === 0,
});

const commentListResult = (data: CommentListResponse): JsonResult<CommentListResponse> => ({
  data,
  empty: data.comments.length === 0,
});

export const getSettings = (): Promise<ReviewRequestState<Settings>> =>
  requestJson(fetch('/_/api/settings'), SettingsSchema);

export const getUpload = (id: number): Promise<ReviewRequestState<Response>> =>
  requestResponse(fetch(`/_/api/uploads/${encodeURIComponent(String(id))}`));

export const getThreadsByArtifact = (input: ArtifactThreadQuery): Promise<ReviewRequestState<ThreadListResponse>> =>
  requestJson(fetch(threadsUrl(input)), ThreadListResponseSchema, threadListResult);

export const getThreadsByUrl = (url: string): Promise<ReviewRequestState<ThreadListResponse>> =>
  requestJson(fetch(threadsUrl({ url })), ThreadListResponseSchema, threadListResult);

export const createThread = (input: CreateThreadFormInput): Promise<ReviewRequestState<CreateThreadResponse>> =>
  requestJson(
    fetch('/_/api/threads', {
      method: 'POST',
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
      headers: jsonHeaders,
      body: JSON.stringify({ resolved }),
    }),
    ResolveThreadResponseSchema,
  );

export const toggleThreadResolved = (id: number): Promise<ReviewRequestState<ResolveThreadResponse>> =>
  requestJson(
    fetch(`/_/api/threads/${encodeURIComponent(String(id))}/resolve`, {
      method: 'POST',
    }),
    ResolveThreadResponseSchema,
  );

export const getComments = (input: CommentQuery): Promise<ReviewRequestState<CommentListResponse>> =>
  requestJson(fetch(commentsUrl(input)), CommentListResponseSchema, commentListResult);

export const createComment = (input: CreateCommentFormInput): Promise<ReviewRequestState<CreateCommentResponse>> =>
  requestJson(
    fetch('/_/api/comments', {
      method: 'POST',
      body: createCommentFormData(input),
    }),
    CreateCommentResponseSchema,
  );

export const getArtifactBytes = (url: string): Promise<ReviewRequestState<Response>> => requestResponse(fetch(url));
