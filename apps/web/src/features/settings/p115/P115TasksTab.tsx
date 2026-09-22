'use client';

import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  CloudDownload,
  LoaderCircle,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { AppFootnote } from '@/components/ui/AppMsg';
import { cn } from '@/lib/utils';
import {
  TASK_FILTERS,
  formatBytes,
  formatTaskTime,
  taskDisplay,
  taskTone,
} from './format';
import type { P115PanelState } from './useP115Panel';

export function P115TasksTab({ p }: { p: P115PanelState }) {
  const {
    tasksLoaded,
    tasksError,
    tasks,
    tasksLoading,
    locked,
    refreshTasks,
    taskFilter,
    setTaskFilter,
    clearing,
    taskCounts,
    onClear,
    filteredTasks,
    deletingHash,
    onDeleteTask,
  } = p;

  return (
    <div className="p115-console__pane p115-console__pane--tasks">
      <div className="p115-tasks-toolbar">
        <div className="p115-tasks-toolbar__lead">
          <span className="p115-tasks-toolbar__title">云下载队列</span>
          <span className="p115-tasks-toolbar__count allow-select">
            {tasksLoaded && !tasksError
              ? tasks.length > 0
                ? `${tasks.length} 项`
                : '空'
              : tasksLoading
                ? '读取中'
                : '—'}
          </span>
        </div>
        <div className="p115-tasks-toolbar__actions" role="toolbar" aria-label="任务操作">
          <button
            type="button"
            className="p115-tasks-action"
            disabled={tasksLoading || locked}
            onClick={() => void refreshTasks()}
          >
            <RefreshCw
              size={14}
              strokeWidth={2.25}
              className={cn(tasksLoading && 'p115-spin')}
              aria-hidden
            />
            刷新
          </button>
          {taskFilter === 'done' ? (
            <button
              type="button"
              className="p115-tasks-action"
              disabled={
                tasksLoading || locked || clearing === 'done' || taskCounts.done === 0
              }
              onClick={() => void onClear('done')}
            >
              {clearing === 'done' ? '清理中' : '清完成'}
            </button>
          ) : null}
          {taskFilter === 'failed' ? (
            <button
              type="button"
              className="p115-tasks-action p115-tasks-action--warn"
              disabled={
                tasksLoading ||
                locked ||
                clearing === 'failed' ||
                taskCounts.failed === 0
              }
              onClick={() => void onClear('failed')}
            >
              {clearing === 'failed' ? '清理中' : '清失败'}
            </button>
          ) : null}
        </div>
      </div>

      <div className="app-seg p115-tasks-filter" role="tablist" aria-label="任务状态">
        {TASK_FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            role="tab"
            aria-selected={taskFilter === f.key}
            className={cn(
              'app-seg__btn',
              taskFilter === f.key && 'app-seg__btn--active',
            )}
            onClick={() => setTaskFilter(f.key)}
          >
            {f.label}
            <span className="p115-tasks-filter__n allow-select">
              {tasksLoaded && !tasksError ? taskCounts[f.key] : '—'}
            </span>
          </button>
        ))}
      </div>

      {tasksError ? (
        <div className="p115-tasks-empty p115-tasks-empty--err">
          <p>{tasksError}</p>
          <button
            type="button"
            className="p115-tasks-empty__link"
            onClick={() => void refreshTasks()}
          >
            重试
          </button>
        </div>
      ) : tasksLoading && !tasksLoaded ? (
        <div className="p115-tasks-empty" aria-busy="true">
          <p>加载任务中…</p>
        </div>
      ) : tasks.length === 0 ? (
        <div className="p115-tasks-empty">
          <span className="p115-tasks-empty__icon" aria-hidden>
            <CloudDownload size={22} strokeWidth={1.75} />
          </span>
          <p>暂无离线任务</p>
          <span>转存后会出现在这里；额度紧时清理已完成或失败项即可腾出队列。</span>
        </div>
      ) : filteredTasks.length === 0 ? (
        <div className="p115-tasks-empty">
          <p>
            {taskFilter === 'run'
              ? '没有下载中的任务'
              : taskFilter === 'failed'
                ? '没有失败任务'
                : '没有已完成任务'}
          </p>
          <span>
            {taskFilter === 'run'
              ? '排队或进行中的任务会显示在这里。'
              : taskFilter === 'failed'
                ? '失败记录可一键清理，腾出额度。'
                : '完成后可清理记录，网盘文件不受影响。'}
          </span>
        </div>
      ) : (
        <ul className="p115-tasks" aria-label="离线任务列表">
          {filteredTasks.map((t, idx) => {
            const tone = taskTone(t.status);
            const show = taskDisplay(t);
            const timeText = formatTaskTime(t.updateTime || t.addTime);
            const sizeText = formatBytes(t.size);
            const hash = String(t.infoHash || '').trim();
            const deleting = Boolean(hash) && deletingHash === hash;
            return (
              <li
                key={`${hash || t.name}-${idx}`}
                className={cn(
                  'p115-task',
                  `p115-task--${tone}`,
                  deleting && 'is-deleting',
                )}
              >
                <span className={cn('p115-task__mark', `is-${tone}`)} aria-hidden>
                  {tone === 'ok' ? (
                    <CheckCircle2 size={15} strokeWidth={2.1} />
                  ) : tone === 'warn' ? (
                    <AlertCircle size={15} strokeWidth={2.1} />
                  ) : tone === 'run' ? (
                    <LoaderCircle
                      size={15}
                      strokeWidth={2.1}
                      className="p115-spin"
                    />
                  ) : (
                    <Clock3 size={15} strokeWidth={2.1} />
                  )}
                </span>
                <div className="p115-task__body">
                  <p className="p115-task__name allow-select">{show.title}</p>
                  {timeText ? (
                    <p className="p115-task__line allow-select">{timeText}</p>
                  ) : null}
                  {sizeText ? (
                    <p className="p115-task__line allow-select">{sizeText}</p>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="p115-task__del"
                  aria-label={`删除${show.title}`}
                  title={hash ? '删除这条任务，不删网盘文件' : '缺少 infoHash，无法删除'}
                  disabled={locked || !hash}
                  onClick={() => void onDeleteTask(t)}
                >
                  {deleting ? (
                    <LoaderCircle size={14} strokeWidth={2.25} className="p115-spin" aria-hidden />
                  ) : (
                    <Trash2 size={14} strokeWidth={2.25} aria-hidden />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <AppFootnote>删除和清理只移除云下载队列记录，不会删除已转存到网盘的文件。</AppFootnote>
    </div>
  );
}
