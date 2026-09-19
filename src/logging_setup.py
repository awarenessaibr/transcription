import logging
import os


def setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    # Silence noisy libs unless explicitly DEBUG_LIBS=1
    if not os.getenv("DEBUG_LIBS"):
        for noisy in [
            "multipart.multipart",
            "numba.core.byteflow",
            "numba.core.interpreter",
            "numba.core.ssa",
            "numba.core.ir",
            "urllib3.connectionpool",  # keep at INFO if you want network timing
        ]:
            logging.getLogger(noisy).setLevel(logging.WARNING)
    # Optional: quiet tqdm progress bar
    os.environ.setdefault("TQDM_DISABLE", "1")
