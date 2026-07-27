import { z } from 'zod';
import type {
  CodeLineAnchor,
  ImageRegionAnchor,
  LegacyComment,
  Reply,
  Settings,
  Thread,
  Upload,
} from './artifactReviewTypes';

export const AnchorKindSchema = z.union([
  z.literal('page'),
  z.literal('image_region'),
  z.literal('code_line'),
]);

export const ImageRegionAnchorSchema: z.ZodType<ImageRegionAnchor> = z.object({
  selector: z.object({
    type: z.literal('FragmentSelector'),
    value: z.string(),
    conformsTo: z.string().optional(),
  }),
});

export const CodeLineAnchorSchema: z.ZodType<CodeLineAnchor> = z
  .object({
    line: z.number().int().min(1),
    end_line: z.number().int().min(1).optional(),
  })
  .refine((anchor) => anchor.end_line === undefined || anchor.end_line >= anchor.line, {
    message: 'end_line must be greater than or equal to line',
    path: ['end_line'],
  });

const ThreadAnchorSchema = z.union([ImageRegionAnchorSchema, CodeLineAnchorSchema, z.null()]);

export const UploadSchema: z.ZodType<Upload> = z.object({
  id: z.number().int(),
  filename: z.string(),
  stored_path: z.string(),
  mime: z.string().nullable(),
  size: z.number().int(),
  created_at: z.number(),
  created_at_iso: z.string(),
});

export const ReplySchema: z.ZodType<Reply> = z.object({
  id: z.number().int(),
  body: z.string(),
  author: z.string().nullable(),
  created_at: z.number(),
  created_at_iso: z.string(),
  uploads: z.array(UploadSchema),
});

export const ThreadSchema: z.ZodType<Thread> = z
  .object({
    id: z.number().int(),
    sub_path: z.string(),
    anchor_kind: AnchorKindSchema,
    anchor: ThreadAnchorSchema,
    resolved: z.boolean(),
    author: z.string().nullable(),
    created_at: z.number(),
    created_at_iso: z.string(),
    bd_ticket: z.string().nullable(),
    replies: z.array(ReplySchema),
  })
  .superRefine((thread, context) => {
    if (thread.anchor_kind === 'page' && thread.anchor !== null) {
      context.addIssue({ code: 'custom', message: 'page anchor must be null', path: ['anchor'] });
    }
    if (thread.anchor_kind === 'image_region' && !ImageRegionAnchorSchema.safeParse(thread.anchor).success) {
      context.addIssue({ code: 'custom', message: 'image_region anchor must be a FragmentSelector', path: ['anchor'] });
    }
    if (thread.anchor_kind === 'code_line' && !CodeLineAnchorSchema.safeParse(thread.anchor).success) {
      context.addIssue({ code: 'custom', message: 'code_line anchor must be line data', path: ['anchor'] });
    }
  });

export const LegacyCommentSchema: z.ZodType<LegacyComment> = z.object({
  id: z.number().int(),
  thread_id: z.number().int(),
  sub_path: z.string(),
  body: z.string(),
  author: z.string().nullable(),
  created_at: z.number(),
  created_at_iso: z.string(),
  resolved: z.boolean(),
  uploads: z.array(UploadSchema),
});

export const SettingsSchema: z.ZodType<Settings> = z.record(z.string(), z.string());

export const ThreadListResponseSchema = z.object({
  artifact_id: z.string(),
  sub_path: z.string(),
  threads: z.array(ThreadSchema),
});

export const CreateThreadResponseSchema = z.object({
  thread_id: z.number().int(),
  reply_id: z.number().int(),
  artifact_id: z.string(),
  sub_path: z.string(),
  anchor_kind: AnchorKindSchema,
  uploads: z.array(UploadSchema),
});

export const CreateReplyResponseSchema = z.object({
  reply_id: z.number().int(),
  thread_id: z.number().int(),
  uploads: z.array(UploadSchema),
});

export const ResolveThreadResponseSchema = z.object({
  id: z.number().int(),
  resolved: z.boolean(),
});

export const CommentListResponseSchema = z.object({
  artifact_id: z.string(),
  sub_path: z.string(),
  comments: z.array(LegacyCommentSchema),
});

export const CreateCommentResponseSchema = z.object({
  id: z.number().int(),
  thread_id: z.number().int(),
  artifact_id: z.string(),
  sub_path: z.string(),
});

export type ThreadListResponse = z.infer<typeof ThreadListResponseSchema>;
export type CreateThreadResponse = z.infer<typeof CreateThreadResponseSchema>;
export type CreateReplyResponse = z.infer<typeof CreateReplyResponseSchema>;
export type ResolveThreadResponse = z.infer<typeof ResolveThreadResponseSchema>;
export type CommentListResponse = z.infer<typeof CommentListResponseSchema>;
export type CreateCommentResponse = z.infer<typeof CreateCommentResponseSchema>;
