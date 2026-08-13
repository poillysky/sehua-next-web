/** iOS standalone PWA shell — keep stable; swap features instead. */
export { AppShell } from './AppShell';
export {
  TabProvider,
  useTabNavigation,
  TAB_ROUTES,
  type TabRoute,
} from './TabContext';
export { TabPane } from './TabPane';
export { TabLink } from './TabLink';
export { HapticsProvider, useHaptics } from './HapticsProvider';
