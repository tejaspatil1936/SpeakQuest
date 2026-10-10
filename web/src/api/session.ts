/**
 * Anonymous identity (system design §3): a UUID created on first visit and
 * sent as `x-session-id`. No accounts, nothing to tear down.
 */
const KEY = "sq.session";

function uuid(): string {
  const c: Crypto = globalThis.crypto;
  if (typeof c.randomUUID === "function") return c.randomUUID();
  const bytes = new Uint8Array(16);
  c.getRandomValues(bytes);
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

let memory: string | null = null;

export function getSessionId(storage: Storage | undefined = globalThis.localStorage): string {
  try {
    const existing = storage?.getItem(KEY);
    if (existing && /^[0-9a-f-]{36}$/i.test(existing)) return existing;
    const fresh = uuid();
    storage?.setItem(KEY, fresh);
    return fresh;
  } catch {
    // Private mode / blocked storage: keep one id for this tab.
    memory ??= uuid();
    return memory;
  }
}
