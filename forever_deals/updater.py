"""Обновление приложения с GitHub (kclazzy/aucwow): сравнить коммит, скачать архив ветки, заменить файлы кода.

Данные пользователя лежат в ~/.forever_deals и не затрагиваются. Работает при запуске из исходников."""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO, BRANCH = "kclazzy/aucwow", "main"
SKIP_TOP = {".git", "reports"}          # из архива не берём
UNKNOWN = "unknown"


class UpdateError(Exception):
    pass


def supported() -> bool:
    """Обновление кода возможно только при запуске из исходников (не из собранного exe)."""
    return not getattr(sys, "frozen", False)


def local_version(app_dir) -> str:
    f = Path(app_dir) / "VERSION"
    return f.read_text(encoding="utf-8").strip() if f.exists() else UNKNOWN


def _get(opener, url: str, token: str = "") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "aucwow-updater"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with opener(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        hint = " Если репозиторий приватный, укажите github_token в config.json." if exc.code in (401, 403, 404) else ""
        raise UpdateError(f"GitHub ответил HTTP {exc.code}.{hint}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"нет связи с GitHub: {exc.reason}") from exc


def latest_sha(opener=urllib.request.urlopen, token="", repo=REPO, branch=BRANCH) -> str:
    data = json.loads(_get(opener, f"https://api.github.com/repos/{repo}/commits/{branch}", token))
    return data["sha"]


def check(app_dir, opener=urllib.request.urlopen, token="", repo=REPO, branch=BRANCH):
    """-> (есть_обновление, локальная_версия, версия_на_GitHub)."""
    remote = latest_sha(opener, token, repo, branch)
    local = local_version(app_dir)
    return local != remote, local, remote


def _members(zf: zipfile.ZipFile):
    """[(относительный путь без верхней папки, имя в архиве)]; любой подозрительный путь отклоняет весь архив."""
    out = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = PurePosixPath(info.filename).parts
        if len(parts) < 2:
            continue
        rel = parts[1:]
        if ".." in rel or PurePosixPath(info.filename).is_absolute() or any(":" in p or "\\" in p for p in rel):
            raise UpdateError(f"в архиве недопустимый путь: {info.filename}")
        if rel[0] in SKIP_TOP:
            continue
        out.append(("/".join(rel), info.filename))
    return out


def apply_zip(data: bytes, app_dir, sha: str) -> list:
    """Раскладывает архив в app_dir. Сначала проверяет весь архив, потом пишет только изменившиеся файлы. -> изменённые."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UpdateError("скачанный файл не является архивом") from exc
    root = Path(app_dir).resolve()
    members = _members(zf)
    changed = []
    for rel, name in members:
        target = (root / rel).resolve()
        if root not in target.parents:
            raise UpdateError(f"в архиве недопустимый путь: {rel}")
        content = zf.read(name)
        if target.exists() and target.read_bytes() == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        changed.append(rel)
    (root / "VERSION").write_text(sha + "\n", encoding="utf-8")
    return sorted(changed)


def update(app_dir, opener=urllib.request.urlopen, token="", repo=REPO, branch=BRANCH) -> list:
    sha = latest_sha(opener, token, repo, branch)
    data = _get(opener, f"https://api.github.com/repos/{repo}/zipball/{sha}", token)
    return apply_zip(data, app_dir, sha)
