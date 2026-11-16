"""Own-Python grandchild fixture: record pid, then stay alive for N seconds.

argv[1] = work dir; argv[2] = seconds to sleep.
"""

import os
import sys
import time
from pathlib import Path

work = Path(sys.argv[1])
(work / "grandchild.pid").write_text(str(os.getpid()), encoding="utf-8")
time.sleep(float(sys.argv[2]))
