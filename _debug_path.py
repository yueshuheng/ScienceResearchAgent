import os
# Simulate what server.py does
REACT_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Futuristic AI Chat Interface", "dist")
index = os.path.join(REACT_DIST, "index.html")
print(f"REACT_DIST = {REACT_DIST}")
print(f"index.html exists = {os.path.isfile(index)}")
print(f"dist dir exists = {os.path.isdir(REACT_DIST)}")
# Also check what __file__ gives in server.py context
print(f"__file__ dir = {os.path.dirname(os.path.abspath(__file__))}")
print(f"CWD = {os.getcwd()}")
