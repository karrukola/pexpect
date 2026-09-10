"""Sleep for the number of seconds given as the only argument. Stand-in for `sleep`."""

import sys
import time

time.sleep(float(sys.argv[1]))
