import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactElement } from 'react';
import {
  createReply,
  createThread,
  getArtifacts,
  getThreadsByArtifact,
  setThreadResolved,
} from './api/artifactReviewClient';
import type {
  ArtifactSummary,
  ReviewRequestState,
  Thread,
} from './api/artifactReviewTypes';
import type { ThreadListResponse } from './api/artifactReviewSchemas';
import { ThemeToggle } from './components/shell/ThemeToggle';
import './styles/app.css';

const ARTIFACTS_ENDPOINT = '/_/api/artifacts';
const THREADS_ENDPOINT = '/_/api/threads';
const DEFAULT_SUB_PATH = '';

type SubmitState = ReviewRequestState<null>;

const initialSubmitState: SubmitState = { status: 'idle' };

const encodePath = (value: string): string =>
  value.split('/').map((part) => encodeURIComponent(part)).join('/');

const artifactUrl = (artifact: ArtifactSummary): string => {
  const project = encodePath(artifact.project);
  const subdir = encodePath(artifact.subdir);
  return subdir.length > 0 ? `/${project}/${subdir}/` : `/${project}/`;
};

const endpointError = (endpoint: string, message: string): string =>
  `${endpoint} failed: ${message}`;

const formatEntryCount = (entryCount: number): string =>
  entryCount === 1 ? '1 entry' : `${entryCount} entries`;

const formatIsoTime = (isoTime: string): string => {
  const date = new Date(isoTime);
  if (Number.isNaN(date.getTime())) {
    return isoTime;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
};

const submitError = (message: string): SubmitState => ({
  status: 'error',
  message,
});

function ArtifactIndex(props: {
  readonly artifactsState: ReviewRequestState<{ readonly artifacts: readonly ArtifactSummary[] }>;
  readonly selectedArtifactId: string | null;
  readonly onSelectArtifact: (artifact: ArtifactSummary) => void;
}): ReactElement {
  const { artifactsState, selectedArtifactId, onSelectArtifact } = props;

  if (artifactsState.status === 'loading' || artifactsState.status === 'idle') {
    return <p className="notice">Loading {ARTIFACTS_ENDPOINT}...</p>;
  }

  if (artifactsState.status === 'error') {
    return <p className="notice error">{endpointError(ARTIFACTS_ENDPOINT, artifactsState.message)}</p>;
  }

  if (artifactsState.data.artifacts.length === 0) {
    return (
      <p className="notice">
        No staged artifacts are available. Artifacts arrive here when the CLI
        runs the artifact publish verb.
      </p>
    );
  }

  return (
    <ul className="artifact-list" aria-label="Staged artifacts">
      {artifactsState.data.artifacts.map((artifact) => (
        <li key={artifact.artifact_id}>
          <button
            type="button"
            className="artifact-button"
            data-selected={artifact.artifact_id === selectedArtifactId}
            onClick={() => onSelectArtifact(artifact)}
          >
            <span className="artifact-title">{artifact.project}/{artifact.subdir}</span>
            <span className="artifact-meta">{artifact.artifact_id}</span>
            <span className="artifact-meta">{formatEntryCount(artifact.entry_count)}</span>
            <span className="artifact-meta">{formatIsoTime(artifact.last_pushed_iso)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function NewThreadForm(props: {
  readonly artifact: ArtifactSummary;
  readonly onCreated: () => Promise<void>;
}): ReactElement {
  const { artifact, onCreated } = props;
  const [body, setBody] = useState('');
  const [author, setAuthor] = useState('');
  const [submitState, setSubmitState] = useState<SubmitState>(initialSubmitState);

  const submitThread = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const trimmedBody = body.trim();
    if (trimmedBody.length === 0) {
      setSubmitState(submitError('Thread body is required.'));
      return;
    }

    setSubmitState({ status: 'loading' });
    const trimmedAuthor = author.trim();
    const result = await createThread({
      artifact: artifact.artifact_id,
      sub_path: DEFAULT_SUB_PATH,
      body: trimmedBody,
      author: trimmedAuthor.length > 0 ? trimmedAuthor : undefined,
      anchor_kind: 'page',
    });

    if (result.status === 'error') {
      setSubmitState(submitError(endpointError(THREADS_ENDPOINT, result.message)));
      return;
    }

    setBody('');
    setSubmitState({ status: 'ready', data: null });
    await onCreated();
  };

  return (
    <form className="thread-form" onSubmit={(event) => void submitThread(event)}>
      <label>
        <span>New page thread</span>
        <textarea value={body} onChange={(event) => setBody(event.target.value)} />
      </label>
      <label>
        <span>Author</span>
        <input value={author} onChange={(event) => setAuthor(event.target.value)} />
      </label>
      <button type="submit">Post thread</button>
      {submitState.status === 'error' ? <p className="form-error">{submitState.message}</p> : null}
    </form>
  );
}

function ReplyForm(props: {
  readonly threadId: number;
  readonly onCreated: () => Promise<void>;
}): ReactElement {
  const { threadId, onCreated } = props;
  const [body, setBody] = useState('');
  const [submitState, setSubmitState] = useState<SubmitState>(initialSubmitState);

  const submitReply = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const trimmedBody = body.trim();
    if (trimmedBody.length === 0) {
      setSubmitState(submitError('Reply body is required.'));
      return;
    }

    setSubmitState({ status: 'loading' });
    const result = await createReply(threadId, { body: trimmedBody });
    if (result.status === 'error') {
      setSubmitState(submitError(endpointError(`${THREADS_ENDPOINT}/${threadId}/replies`, result.message)));
      return;
    }

    setBody('');
    setSubmitState({ status: 'ready', data: null });
    await onCreated();
  };

  return (
    <form className="reply-form" onSubmit={(event) => void submitReply(event)}>
      <textarea
        aria-label={`Reply to thread ${threadId}`}
        value={body}
        onChange={(event) => setBody(event.target.value)}
      />
      <button type="submit">Reply</button>
      {submitState.status === 'error' ? <p className="form-error">{submitState.message}</p> : null}
    </form>
  );
}

function ThreadCard(props: {
  readonly thread: Thread;
  readonly onChanged: () => Promise<void>;
}): ReactElement {
  const { thread, onChanged } = props;
  const [submitState, setSubmitState] = useState<SubmitState>(initialSubmitState);

  const toggleResolved = async (): Promise<void> => {
    setSubmitState({ status: 'loading' });
    const result = await setThreadResolved(thread.id, !thread.resolved);
    if (result.status === 'error') {
      setSubmitState(submitError(endpointError(`${THREADS_ENDPOINT}/${thread.id}/resolve`, result.message)));
      return;
    }
    setSubmitState({ status: 'ready', data: null });
    await onChanged();
  };

  return (
    <article className="thread-card" data-resolved={thread.resolved}>
      <header className="thread-header">
        <span className="status-pill">{thread.resolved ? 'Resolved' : 'Open'}</span>
        <span>Thread {thread.id}</span>
        <button type="button" onClick={() => void toggleResolved()}>
          {thread.resolved ? 'Reopen' : 'Resolve'}
        </button>
      </header>
      <p className="thread-meta">
        {thread.anchor_kind} anchor on {thread.sub_path || 'page root'}
      </p>
      {thread.replies.map((reply) => (
        <section className="reply" key={reply.id}>
          <p>{reply.body}</p>
          <footer>{reply.author ?? 'Unknown'} at {formatIsoTime(reply.created_at_iso)}</footer>
        </section>
      ))}
      <ReplyForm threadId={thread.id} onCreated={onChanged} />
      {submitState.status === 'error' ? <p className="form-error">{submitState.message}</p> : null}
    </article>
  );
}

function ThreadList(props: {
  readonly artifact: ArtifactSummary;
  readonly threadsState: ReviewRequestState<ThreadListResponse>;
  readonly onChanged: () => Promise<void>;
}): ReactElement {
  const { artifact, threadsState, onChanged } = props;

  if (threadsState.status === 'loading' || threadsState.status === 'idle') {
    return <p className="notice">Loading {THREADS_ENDPOINT}...</p>;
  }

  if (threadsState.status === 'error') {
    return <p className="notice error">{endpointError(THREADS_ENDPOINT, threadsState.message)}</p>;
  }

  return (
    <div className="threads">
      <NewThreadForm artifact={artifact} onCreated={onChanged} />
      {threadsState.data.threads.length === 0 ? (
        <p className="notice">No feedback threads for this artifact yet.</p>
      ) : (
        threadsState.data.threads.map((thread) => (
          <ThreadCard key={thread.id} thread={thread} onChanged={onChanged} />
        ))
      )}
    </div>
  );
}

function ArtifactView(props: {
  readonly artifact: ArtifactSummary;
  readonly threadsState: ReviewRequestState<ThreadListResponse>;
  readonly onThreadsChanged: () => Promise<void>;
}): ReactElement {
  const { artifact, threadsState, onThreadsChanged } = props;
  const src = useMemo(() => artifactUrl(artifact), [artifact]);

  return (
    <section className="artifact-view" aria-label="Artifact review">
      <div className="viewer-pane">
        <iframe
          title={`Artifact ${artifact.artifact_id}`}
          src={src}
          sandbox=""
        />
      </div>
      <aside className="feedback-pane">
        <h2>Feedback</h2>
        <ThreadList artifact={artifact} threadsState={threadsState} onChanged={onThreadsChanged} />
      </aside>
    </section>
  );
}

export function App(): ReactElement {
  const [artifactsState, setArtifactsState] =
    useState<ReviewRequestState<{ readonly artifacts: readonly ArtifactSummary[] }>>({ status: 'loading' });
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [threadsState, setThreadsState] =
    useState<ReviewRequestState<ThreadListResponse>>({ status: 'idle' });

  const selectedArtifact = useMemo(() => {
    if (artifactsState.status !== 'ready' && artifactsState.status !== 'empty') {
      return null;
    }
    return artifactsState.data.artifacts.find((artifact) => artifact.artifact_id === selectedArtifactId) ?? null;
  }, [artifactsState, selectedArtifactId]);

  const loadArtifacts = useCallback(async (): Promise<void> => {
    setArtifactsState({ status: 'loading' });
    setArtifactsState(await getArtifacts());
  }, []);

  const loadThreads = useCallback(async (artifact: ArtifactSummary): Promise<void> => {
    setThreadsState({ status: 'loading' });
    setThreadsState(await getThreadsByArtifact({
      artifact: artifact.artifact_id,
      subPath: DEFAULT_SUB_PATH,
    }));
  }, []);

  useEffect(() => {
    void loadArtifacts();
  }, [loadArtifacts]);

  useEffect(() => {
    if (selectedArtifactId !== null || artifactsState.status !== 'ready') {
      return;
    }

    setSelectedArtifactId(artifactsState.data.artifacts[0]?.artifact_id ?? null);
  }, [artifactsState, selectedArtifactId]);

  useEffect(() => {
    if (selectedArtifact === null) {
      setThreadsState({ status: 'idle' });
      return;
    }

    void loadThreads(selectedArtifact);
  }, [loadThreads, selectedArtifact]);

  const selectArtifact = (artifact: ArtifactSummary): void => {
    setSelectedArtifactId(artifact.artifact_id);
  };

  const reloadSelectedThreads = async (): Promise<void> => {
    if (selectedArtifact !== null) {
      await loadThreads(selectedArtifact);
    }
  };

  return (
    <main className="review-app">
      <header className="app-header">
        <div>
          <h1>Artifact Review</h1>
          <p>Local staged artifact feedback</p>
        </div>
        <ThemeToggle />
      </header>
      <div className="review-layout">
        <nav className="artifact-pane" aria-label="Artifact index">
          <ArtifactIndex
            artifactsState={artifactsState}
            selectedArtifactId={selectedArtifactId}
            onSelectArtifact={selectArtifact}
          />
        </nav>
        {selectedArtifact === null ? (
          <section className="empty-view">
            <p>Select an artifact to review its staged content and feedback.</p>
          </section>
        ) : (
          <ArtifactView
            artifact={selectedArtifact}
            threadsState={threadsState}
            onThreadsChanged={reloadSelectedThreads}
          />
        )}
      </div>
    </main>
  );
}
