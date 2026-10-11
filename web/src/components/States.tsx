import { describeError, ApiError } from "../api/errors";

/** Loading line: a mono label, no spinner graphics. */
export function Loading({ what }: { what: string }) {
  return (
    <p className="label px-[var(--gutter)] py-16 text-ink-2" role="status" aria-live="polite">
      Loading {what}…
    </p>
  );
}

export function ErrorPanel({
  error,
  onRetry,
  title = "That didn't work.",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const code = error instanceof ApiError ? error.code : null;
  const retryable = error instanceof ApiError ? error.retryable : true;
  return (
    <div role="alert" className="mx-[var(--gutter)] my-10 border-l-4 border-tally py-2 pl-5">
      <p className="display text-l">{title}</p>
      <p className="mt-2 max-w-prose">{describeError(error)}</p>
      {code && <p className="label mt-2 text-ink-2">Code {code}</p>}
      {onRetry && retryable && (
        <button type="button" className="btn mt-4" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
