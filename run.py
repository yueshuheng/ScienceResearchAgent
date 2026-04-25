"""
科研智能体运行入口

使用方式：
    python run.py              # 新建研究会话
    python run.py --resume     # 恢复上次中断的会话
    python run.py --session ID # 指定会话 ID

流程：
    1. 输入研究课题
    2. 每个阶段完成后展示结果
    3. 用户可选择：继续 / 补充信息后继续 / 终止
    4. 进度自动保存到 checkpoints.db，随时可恢复
"""

import argparse
from research_agent.main import create_app, STAGE_NAMES

# 阶段 → 对应的输出字段
STAGE_OUTPUT_KEY = {
    "literature_review": "literature_review",
    "hypothesis": "hypothesis",
    "experiment_design": "experiment_design",
    "experiment": "experiment_code",
    "analysis": "analysis_result",
    "paper": "paper_draft",
}

# 阶段顺序
STAGE_ORDER = ["literature_review", "hypothesis", "experiment_design", "experiment", "analysis", "paper"]

# interrupt 节点 → 刚完成的阶段索引
INTERRUPT_TO_STAGE_IDX = {
    "human_after_literature": 0,
    "human_after_hypothesis": 1,
    "human_after_design": 2,
    "human_after_experiment": 3,
    "human_after_analysis": 4,
}


def print_divider(title: str = ""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")


def get_stage_output(state: dict, stage: str) -> str:
    key = STAGE_OUTPUT_KEY.get(stage, "")
    return state.get(key, "（暂无输出）")


def ask_user_confirmation(stage_name: str) -> tuple[bool, str]:
    print(f"\n{stage_name} 已完成！")
    print("-" * 40)
    print("请选择：")
    print("  [1] 确认，继续下一步")
    print("  [2] 补充信息后继续下一步")
    print("  [3] 终止流程（进度已保存，可用 --resume 恢复）")
    print("-" * 40)

    while True:
        choice = input("请输入选项 (1/2/3): ").strip()
        if choice == "1":
            return True, ""
        elif choice == "2":
            feedback = input("请输入补充信息：").strip()
            return True, feedback
        elif choice == "3":
            return False, ""
        else:
            print("无效输入，请重新选择。")


def run_new_session(graph, session_id: str):
    """启动新的研究会话"""
    topic = input("请输入你的研究课题：").strip()
    if not topic:
        print("课题不能为空，退出。")
        return

    config = {"configurable": {"thread_id": session_id}}
    initial_state = {
        "topic": topic,
        "literature_review": "",
        "hypothesis": "",
        "experiment_design": "",
        "experiment_code": "",
        "analysis_result": "",
        "paper_draft": "",
        "messages": [],
        "human_feedback": "",
        "current_stage": "",
        "session_id": "",
        "user_id": 0,
        "memory_context": "",
    }

    print_divider("🚀 开始科研流程")
    print(f"研究课题：{topic}")
    print(f"会话 ID：{session_id}（可用 --session {session_id} 恢复）\n")

    result = None
    for event in graph.stream(initial_state, config, stream_mode="values"):
        result = event

    run_interrupt_loop(graph, config, result)


def run_interrupt_loop(graph, config: dict, result: dict | None):
    """处理 interrupt 循环，直到流程结束或用户终止"""
    while True:
        snapshot = graph.get_state(config)

        # 如果没有下一个节点，说明流程已结束
        if not snapshot.next:
            # 输出最后阶段（论文）
            if result:
                paper_output = get_stage_output(result, "paper")
                if paper_output and paper_output != "（暂无输出）":
                    print_divider(STAGE_NAMES["paper"])
                    print(paper_output)
            print_divider("✅ 科研流程全部完成！")
            print("论文初稿已生成，你可以在此基础上进一步修改完善。")
            return

        # 找到当前暂停的 interrupt 节点
        next_node = snapshot.next[0]
        stage_idx = INTERRUPT_TO_STAGE_IDX.get(next_node)
        if stage_idx is None:
            # 不认识的节点，继续执行
            result = None
            for event in graph.stream(None, config, stream_mode="values"):
                result = event
            continue

        current_stage = STAGE_ORDER[stage_idx]
        stage_display = STAGE_NAMES.get(current_stage, current_stage)
        output = get_stage_output(result or snapshot.values, current_stage)

        print_divider(stage_display)
        print(output)

        proceed, feedback = ask_user_confirmation(stage_display)
        if not proceed:
            print_divider("⏸️ 流程已暂停")
            print(f"进度已保存。恢复命令：python run.py --session {config['configurable']['thread_id']}")
            return

        graph.update_state(config, {"human_feedback": feedback})

        result = None
        for event in graph.stream(None, config, stream_mode="values"):
            result = event


def resume_session(graph, session_id: str):
    """恢复之前中断的会话"""
    config = {"configurable": {"thread_id": session_id}}
    snapshot = graph.get_state(config)

    if not snapshot or not snapshot.values:
        print(f"❌ 未找到会话 '{session_id}' 的保存记录。")
        print("请使用 python run.py 开始新会话。")
        return

    topic = snapshot.values.get("topic", "未知课题")
    stage = snapshot.values.get("current_stage", "未知")

    print_divider("🔄 恢复科研流程")
    print(f"研究课题：{topic}")
    print(f"会话 ID：{session_id}")
    print(f"上次停在：{STAGE_NAMES.get(stage, stage)}")

    if not snapshot.next:
        print("\n该会话已完成所有阶段。")
        return

    # 从当前状态继续 interrupt 循环
    run_interrupt_loop(graph, config, snapshot.values)


def main():
    parser = argparse.ArgumentParser(description="🔬 科研智能体 - Research Agent")
    parser.add_argument("--resume", action="store_true", help="恢复上次中断的会话")
    parser.add_argument("--session", type=str, default="research-session-1", help="会话 ID（默认: research-session-1）")
    args = parser.parse_args()

    print_divider("🔬 科研智能体 - Research Agent")
    print("基于 LangGraph 的多阶段科研工作流")
    print("流程：课题输入 → 文献调研 → 假设生成 → 实验设计 → 实验代码 → 结果分析 → 论文初稿")
    print(f"进度持久化：checkpoints.db\n")

    graph = create_app()

    if args.resume:
        resume_session(graph, args.session)
    else:
        run_new_session(graph, args.session)


if __name__ == "__main__":
    main()
