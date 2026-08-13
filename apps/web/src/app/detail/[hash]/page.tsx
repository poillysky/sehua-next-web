'use client';

import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';

/** 深链兼容：/detail/:hash → /?detail=hash（留在主 Tab Shell 内） */
export default function DetailPage() {
  const params = useParams<{ hash: string }>();
  const router = useRouter();
  const hash = decodeURIComponent(params.hash || '');

  useEffect(() => {
    if (!hash) {
      router.replace('/');
      return;
    }
    router.replace(`/?detail=${encodeURIComponent(hash)}`);
  }, [hash, router]);

  return null;
}
