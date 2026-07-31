import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve()
REPOSITORY_EVENT_TOOL = (
    SCRIPT.parents[3] / "event-tool" if len(SCRIPT.parents) > 3 else None
)
if REPOSITORY_EVENT_TOOL is not None and REPOSITORY_EVENT_TOOL.is_dir():
    sys.path.insert(0, str(REPOSITORY_EVENT_TOOL))
from sqlite_backup import create_verified_backup

db_path = Path(os.environ.get("EVENT_DB_PATH", "/data/event.db"))
lease_path = Path(os.environ.get(
    "EVENT_WRITER_LEASE_PATH", str(db_path.parent / "event-tool.writer-lease")
))
try:
    lease_path.mkdir()
except FileExistsError:
    raise SystemExit(
        f"offline backup refused while writer lease exists: {lease_path}; "
        "use the authenticated maintenance API"
    )

try:
    (lease_path / "owner.json").write_text(
        json.dumps({
            "mode": "offline-backup",
            "pid": os.getpid(),
            "acquired_at": datetime.now(UTC).isoformat(),
        }, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(create_verified_backup(), sort_keys=True))
finally:
    shutil.rmtree(lease_path)
