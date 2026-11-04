/// <reference types="vite/client" />

type ImportMetaEnv = {
  readonly VITE_BEL_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
