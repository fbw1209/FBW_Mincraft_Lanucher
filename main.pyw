from __future__ import annotations

import sys
import traceback
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from launcher.ui.theme import set_dpi_awareness

set_dpi_awareness()


def main() -> None:
    try:
        from launcher.ui.app import run

        run()
    except Exception:
        detail = traceback.format_exc()
        try:
            log_dir = PROJECT_DIR / "data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "crash.log").write_text(detail, encoding="utf-8")
        except Exception:
            pass
        try:
            import tkinter.messagebox

            tkinter.messagebox.showerror("FML 启动失败", detail)
        except Exception:
            pass


if __name__ == "__main__":
    main()
