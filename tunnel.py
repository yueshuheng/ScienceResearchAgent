"""
一键启动：uvicorn 服务 + ngrok 公网穿透

使用方式：
    python tunnel.py
    python tunnel.py --port 8000
    python tunnel.py --token YOUR_NGROK_TOKEN  (可选，免费账号需要)

首次运行会自动下载 ngrok。
免费账号注册：https://dashboard.ngrok.com/signup
"""

import argparse
import threading
import time
import uvicorn
from pyngrok import ngrok, conf


def start_server(port: int):
    """启动 uvicorn"""
    uvicorn.run("server:app", host="127.0.0.1", port=port, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="启动科研智能体 + 公网穿透")
    parser.add_argument("--port", type=int, default=8000, help="本地端口（默认 8000）")
    parser.add_argument("--token", type=str, default="", help="ngrok authtoken（可选）")
    args = parser.parse_args()

    # 设置 ngrok token（如果提供）
    if args.token:
        ngrok.set_auth_token(args.token)

    # 后台启动 uvicorn
    print(f"🚀 启动本地服务 http://127.0.0.1:{args.port}")
    server_thread = threading.Thread(target=start_server, args=(args.port,), daemon=True)
    server_thread.start()
    time.sleep(2)  # 等服务启动

    # 启动 ngrok 穿透
    print("🌐 正在建立公网隧道...")
    try:
        tunnel = ngrok.connect(args.port, "http")
        public_url = tunnel.public_url
        print()
        print("=" * 60)
        print(f"  ✅ 公网地址: {public_url}")
        print(f"  📱 本地地址: http://127.0.0.1:{args.port}")
        print(f"  🔗 分享公网地址即可让他人访问")
        print("=" * 60)
        print("\n按 Ctrl+C 停止服务\n")

        # 保持运行
        server_thread.join()
    except KeyboardInterrupt:
        print("\n⏹ 正在关闭...")
        ngrok.kill()
    except Exception as e:
        print(f"\n⚠️ ngrok 穿透失败: {e}")
        print(f"本地服务仍在运行: http://127.0.0.1:{args.port}")
        print("\n可能需要注册 ngrok 免费账号获取 token:")
        print("  1. 访问 https://dashboard.ngrok.com/signup")
        print("  2. 获取 authtoken")
        print(f"  3. 运行: python tunnel.py --token YOUR_TOKEN")
        print("\n按 Ctrl+C 停止服务\n")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
