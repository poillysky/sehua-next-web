/**
 * 首帧前写入 data-shell：宽屏桌面 = preview（模拟 iPhone），
 * 真机 / 窄屏 / standalone = native（全屏）。
 */
export const SHELL_BOOT_SCRIPT = `(function(){try{var d=document.documentElement;var alone=window.matchMedia("(display-mode: standalone)").matches||!!(navigator.standalone);var narrow=window.matchMedia("(max-width: 480px)").matches;var dark=window.matchMedia("(prefers-color-scheme: dark)").matches;d.dataset.shell=(alone||narrow)?"native":"preview";d.dataset.standalone=alone?"1":"0";d.dataset.theme=dark?"dark":"light";d.style.colorScheme=dark?"dark":"light";if(alone){d.style.setProperty("--app-height","100vh");}else{d.style.removeProperty("--app-height");}if(dark){d.style.backgroundColor="#000000";}else{d.style.backgroundColor="#f2f2f7";}}catch(e){document.documentElement.dataset.shell="native";}})();`;
