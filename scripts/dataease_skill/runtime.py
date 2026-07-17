from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 20) -> tuple[int, str]:
    try:
        process = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return process.returncode, (process.stdout or process.stderr).strip()


def _package_version(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = value.get("version") if isinstance(value, dict) else None
    return str(version) if version else None


def runtime_diagnostics(skill_root: Path) -> dict[str, Any]:
    root = Path(skill_root).resolve()
    recommendations: list[str] = []
    warnings: list[str] = []
    node = shutil.which("node")
    npm = shutil.which("npm")
    node_version = None
    if node:
        code, output = _run([node, "--version"])
        node_version = output if code == 0 else None
    playwright_manifest = root / "node_modules" / "playwright" / "package.json"
    playwright_version = _package_version(playwright_manifest)
    browser_path = None
    browser_exists = False
    browser_error = None
    if node and playwright_version:
        code, output = _run(
            [
                node,
                "-e",
                "const {chromium}=require('playwright');process.stdout.write(chromium.executablePath())",
            ],
            cwd=root,
        )
        if code == 0 and output:
            browser_path = output
            browser_exists = Path(output).exists()
        else:
            browser_error = output or "无法解析 Chromium 路径"

    missing_libraries: list[str] = []
    if sys.platform.startswith("linux") and browser_exists and shutil.which("ldd"):
        code, output = _run(["ldd", str(browser_path)])
        if code in {0, 1}:
            missing_libraries = sorted(
                {
                    line.split("=>", 1)[0].strip()
                    for line in output.splitlines()
                    if "not found" in line and "=>" in line
                }
            )

    if not node:
        recommendations.append("安装 Node.js 后再启用截图/PDF；纯 API 操作不需要 Node.js。")
    if not npm:
        recommendations.append("安装 npm，或使用包含 npm 的 Node.js 发行版。")
    if node and not playwright_version:
        recommendations.append("在 Skill 根目录运行 npm install。")
    if playwright_version and not browser_exists:
        recommendations.append("在 Skill 根目录运行 npx playwright install chromium。")
    if missing_libraries:
        recommendations.append("安装 Chromium 缺失的 Linux 动态库；Debian/Ubuntu 可运行 npx playwright install --with-deps chromium。")
    python_playwright = importlib.util.find_spec("playwright") is not None
    if python_playwright:
        warnings.append("检测到 Python Playwright，但本 Skill 截图只使用 Node Playwright；无需为 Python Playwright 再安装一份 Chromium。")
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        recommendations.append("建议使用 python -m venv .venv，避免依赖系统 pip 或 --break-system-packages。")

    capture_ready = bool(node and npm and playwright_version and browser_exists and not missing_libraries)
    return {
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "virtual_environment": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
            "python_playwright_detected": python_playwright,
        },
        "capture": {
            "engine": "node-playwright",
            "ready": capture_ready,
            "node": node,
            "node_version": node_version,
            "npm": npm,
            "playwright_version": playwright_version,
            "chromium_path": browser_path,
            "chromium_exists": browser_exists,
            "browser_error": browser_error,
            "missing_libraries": missing_libraries,
        },
        "warnings": warnings,
        "recommendations": recommendations,
    }
