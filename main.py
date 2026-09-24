"""Start the desktop app after DPI, runtime folders, logging, and replay samples are ready."""
from __future__ import annotations

import ctypes
import logging
from tkinter import messagebox

from app import config
from app.utils.helpers import ensure_directories
from app.utils.logging_config import setup_logging
from app.utils.sample_data import generate_sample_missions


def main() -> None:
    """Prepare the host, then enter Tk's single threaded event loop."""
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        ensure_directories()
        setup_logging()
        logging.info("Starting SomaiyaSat Mission Control")
        if not (config.SAMPLE_MISSION_CSV.exists() and config.STRESSFUL_MISSION_CSV.exists()):
            try:
                generate_sample_missions()
            except Exception:
                logging.exception("Could not generate sample replay missions")
        from app.application import MissionControlApp
        MissionControlApp().mainloop()
    except Exception:
        logging.exception("Fatal startup error")
        messagebox.showerror("SomaiyaSat Mission Control", "The application could not start. See logs/somaiyasat.log for details.")


if __name__ == "__main__":
    main()
