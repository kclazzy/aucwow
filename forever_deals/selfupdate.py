"""Самообновление собранного exe: скачать свежий архив из Releases, подготовить новый exe и подменить его после выхода.

Запущенный exe Windows не даёт перезаписать, поэтому новый файл кладётся рядом, а маленький bat-скрипт ждёт завершения
приложения, подменяет файл, запускает новую версию и удаляет сам себя. Данные пользователя (~/.forever_deals) не трогаются."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .updater import REPO, UNKNOWN, UpdateError

TAG = "windows-latest"
ASSET = "ForeverDeals-windows.zip"
EXE = "ForeverDeals.exe"
MIN_EXE_BYTES = 1024            # меньше — явно не exe


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundled_version(base) -> str:
    """Версия (коммит), записанная в exe при сборке."""
    f = Path(base) / "VERSION"
    return f.read_text(encoding="utf-8").strip() if f.exists() else UNKNOWN


def current_version() -> str:
    return bundled_version(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def _get(opener, url: str, token: str = "", accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "aucwow-updater"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with opener(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        hint = " Если репозиторий приватный, укажите github_token в config.json." if exc.code in (401, 403, 404) else ""
        raise UpdateError(f"GitHub ответил HTTP {exc.code}.{hint}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"нет связи с GitHub: {exc.reason}") from exc


def release(opener=urllib.request.urlopen, token: str = "", repo: str = REPO) -> dict:
    data = json.loads(_get(opener, f"https://api.github.com/repos/{repo}/releases/tags/{TAG}", token))
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET), None)
    if not asset:
        raise UpdateError(f"в релизе {TAG} нет файла {ASSET}")
    return {"sha": data.get("target_commitish", UNKNOWN), "asset": asset}


def check(local: str, opener=urllib.request.urlopen, token: str = "", repo: str = REPO):
    """-> (есть_обновление, локальная_версия, версия_релиза)."""
    remote = release(opener, token, repo)["sha"]
    return local != remote, local, remote


def download(opener=urllib.request.urlopen, token: str = "", repo: str = REPO) -> bytes:
    a = release(opener, token, repo)["asset"]
    if token:       # приватный репозиторий: скачивание через API
        return _get(opener, a["url"], token, accept="application/octet-stream")
    return _get(opener, a["browser_download_url"], accept="application/octet-stream")


def stage(zip_bytes: bytes, folder) -> Path:
    """Достаёт из архива только exe и кладёт как ForeverDeals.new.exe. Остальное из архива не берётся."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise UpdateError("скачанный файл не является архивом") from exc
    name = next((i.filename for i in zf.infolist() if i.filename.replace("\\", "/").split("/")[-1] == EXE and not i.is_dir()), None)
    if not name:
        raise UpdateError(f"в архиве нет {EXE}")
    data = zf.read(name)
    if len(data) < MIN_EXE_BYTES:
        raise UpdateError("файл exe в архиве повреждён или пуст")
    out = Path(folder) / "ForeverDeals.new.exe"
    out.write_bytes(data)
    return out


def script(target: str, new: str, pid: int) -> str:
    """Текст bat-скрипта: ждёт завершения процесса, подменяет exe (повторяя, пока файл занят), запускает, удаляется."""
    if any('"' in p or "\n" in p for p in (target, new)):
        raise ValueError("недопустимые символы в пути")
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        "set /a tries=0\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        ":swap\r\n"
        f'move /y "{new}" "{target}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  set /a tries+=1\r\n"
        "  if %tries% GEQ 30 goto fail\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto swap\r\n"
        ")\r\n"
        f'start "" "{target}"\r\n'
        "goto done\r\n"
        ":fail\r\n"
        f'echo Не удалось заменить {target}. Новый файл: {new}\r\n'
        "pause\r\n"
        ":done\r\n"
        'del "%~f0"\r\n'
    )


def clean_env(env: dict) -> dict:
    """Убирает служебные переменные PyInstaller: иначе перезапущенный exe может подхватить временную папку старого процесса."""
    return {k: v for k, v in env.items() if not (k.startswith("_PYI") or k.startswith("_MEIPASS"))}


def launch_swap(new: Path) -> None:
    """Запускает скрипт подмены отдельным процессом. После этого приложение должно завершиться."""
    target = sys.executable
    bat = Path(new).parent / "ForeverDeals-update.bat"
    bat.write_text(script(target, str(new), os.getpid()), encoding="cp866", errors="replace")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True, env=clean_env(dict(os.environ)))
