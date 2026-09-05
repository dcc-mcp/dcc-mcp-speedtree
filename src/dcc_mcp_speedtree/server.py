"""Composition root for one exact SpeedTree GUI instance."""
from __future__ import annotations
import argparse, os, signal, sys, threading
from pathlib import Path
from typing import Any
from dcc_mcp_core import DccServerOptions, HostExecutionBridge, MinimalModeConfig
from dcc_mcp_core.server_base import DccServerBase
from .__version__ import __version__
from .runtime import RuntimeBinding, bind_runtime, process_path
SERVER_NAME="dcc-mcp-speedtree"; _BUILTIN=Path(__file__).parent/'skills'; _server=None
class SpeedTreeMcpServer(DccServerBase):
    def __init__(self, *, dcc_pid:int, dcc_window_handle:int, executable:str|None=None, dcc_version:str|None=None, binding:RuntimeBinding|None=None, port:int|None=None, **kwargs:Any):
        self.binding=binding or bind_runtime(dcc_pid,dcc_window_handle,executable,dcc_version)
        os.environ.update({"DCC_MCP_SPEEDTREE_PID":str(self.binding.pid),"DCC_MCP_SPEEDTREE_WINDOW_HANDLE":str(self.binding.window_handle),"DCC_MCP_SPEEDTREE_EXECUTABLE":self.binding.executable,"DCC_MCP_SPEEDTREE_VERSION":self.binding.version,"DCC_MCP_UI_CONTROL_PROCESS_ID":str(self.binding.pid),"DCC_MCP_UI_CONTROL_WINDOW_HANDLE":str(self.binding.window_handle)})
        options=DccServerOptions.from_env("SPEEDTREE",_BUILTIN,port=port,server_name=SERVER_NAME,server_version=__version__,adapter_version=__version__,dcc_version=self.binding.version,instance_type="gui",dcc_pid=self.binding.pid,dcc_window_handle=self.binding.window_handle,dcc_window_title=self.binding.title,execution_bridge=HostExecutionBridge(dispatcher=None),**kwargs)
        super().__init__(options=options)
    def register_builtin_actions(self, **kwargs):
        kwargs.setdefault('minimal_mode',MinimalModeConfig(skills=('speedtree-official',),env_var_minimal='DCC_MCP_SPEEDTREE_MINIMAL',env_var_default_tools='DCC_MCP_SPEEDTREE_DEFAULT_TOOLS'))
        return super().register_builtin_actions(**kwargs)
def start_server(**kwargs):
    global _server
    if _server is None:
        _server=SpeedTreeMcpServer(**kwargs); _server.register_builtin_actions(); _server.start()
    return _server
def stop_server():
    global _server
    if _server: _server.stop(); _server=None
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--pid',type=int,required=True); p.add_argument('--window-handle',type=int,required=True); p.add_argument('--executable'); p.add_argument('--version'); p.add_argument('--port',type=int)
    a=p.parse_args(argv); stop=threading.Event(); signal.signal(signal.SIGINT,lambda *_:stop.set());
    s=start_server(dcc_pid=a.pid,dcc_window_handle=a.window_handle,executable=a.executable,dcc_version=a.version,port=a.port)
    try:
        while not stop.wait(1):
            try: process_path(s.binding.pid)
            except Exception: break
    finally: stop_server()
