"""
🔬 科研智能体 — 一键启动脚本

使用方式：
    python start.py                        # 本地启动（自动构建前端）
    python start.py --tunnel               # 本地 + ngrok 公网穿透
    python start.py --tunnel --token XXX   # 指定 ngrok token
    python start.py --port 9000            # 自定义端口
    python start.py --skip-build           # 跳过前端构建
    python start.py --dev                  # 开发模式（后端 reload + 提示前端 dev）

流程：
    1. 检测并构建 React 前端（npm run build）
    2. 启动 FastAPI 后端（uvicorn）
    3. [可选] 启动 ngrok 公网穿透
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT, "Futuristic AI Chat Interface")
DIST_DIR = os.path.join(FRONTEND_DIR, "dist")
DIST_INDEX = os.path.join(DIST_DIR, "index.html")


# ── 工具函数 ──────────────────────────────────────────────────

def log(icon: str, msg: str):
    print(f"  {icon}  {msg}")


def check_node():
    """检查 Node.js 是否可用"""
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, text=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def check_npm_installed():
    """检查前端依赖是否已安装"""
    return os.path.isdir(os.path.join(FRONTEND_DIR, "node_modules"))


def install_frontend_deps():
    """安装前端 npm 依赖"""
    log("📦", "安装前端依赖 (npm install)...")
    r = subprocess.run(
        ["npm", "install"],
        cwd=FRONTEND_DIR,
        shell=True,
    )
    if r.returncode != 0:
        log("❌", "npm install 失败")
        sys.exit(1)
    log("✅", "前端依赖安装完成")


def build_frontend():
    """构建 React 前端"""
    log("🔨", "构建前端 (npm run build)...")
    r = subprocess.run(
        ["npm", "run", "build"],
        cwd=FRONTEND_DIR,
        shell=True,
    )
    if r.returncode != 0:
        log("❌", "前端构建失败")
        sys.exit(1)
    log("✅", "前端构建完成")


def start_server(port: int, reload: bool = False):
    """启动 uvicorn 后端"""
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
        log_level="info",
    )


def start_tunnel(port: int, token: str = ""):
    """启动 ngrok 公网穿透"""
    ngrok_bin = _find_system_ngrok()

    if not ngrok_bin:
        log("⚠️", "未找到 ngrok，请先安装：")
        print("    choco install ngrok  或  scoop install ngrok")
        print("    或从 https://ngrok.com/download 下载")
        return None

    log("✅", f"使用 ngrok: {ngrok_bin}")

    if token:
        log("🔑", "设置 ngrok authtoken...")
        subprocess.run([ngrok_bin, "config", "add-authtoken", token], check=False)

    log("🌐", "正在建立公网隧道...")
    try:
        # 在后台启动 ngrok（Windows 用 start /B）
        ngrok_cmd = f'start /B "" "{ngrok_bin}" http {port}'
        os.system(ngrok_cmd)

        # 等 ngrok 启动，然后通过本地 API (4040) 获取公网 URL
        import urllib.request
        import json as _json
        public_url = None
        for attempt in range(20):  # 最多等 20 秒
            time.sleep(1)
            try:
                req = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2)
                data = _json.loads(req.read().decode())
                tunnels = data.get("tunnels", [])
                for t in tunnels:
                    url = t.get("public_url", "")
                    if url.startswith("https://"):
                        public_url = url
                        break
                if public_url:
                    break
            except Exception:
                continue

        if public_url:
            print()
            print("=" * 60)
            log("✅", f"公网地址: {public_url}")
            log("📱", f"本地地址: http://127.0.0.1:{port}")
            log("🔗", "分享公网地址即可让他人访问")
            print("=" * 60)
            return public_url
        else:
            log("⚠️", "未能获取公网地址，ngrok 可能需要 authtoken")
            print("    运行: ngrok config add-authtoken YOUR_TOKEN")
            return None
    except Exception as e:
        log("⚠️", f"ngrok 穿透失败: {e}")
        return None


def _find_system_ngrok() -> str | None:
    """查找系统已安装的 ngrok 可执行文件"""
    import shutil
    path = shutil.which("ngrok")
    if path:
        return path
    # Windows 常见安装位置
    candidates = [
        os.path.expanduser("~\\AppData\\Local\\ngrok\\ngrok.exe"),
        os.path.expanduser("~\\.ngrok2\\ngrok.exe"),
        "C:\\ngrok\\ngrok.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# ── 主流程 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="🔬 科研智能体 — 一键启动")
    parser.add_argument("--port", type=int, default=8000, help="服务端口（默认 8000）")
    parser.add_argument("--tunnel", action="store_true", help="启用 ngrok 公网穿透")
    parser.add_argument("--token", type=str, default="", help="ngrok authtoken")
    parser.add_argument("--skip-build", action="store_true", help="跳过前端构建")
    parser.add_argument("--dev", action="store_true", help="开发模式（后端 reload）")
    args = parser.parse_args()

    print()
    print("  🔬  科研智能体 — 一键启动")
    print("  " + "─" * 40)
    print()

    # ── Step 1: 前端构建 ──────────────────────────────────────
    if args.dev:
        log("💡", "开发模式：跳过前端构建")
        log("💡", "请在另一个终端运行前端 dev server：")
        print(f'       cd "Futuristic AI Chat Interface" && npm run dev')
        print()
    elif args.skip_build:
        log("⏭️", "跳过前端构建")
    elif os.path.isfile(DIST_INDEX):
        log("✅", "前端已构建，跳过（使用 --skip-build=false 强制重建）")
    else:
        if not check_node():
            log("⚠️", "未检测到 Node.js，跳过前端构建")
            log("💡", "前端将使用旧版 HTML（如果存在）")
        else:
            if not check_npm_installed():
                install_frontend_deps()
            build_frontend()

    # ── Step 2: 启动后端 ──────────────────────────────────────
    if args.tunnel:
        # 穿透模式：后台启动后端，前台启动 ngrok
        log("🚀", f"启动后端服务 http://0.0.0.0:{args.port}")
        server_thread = threading.Thread(
            target=start_server,
            args=(args.port, args.dev),
            daemon=True,
        )
        server_thread.start()
        time.sleep(2)  # 等后端启动

        # ── Step 3: 启动穿透 ─────────────────────────────────
        start_tunnel(args.port, args.token)

        print(f"\n  按 Ctrl+C 停止服务\n")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            log("⏹", "正在关闭...")
    else:
        # 普通模式：直接前台启动后端
        print()
        log("🚀", f"启动服务 http://127.0.0.1:{args.port}")
        log("📱", f"浏览器打开 http://localhost:{args.port}")
        print()
        start_server(args.port, reload=args.dev)


if __name__ == "__main__":
    main()
