"""Public static file serving that can never return protected directories.

The existing /assets mount serves the whole frontend folder. The Administrator
module lives inside it (frontend/roles/administrator/), so the mount must
refuse every file there; those files are served only by the authorized
/admin routes (app.api.admin_ui).

The check runs AFTER Starlette has resolved the requested path to a real
filesystem path, so it covers '..' segments, percent-encoded and backslash
separators, mixed letter case, Windows short (8.3) names, trailing dots and
alternate data streams. A refused file is reported as an ordinary 404 so its
existence is not revealed.
"""

from __future__ import annotations

import os
from pathlib import Path

from starlette.staticfiles import StaticFiles


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.realpath(path))


class ProtectedStaticFiles(StaticFiles):
    def __init__(self, *args, protected_directories: list[os.PathLike[str] | str], **kwargs):
        if not protected_directories:
            raise ValueError("At least one protected directory is required.")
        self._protected = [Path(d) for d in protected_directories]
        self._protected_norm = [_norm(d) for d in self._protected]
        super().__init__(*args, **kwargs)

    def is_protected(self, full_path: str | os.PathLike[str]) -> bool:
        """True when the path is a protected directory or anything inside one."""
        target = _norm(full_path)
        for root in self._protected_norm:
            if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
                return True
        # Identity check (device + inode) on the path and every ancestor:
        # catches any spelling the OS maps onto the protected directory.
        candidate = Path(full_path)
        for item in (candidate, *candidate.parents):
            for root in self._protected:
                try:
                    if os.path.samefile(item, root):
                        return True
                except OSError:
                    continue
        return False

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        full_path, stat_result = super().lookup_path(path)
        if full_path and self.is_protected(full_path):
            return "", None
        return full_path, stat_result
