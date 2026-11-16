"""Own-Python child fixture: spawn a grandchild, then stay alive for N seconds.

argv[1] = work dir; argv[2] = grandchild script; argv[3] = child sleep;
argv[4] = grandchild sleep.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

work = Path(sys.argv[1])
grandchild_script = sys.argv[2]
child_sleep = sys.argv[3]
grandchild_sleep = sys.argv[4]
(work / "child.pid").write_text(str(os.getpid()), encoding="utf-8")
grandchild = subprocess.Popen(
    [sys.executable, grandchild_script, str(work), grandchild_sleep],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
# Record the descendant identity at spawn time; the test must not depend on
# how long the grandchild's own interpreter takes to start under load.
(work / "grandchild.pid").write_text(str(grandchild.pid), encoding="utf-8")
time.sleep(float(child_sleep))
