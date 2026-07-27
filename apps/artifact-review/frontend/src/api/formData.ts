import type { AnchorKind, CodeLineAnchor, ImageRegionAnchor } from './artifactReviewTypes';

type ReviewTarget =
  | { readonly artifact: string; readonly url?: never; readonly sub_path?: string }
  | { readonly url: string; readonly artifact?: never; readonly sub_path?: string };

export type CreateThreadFormInput = ReviewTarget & {
  readonly body: string;
  readonly author?: string;
  readonly files?: readonly File[];
  readonly anchor_kind?: AnchorKind;
  readonly anchor_data?: ImageRegionAnchor | CodeLineAnchor;
};

export type CreateReplyFormInput = {
  readonly body: string;
  readonly author?: string;
  readonly files?: readonly File[];
};

export type CreateCommentFormInput = ReviewTarget & {
  readonly body: string;
  readonly author?: string;
  readonly files?: readonly File[];
};

const appendText = (formData: FormData, name: string, value: string | undefined): void => {
  if (value !== undefined) {
    formData.append(name, value);
  }
};

const appendFiles = (formData: FormData, files: readonly File[] | undefined): void => {
  for (const file of files ?? []) {
    formData.append('files', file);
  }
};

const appendTarget = (formData: FormData, input: ReviewTarget): void => {
  appendText(formData, 'artifact', input.artifact);
  appendText(formData, 'url', input.url);
  appendText(formData, 'sub_path', input.sub_path);
};

export const createThreadFormData = (input: CreateThreadFormInput): FormData => {
  const formData = new FormData();
  appendTarget(formData, input);
  formData.append('body', input.body);
  appendText(formData, 'author', input.author);
  appendText(formData, 'anchor_kind', input.anchor_kind);
  if (input.anchor_data !== undefined) {
    formData.append('anchor_data', JSON.stringify(input.anchor_data));
  }
  appendFiles(formData, input.files);
  return formData;
};

export const createReplyFormData = (input: CreateReplyFormInput): FormData => {
  const formData = new FormData();
  formData.append('body', input.body);
  appendText(formData, 'author', input.author);
  appendFiles(formData, input.files);
  return formData;
};

export const createCommentFormData = (input: CreateCommentFormInput): FormData => {
  const formData = new FormData();
  appendTarget(formData, input);
  formData.append('body', input.body);
  appendText(formData, 'author', input.author);
  appendFiles(formData, input.files);
  return formData;
};
