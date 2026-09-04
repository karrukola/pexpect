"""Die of an unhandled SIGALRM while sleeping."""

import signal
import time

signal.alarm(1)  # Schedule SIGALRM in 1s

time.sleep(6)
