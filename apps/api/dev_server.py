"""Windows 可靠的 API 热重载。

uvicorn 自带 `--reload` 在 Windows 上用 CTRL_C_EVENT + process.join()，
子进程里只要有 ThreadPoolExecutor / 刮削线程未退干净就会永远卡住，
表现为：日志停在 Reloading / Waiting for application startup，8020 假活。

本脚本：无 reload 跑 uvicorn；watchfiles 侦测 app/*.py 后硬杀再拉起。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"
PORT = str(os.environ.get("API_PORT") or "8020")
HOST = str(os.environ.get("API_HOST") or "0.0.0.0")
RELOAD = str(os.environ.get("API_RELOAD") or "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
# 优雅退出等待；超时后 taskkill /F
GRACE_SEC = float(os.environ.get("API_RELOAD_GRACE_SEC") or "4")


def _python() -> str:
    win = ROOT / ".venv" / "Scripts" / "python.exe"
    unix = ROOT / ".venv" / "bin" / "python"
    if win.is_file():
        return str(win)
    if unix.is_file():
        return str(unix)
    return sys.executable


def _uvicorn_cmd() -> list[str]:
    return [
        _python(),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        PORT,
        "--timeout-graceful-shutdown",
        "3",
    ]


def _popen() -> subprocess.Popen[bytes]:
    kw: dict = {
        "cwd": str(ROOT),
        "env": {**os.environ, "PYTHONUNBUFFERED": "1"},
    }
    if sys.platform == "win32":
        # 独立进程组，便于 CTRL_BREAK / taskkill 树杀，且不伤父终端
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(_uvicorn_cmd(), **kw)


def _kill(proc: subprocess.Popen[bytes], *, grace: float = GRACE_SEC) -> None:
    """优先优雅退出；超时则整树强杀（Windows 热重载关键）。"""
    if proc.poll() is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        # 先试 CTRL_BREAK（独立进程组），给 lifespan 清锁的机会
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            proc.wait(timeout=min(grace, 2.0))
            return
        except subprocess.TimeoutExpired:
            pass
        # 彻底解决：强杀整棵树，避免 join 永久挂起
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
        return

    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def main() -> int:
    os.chdir(ROOT)
    if not RELOAD:
        print(f"[dev_server] noreload → uvicorn :{PORT}", flush=True)
        return subprocess.call(_uvicorn_cmd(), cwd=str(ROOT))

    try:
        from watchfiles import watch
        from watchfiles.filters import PythonFilter
    except ImportError:
        print(
            "[dev_server] watchfiles 不可用，回退 uvicorn --reload",
            flush=True,
        )
        cmd = _uvicorn_cmd() + [
            "--reload",
            "--reload-dir",
            str(APP_DIR),
            "--reload-exclude",
            ".venv",
            "--reload-exclude",
            "__pycache__",
        ]
        return subprocess.call(cmd, cwd=str(ROOT))

    print(
        f"[dev_server] watching {APP_DIR} → uvicorn :{PORT} (hard-reload)",
        flush=True,
    )
    proc = _popen()
    try:
        for changes in watch(
            APP_DIR,
            watch_filter=PythonFilter(),
            debounce=800,
            step=200,
            ignore_permission_denied=True,
        ):
            paths = sorted({Path(p).name for _, p in changes})
            print(
                f"[dev_server] reload ({', '.join(paths[:6])}"
                f"{'…' if len(paths) > 6 else ''})",
                flush=True,
            )
            _kill(proc)
            # 稍等端口释放，避免 WinError 10048
            time.sleep(0.4)
            proc = _popen()
    except KeyboardInterrupt:
        print("\n[dev_server] stop", flush=True)
    finally:
        _kill(proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
