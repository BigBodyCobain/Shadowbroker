'use client';

import Image, { type ImageLoaderProps, type ImageProps } from 'next/image';

const passthroughLoader = ({ src }: ImageLoaderProps) => src;

type ExternalImageProps = Omit<ImageProps, 'loader'> & {
  unoptimized?: boolean;
};

export default function ExternalImage({
  unoptimized = true,
  alt = '',
  fill,
  width,
  height,
  ...rest
}: ExternalImageProps) {
  if (fill) {
    return (
      <Image loader={passthroughLoader} unoptimized={unoptimized} fill alt={alt} {...rest} />
    );
  }

  return (
    <Image
      loader={passthroughLoader}
      unoptimized={unoptimized}
      width={width ?? 640}
      height={height ?? 360}
      alt={alt}
      {...rest}
    />
  );
}
