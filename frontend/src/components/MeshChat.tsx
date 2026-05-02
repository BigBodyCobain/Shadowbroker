// Re-export from decomposed MeshChat module.
// The original monolith has been split into:
//   MeshChat/useMeshChatController.ts — controller hook (state, effects, handlers)
//   MeshChat/index.tsx — presentational shell
//   MeshChat/types.ts, utils.ts, storage.ts — extracted shared modules
export { default } from './MeshChat/index';
export type { MeshChatProps } from './MeshChat/types';
