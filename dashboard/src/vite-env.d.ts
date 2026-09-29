/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Optional: the server's address, only when the Vite /v1 proxy can't be used.
  readonly VITE_API_BASE?: string;
  // Optional: organization name shown in the top bar.
  readonly VITE_ORG_NAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
