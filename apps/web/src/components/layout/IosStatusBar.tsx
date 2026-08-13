'use client';

import { useEffect, useState } from 'react';

function formatTime(d: Date) {
  return `${d.getHours()}:${d.getMinutes().toString().padStart(2, '0')}`;
}

/** 仅桌面 preview 壳显示；native/standalone 由 CSS 隐藏 */
export function IosStatusBar() {
  const [time, setTime] = useState(() => formatTime(new Date()));

  useEffect(() => {
    const tick = () => setTime(formatTime(new Date()));
    tick();
    const id = window.setInterval(tick, 15_000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="ios-status-bar" aria-hidden>
      <span className="ios-status-bar__time">{time}</span>
      <span className="ios-status-bar__spacer" />
      <span className="ios-status-bar__right">
        <span className="ios-status-bar__battery">
          <span className="ios-status-bar__battery-body">
            <span className="ios-status-bar__battery-level" />
          </span>
          <span className="ios-status-bar__battery-cap" />
        </span>
      </span>
    </div>
  );
}
