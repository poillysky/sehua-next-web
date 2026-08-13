'use client';

import { IosStatusBar } from './IosStatusBar';
import './device-frame.css';

/**
 * 桌面宽屏：模拟 iPhone 屏幕（刘海 + 状态栏 + Home 指示条）
 * 真机 / 窄屏 / standalone：全屏 native
 */
export function DeviceFrame({
  children,
  label = 'NextWeb',
}: {
  children: React.ReactNode;
  label?: string;
}) {
  return (
    <div className="device-stage">
      <div className="device-frame" aria-label={label}>
        <div className="device-bezel">
          <div className="bg-effect bg-effect--static" aria-hidden />
          <div className="ios-notch" aria-hidden />
          <IosStatusBar />
          <div className="device-content">
            {children}
            <div id="app-overlay-root" className="app-overlay-root" />
          </div>
          <div className="ios-home-indicator" aria-hidden />
        </div>
      </div>
    </div>
  );
}
