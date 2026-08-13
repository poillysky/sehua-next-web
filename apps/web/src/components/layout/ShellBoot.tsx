import { SHELL_BOOT_SCRIPT } from '@/lib/shellBootScript';

/** 须在 head 最前同步执行，首帧前写 data-shell */
export function ShellBoot() {
  return (
    <script
      id="shell-boot"
      dangerouslySetInnerHTML={{ __html: SHELL_BOOT_SCRIPT }}
    />
  );
}
