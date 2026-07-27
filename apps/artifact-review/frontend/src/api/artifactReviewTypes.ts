export type ArtifactId = string;

export type AnchorKind = 'page' | 'image_region' | 'code_line';

export type ImageRegionAnchor = {
  readonly selector: {
    readonly type: 'FragmentSelector';
    readonly value: string;
    readonly conformsTo?: string;
  };
};

export type CodeLineAnchor = {
  readonly line: number;
  readonly end_line?: number;
};

export type ThreadAnchor = ImageRegionAnchor | CodeLineAnchor | null;

export type Upload = {
  readonly id: number;
  readonly filename: string;
  readonly stored_path: string;
  readonly mime: string | null;
  readonly size: number;
  readonly created_at: number;
  readonly created_at_iso: string;
};

export type Reply = {
  readonly id: number;
  readonly body: string;
  readonly author: string | null;
  readonly created_at: number;
  readonly created_at_iso: string;
  readonly uploads: readonly Upload[];
};

export type Thread = {
  readonly id: number;
  readonly sub_path: string;
  readonly anchor_kind: AnchorKind;
  readonly anchor: ThreadAnchor;
  readonly resolved: boolean;
  readonly author: string | null;
  readonly created_at: number;
  readonly created_at_iso: string;
  readonly bd_ticket: string | null;
  readonly replies: readonly Reply[];
};

export type LegacyComment = {
  readonly id: number;
  readonly thread_id: number;
  readonly sub_path: string;
  readonly body: string;
  readonly author: string | null;
  readonly created_at: number;
  readonly created_at_iso: string;
  readonly resolved: boolean;
  readonly uploads: readonly Upload[];
};

export type Settings = Record<string, string> & {
  readonly schema_version?: string;
  readonly author?: string;
  readonly bd_mirror?: string;
};

export type ReviewRequestState<T> =
  | { readonly status: 'idle' }
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly data: T }
  | { readonly status: 'empty'; readonly data: T }
  | { readonly status: 'error'; readonly message: string };

export type ArtifactQueueRow = {
  readonly id: ArtifactId;
  readonly name: string;
  readonly kind: string;
  readonly version: string;
  readonly openCount: number;
  readonly state: 'open' | 'resolved' | 'draft';
};

export type LedgerRow = {
  readonly artifact: ArtifactId;
  readonly type: AnchorKind | 'report_block' | 'gallery_tile';
  readonly anchor: ThreadAnchor | string;
  readonly state: 'open' | 'resolved' | 'draft';
  readonly replies: number;
  readonly age: string;
  readonly excerpt: string;
};
