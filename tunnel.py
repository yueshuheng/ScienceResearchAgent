"""
公网穿透启动脚本（兼容旧版）

推荐使用新的一键启动脚本：
    python start.py --tunnel
    python start.py --tunnel --token YOUR_NGROK_TOKEN

此脚本保留向后兼容。
"""

import sys
import os

# 转发到 start.py --tunnel
if __name__ == "__main__":
    args = ["--tunnel"]
    # 转换旧参数
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--port" and i < len(sys.argv):
            args.extend(["--port", sys.argv[i + 1]])
        elif a == "--token" and i < len(sys.argv):
            args.extend(["--token", sys.argv[i + 1]])
        elif a.startswith("--port="):
            args.append(a)
        elif a.startswith("--token="):
            args.append(a)

    os.execv(sys.executable, [sys.executable, os.path.join(os.path.dirname(__file__), "start.py")] + args)
