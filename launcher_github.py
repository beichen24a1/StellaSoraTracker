import os
from stellasora_toolkit.project import UPDATE_MANIFEST_URL

os.environ.setdefault(
    "STELLASORA_UPDATE_MANIFEST_GITHUB",
    UPDATE_MANIFEST_URL,
)

from stellasora_toolkit.desktop_launcher import main


if __name__ == "__main__":
    raise SystemExit(main())
