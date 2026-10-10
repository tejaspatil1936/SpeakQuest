/** A failed API call with a stable code the UI can explain. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly stage: string | null;

  constructor(code: string, message: string, status = 0, stage: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.stage = stage;
  }

  /** Whether trying the same request again could succeed. */
  get retryable(): boolean {
    return (
      this.status === 0 ||
      this.status === 408 ||
      this.status === 429 ||
      this.status >= 500 ||
      this.code === "NETWORK" ||
      this.code === "TIMEOUT"
    );
  }
}

const COPY: Record<string, string> = {
  NETWORK: "Can't reach the studio. Check your connection and try again.",
  TIMEOUT: "The studio took too long to answer. Try again.",
  THROTTLED: "Too many takes at once. Wait a few seconds, then try again.",
  BAD_RESPONSE: "The studio sent something we couldn't read.",
};

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return COPY[error.code] ?? error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
