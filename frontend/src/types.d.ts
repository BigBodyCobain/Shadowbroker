declare module '@mapbox/point-geometry';
declare module 'mapbox__point-geometry';
declare module 'qrcode' {
  interface QRCodeToDataURLOptions {
    errorCorrectionLevel?: 'L' | 'M' | 'Q' | 'H';
    margin?: number;
    width?: number;
    color?: {
      dark?: string;
      light?: string;
    };
  }

  interface QRCodeModule {
    toDataURL(text: string, options?: QRCodeToDataURLOptions): Promise<string>;
  }

  const QRCode: QRCodeModule;
  export default QRCode;
}

interface Window {
  __SHADOWBROKER_DESKTOP__?: import('@/lib/desktopBridge').ShadowbrokerDesktopRuntime;
  __SHADOWBROKER_LOCAL_CONTROL__?: import('@/lib/localControlTransport').ShadowbrokerLocalControlBridge;
}
