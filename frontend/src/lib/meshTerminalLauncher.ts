const MESH_TERMINAL_OPEN_EVENT = 'oracle:open-mesh-terminal';
const SECURE_MESH_TERMINAL_LAUNCHER_EVENT = 'oracle:open-secure-mesh-terminal-launcher';

export function requestMeshTerminalOpen(source = 'ui'): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent(MESH_TERMINAL_OPEN_EVENT, {
      detail: { source, at: Date.now() },
    }),
  );
}

export function subscribeMeshTerminalOpen(handler: () => void): () => void {
  if (typeof window === 'undefined') {
    return () => {};
  }

  const listener = () => handler();
  window.addEventListener(MESH_TERMINAL_OPEN_EVENT, listener);
  return () => window.removeEventListener(MESH_TERMINAL_OPEN_EVENT, listener);
}

export function requestSecureMeshTerminalLauncherOpen(source = 'ui'): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent(SECURE_MESH_TERMINAL_LAUNCHER_EVENT, {
      detail: { source, at: Date.now() },
    }),
  );
}

export function subscribeSecureMeshTerminalLauncherOpen(handler: () => void): () => void {
  if (typeof window === 'undefined') {
    return () => {};
  }

  const listener = () => handler();
  window.addEventListener(SECURE_MESH_TERMINAL_LAUNCHER_EVENT, listener);
  return () => window.removeEventListener(SECURE_MESH_TERMINAL_LAUNCHER_EVENT, listener);
}
