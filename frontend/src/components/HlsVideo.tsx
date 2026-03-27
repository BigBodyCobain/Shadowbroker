'use client';

import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react';

export interface HlsVideoHandle {
  play(): void;
  pause(): void;
  get paused(): boolean;
}

const HlsVideo = forwardRef<HlsVideoHandle, { url: string; className?: string; onError?: () => void }>(
  ({ url, className, onError }, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);

    useImperativeHandle(ref, () => ({
      play: () => videoRef.current?.play(),
      pause: () => videoRef.current?.pause(),
      get paused() {
        return videoRef.current?.paused ?? true;
      },
    }));

    useEffect(() => {
      const video = videoRef.current;
      if (!video || !url) return;

      let hlsInstance: { destroy(): void } | null = null;
      let cancelled = false;

      (async () => {
        const { default: Hls } = await import('hls.js');
        if (cancelled) return;
        if (Hls.isSupported()) {
          const hls = new Hls({ enableWorker: false, lowLatencyMode: true });
          hls.on(Hls.Events.ERROR, (_e: unknown, data: { fatal?: boolean }) => {
            if (data.fatal) onError?.();
          });
          hls.loadSource(url);
          hls.attachMedia(video);
          hlsInstance = hls;
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
          video.src = url;
        }
      })();

      return () => {
        cancelled = true;
        hlsInstance?.destroy();
      };
    }, [url, onError]);

    return (
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        onError={() => onError?.()}
        className={className}
      />
    );
  },
);

HlsVideo.displayName = 'HlsVideo';
export default HlsVideo;
