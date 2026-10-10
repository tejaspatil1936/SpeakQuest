/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the SpeakQuest HTTP API. Unset → demo build. */
  readonly VITE_API_URL?: string;
  /** "1" forces the demo adapter even when an API URL is set. */
  readonly VITE_DEMO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
