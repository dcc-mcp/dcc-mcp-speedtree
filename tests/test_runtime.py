from dcc_mcp_speedtree.runtime import RuntimeBinding, SpeedTreeRuntimeError, bind_runtime
class I:
 def process_path(self,pid):
  from pathlib import Path
  return Path("C:/SpeedTree/SpeedTree.exe")
def test_bind_runtime():
 b=bind_runtime(42,99,inspector=I(),version="9.0")
 assert b.pid==42 and b.version=="9.0"
