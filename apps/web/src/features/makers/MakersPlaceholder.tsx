'use client';

/** 片商 Tab 占位（实现已移除） */
export function MakersPlaceholder() {
  return (
    <div className="app-hub makers-hub">
      <div className="makers-hub__top">
        <h1 className="settings-hub__title">片商</h1>
      </div>
      <div className="settings-hub__scroll flex flex-1 flex-col items-center justify-center gap-2 text-center">
        <p className="text-sm" style={{ color: 'var(--mute)', margin: 0 }}>
          功能已下线
        </p>
      </div>
    </div>
  );
}
