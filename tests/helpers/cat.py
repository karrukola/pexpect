"""Copy stdin to stdout, a line at a time, until end of file.

`cat` is what most of this suite drives and Windows has no such program. Line
at a time rather than in blocks, because the tests expect a line to come back
as soon as it is sent.
"""

import sys

for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
