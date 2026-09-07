"""Die of an unhandled SIGALRM while sleeping."""

import signal
import time

signal.setitimer(signal.ITIMER_REAL, 0.01)  # Schedule SIGALRM in 10ms

time.sleep(6)
