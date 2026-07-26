"""Make a published file's directory entry durable, not just its contents.

`os.fsync` on a file descriptor persists that file's data. It does not persist
the *directory entry* that makes the file findable: that entry lives in the
parent directory and stays in the page cache until the directory itself is
synced. Every Minerva publication point creates a new name — `os.link` for a
staged database, `O_EXCL` creation for an exported artifact — so without this a
crash immediately after an operation reported success can leave a recorded audit
row pointing at a file that no longer exists.

What this does not promise: nothing here covers a crash inside SQLite's own
write path, which is SQLite's contract via `synchronous = FULL`, nor does it
make a multi-file export atomic. It closes exactly one gap — the window between
"the name exists in the page cache" and "the name survives power loss".
"""

from __future__ import annotations

import os
from pathlib import Path


def fsync_directory(path: Path) -> None:
    """Persist the directory entries of *path*'s parent.

    Call this after publishing into that directory and before recording that the
    publication happened, so a durable audit row never outlives the artifact it
    describes.
    """

    descriptor = os.open(path.parent, os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
