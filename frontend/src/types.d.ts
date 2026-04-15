declare module '@mapbox/point-geometry';
declare module 'mapbox__point-geometry';

interface Window {
  __SHADOWBROKER_DESKTOP__?: import('@/lib/desktopBridge').ShadowbrokerDesktopRuntime;
  __SHADOWBROKER_LOCAL_CONTROL__?: import('@/lib/localControlTransport').ShadowbrokerLocalControlBridge;
}
