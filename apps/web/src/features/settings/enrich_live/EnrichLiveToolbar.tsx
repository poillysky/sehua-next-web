'use client';

export function EnrichLiveToolbar({
  mode,
  running,
  stopping,
  clearing,
  queueScanning,
  queueScanHere,
  retryingFails,
  retryingSofts,
  rescraping,
  onPause,
  onClearAndScan,
  onRescrape,
}: {
  mode: 'list' | 'detail';
  running: boolean;
  stopping: boolean;
  clearing: boolean;
  queueScanning: boolean;
  queueScanHere: boolean;
  retryingFails: boolean;
  retryingSofts: boolean;
  rescraping: boolean;
  onPause: () => void;
  onClearAndScan: () => void;
  onRescrape: () => void;
}) {
  if (mode === 'detail') {
    return (
      <span className="makers-manage__status-actions">
        <button
          type="button"
          className="makers-manage__probe-btn"
          disabled={rescraping || running}
          onClick={onRescrape}
        >
          {rescraping ? '重刮中…' : '重刮'}
        </button>
      </span>
    );
  }
  return (
    <span className="makers-manage__status-actions">
      {running ? (
        <button
          type="button"
          className="makers-manage__probe-btn"
          disabled={stopping}
          onClick={onPause}
        >
          {stopping ? '处理中' : '暂停'}
        </button>
      ) : null}
      <button
        type="button"
        className="makers-manage__probe-btn makers-manage__probe-btn--danger"
        disabled={clearing || queueScanning || retryingFails || retryingSofts}
        onClick={onClearAndScan}
      >
        {clearing && !queueScanning
          ? '清空中…'
          : queueScanning || queueScanHere
            ? '扫描中…'
            : '清空·扫描'}
      </button>
    </span>
  );
}
