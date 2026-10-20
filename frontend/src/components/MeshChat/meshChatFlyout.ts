export type MeshChatFlyoutRect = {
  top: number;
  left: number;
  width: number;
  height: number;
};

export function measureMeshChatFlyout(
  anchor: DOMRect,
  maxWidth: number,
  minHeight: number,
): MeshChatFlyoutRect {
  const width = Math.min(maxWidth, Math.max(320, window.innerWidth - 48));
  const height = Math.min(
    Math.max(anchor.height, minHeight),
    window.innerHeight - anchor.top - 36,
  );
  return {
    top: anchor.top,
    left: anchor.left,
    width,
    height,
  };
}

export const SHELL_FLYOUT_WIDTH = 760;
export const SHELL_FLYOUT_MIN_HEIGHT = 420;
export const INFONET_FLYOUT_WIDTH = 960;
export const INFONET_FLYOUT_MIN_HEIGHT = 480;
