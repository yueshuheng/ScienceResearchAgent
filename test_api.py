"""
API 集成测试 — 模拟前端完整流程
测试：注册 → 登录 → 开始研究 → SSE 流式接收 → 确认继续
"""

import os
os.environ["MOONSHOT_API_KEY"] = os.getenv("MOONSHOT_API_KEY", "")
os.environ["MOONSHOT_API_BASE"] = os.getenv("MOONSHOT_API_BASE", "")

import requests
import json
import time
import threading

BASE = "http://127.0.0.1:8001"


def test_full_flow():
    print("=" * 60)
    print("  API 集成测试")
    print("=" * 60)

    # 1. 注册
    print("\n[1] 注册用户...")
    r = requests.post(f"{BASE}/api/auth/register", json={
        "username": f"test_{int(time.time())}",
        "password": "test123",
        "display_name": "测试用户",
    })
    if r.status_code == 400 and "已存在" in r.text:
        print("  用户已存在，尝试登录")
        r = requests.post(f"{BASE}/api/auth/login", json={
            "username": "testuser", "password": "test123",
        })
    assert r.status_code == 200, f"注册/登录失败: {r.status_code} {r.text}"
    data = r.json()
    token = data["token"]
    user = data["user"]
    print(f"  ✅ 用户: {user['display_name']} (id={user['id']})")

    headers = {"Authorization": f"Bearer {token}"}

    # 2. 获取用户信息
    print("\n[2] 验证 Token...")
    r = requests.get(f"{BASE}/api/auth/me", headers=headers)
    assert r.status_code == 200
    print(f"  ✅ Token 有效")

    # 3. 开始研究
    print("\n[3] 开始研究...")
    r = requests.post(f"{BASE}/api/start", headers=headers, json={
        "topic": "深度学习在自然语言处理中的应用",
    })
    assert r.status_code == 200
    sid = r.json()["session_id"]
    print(f"  ✅ 会话创建: {sid}")

    # 4. 连接 SSE 流
    print("\n[4] 连接 SSE 流式输出...")
    token_count = 0
    events_received = []
    final_status = None

    try:
        r = requests.get(f"{BASE}/api/stream?session_id={sid}",
                         headers=headers, stream=True, timeout=180)
        current_event = ""
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                raw = line[6:]
                events_received.append(current_event)

                if current_event == "token":
                    token_count += 1
                    if token_count <= 3:
                        text = raw.replace("\\n", "\n")
                        print(f"  📝 token #{token_count}: {text[:50]}...")
                    elif token_count == 4:
                        print(f"  📝 ... (继续接收中)")

                elif current_event == "stage_start":
                    d = json.loads(raw.replace("\\n", "\n"))
                    print(f"  🚀 阶段开始: {d.get('agent', '')} ({d.get('stage', '')})")

                elif current_event == "info":
                    d = json.loads(raw.replace("\\n", "\n"))
                    print(f"  ℹ️  {d.get('message', '')}")

                elif current_event == "stage_done":
                    d = json.loads(raw.replace("\\n", "\n"))
                    final_status = d.get("status")
                    print(f"  ✅ 阶段完成: stage={d.get('stage', '')} status={final_status}")
                    break

                elif current_event == "error":
                    d = json.loads(raw.replace("\\n", "\n"))
                    print(f"  ❌ 错误: {d.get('message', '')}")
                    break

                elif current_event == "end":
                    print(f"  🏁 SSE 流结束")
                    break

                current_event = ""

    except requests.exceptions.Timeout:
        print("  ⏰ SSE 超时（180s）")

    print(f"\n  收到 {token_count} 个 token，{len(events_received)} 个事件")
    print(f"  事件类型: {list(set(events_received))}")

    # 5. 检查状态
    print("\n[5] 检查会话状态...")
    r = requests.get(f"{BASE}/api/status?session_id={sid}", headers=headers)
    assert r.status_code == 200
    status = r.json()
    print(f"  状态: {status['status']}")
    print(f"  当前阶段: {status['current_stage']}")
    print(f"  消息数: {len(status['messages'])}")

    if status["status"] == "waiting":
        print(f"\n  ✅✅✅ 测试通过！前端应该显示确认按钮了")

        # 6. 测试继续
        print("\n[6] 测试确认继续...")
        r = requests.post(f"{BASE}/api/continue", headers=headers, json={
            "session_id": sid,
            "feedback": "",
        })
        assert r.status_code == 200
        print(f"  ✅ 继续请求成功: {r.json()}")
    else:
        print(f"\n  ⚠️ 状态不是 waiting，可能还在运行或出错")

    # 7. 会话列表
    print("\n[7] 会话列表...")
    r = requests.get(f"{BASE}/api/sessions", headers=headers)
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    print(f"  ✅ 共 {len(sessions)} 个会话")

    print("\n" + "=" * 60)
    print("  测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    test_full_flow()
