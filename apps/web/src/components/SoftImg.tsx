'use client';

import {
  useEffect,
  useRef,
  useState,
  type ImgHTMLAttributes,
  type SyntheticEvent,
} from 'react';

type SoftImgProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'onError' | 'onLoad'> & {
  /** 加载成功前保持透明，避免破图图标闪一下 */
  onError?: (e: SyntheticEvent<HTMLImageElement>) => void;
  onLoad?: (e: SyntheticEvent<HTMLImageElement>) => void;
};

/**
 * 封面/头像用：未 onLoad 前 opacity:0，失败也不露破图。
 * 父级背景/字母占位继续可见。
 */
export function SoftImg({
  src,
  className,
  onError,
  onLoad,
  alt = '',
  decoding = 'async',
  referrerPolicy = 'no-referrer',
  ...rest
}: SoftImgProps) {
  const [ready, setReady] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const url = String(src || '').trim();

  useEffect(() => {
    setReady(false);
    // 缓存命中时部分浏览器不触发 onLoad，需主动认 ready
    const el = imgRef.current;
    if (el && el.complete && el.naturalWidth > 0) {
      setReady(true);
    }
  }, [url]);

  if (!url) return null;

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      {...rest}
      ref={imgRef}
      className={['soft-img', className].filter(Boolean).join(' ')}
      data-ready={ready ? '1' : undefined}
      src={url}
      alt={alt}
      decoding={decoding}
      referrerPolicy={referrerPolicy}
      onLoad={(e) => {
        setReady(true);
        onLoad?.(e);
      }}
      onError={(e) => {
        setReady(false);
        onError?.(e);
      }}
    />
  );
}
