import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server
code = '''
import importlib, gc, sys
import krita_mcp.bridge as b
importlib.reload(b)
n = 0
for o in gc.get_objects():
    if type(o).__name__ == "Bridge" and hasattr(o, "cmds"):
        o.cmds = b.Commands(); n += 1
result = n
'''
print("reloaded bridges:", server.call("execute_python", code=code)["result"])
