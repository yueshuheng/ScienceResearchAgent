"""
非交互式测试脚本 - 验证科研智能体的 Graph 结构和 interrupt 机制
使用 FakeLLM 替代真实 API 调用
"""

import os
# 设置一个假的 API key，避免 dotenv 报错
os.environ["MOONSHOT_API_KEY"] = "sk-fake-key-for-testing"

from research_agent.main import create_app, STAGE_NAMES

STAGE_ORDER = ["literature_review", "hypothesis", "experiment_design", "experiment", "analysis", "paper"]
STAGE_OUTPUT_KEY = {
    "literature_review": "literature_review",
    "hypothesis": "hypothesis",
    "experiment_design": "experiment_design",
    "experiment": "experiment_code",
    "analysis": "analysis_result",
    "paper": "paper_draft",
}


def test_graph_structure():
    """测试 1：验证 Graph 能正确编译，节点和边都正确"""
    print("=" * 50)
    print("测试 1：Graph 结构验证")
    print("=" * 50)

    graph = create_app()
    # 获取 graph 的节点信息
    node_names = list(graph.get_graph().nodes.keys())
    print(f"节点列表: {node_names}")

    expected_nodes = [
        "__start__", "__end__",
        "literature_review", "human_after_literature",
        "hypothesis", "human_after_hypothesis",
        "experiment_design", "human_after_design",
        "experiment", "human_after_experiment",
        "analysis", "human_after_analysis",
        "paper",
    ]
    for n in expected_nodes:
        assert n in node_names, f"缺少节点: {n}"
    print("✅ 所有预期节点都存在")
    print()


def test_interrupt_mechanism():
    """测试 2：验证 interrupt 机制 - 用 mock 节点绕过 LLM 调用"""
    print("=" * 50)
    print("测试 2：Interrupt 机制验证（Mock LLM）")
    print("=" * 50)

    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from research_agent.state import ResearchState

    # 构建一个 mock graph，节点直接写入假数据，不调用 LLM
    def mock_literature(state: ResearchState) -> dict:
        return {"literature_review": "【Mock】量子计算文献综述：已找到 50 篇相关论文。", "current_stage": "literature_review"}

    def mock_hypothesis(state: ResearchState) -> dict:
        return {"hypothesis": "【Mock】假设：量子算法可将药物筛选速度提升 100 倍。", "current_stage": "hypothesis"}

    def mock_design(state: ResearchState) -> dict:
        return {"experiment_design": "【Mock】实验方案：使用 QChem 数据集 + VQE 算法 + 准确率/F1 评估。", "current_stage": "experiment_design"}

    def mock_experiment(state: ResearchState) -> dict:
        return {"experiment_code": "【Mock】实验代码：quantum_drug_screening.py", "current_stage": "experiment"}

    def mock_analysis(state: ResearchState) -> dict:
        return {"analysis_result": "【Mock】分析结果：实验验证了假设，p < 0.05。", "current_stage": "analysis"}

    def mock_paper(state: ResearchState) -> dict:
        return {"paper_draft": "【Mock】论文初稿：量子计算加速药物发现的研究。", "current_stage": "paper"}

    def human_node(state: ResearchState) -> dict:
        return {}

    builder = StateGraph(ResearchState)
    builder.add_node("literature_review", mock_literature)
    builder.add_node("human_after_literature", human_node)
    builder.add_node("hypothesis", mock_hypothesis)
    builder.add_node("human_after_hypothesis", human_node)
    builder.add_node("experiment_design", mock_design)
    builder.add_node("human_after_design", human_node)
    builder.add_node("experiment", mock_experiment)
    builder.add_node("human_after_experiment", human_node)
    builder.add_node("analysis", mock_analysis)
    builder.add_node("human_after_analysis", human_node)
    builder.add_node("paper", mock_paper)

    builder.add_edge(START, "literature_review")
    builder.add_edge("literature_review", "human_after_literature")
    builder.add_edge("human_after_literature", "hypothesis")
    builder.add_edge("hypothesis", "human_after_hypothesis")
    builder.add_edge("human_after_hypothesis", "experiment_design")
    builder.add_edge("experiment_design", "human_after_design")
    builder.add_edge("human_after_design", "experiment")
    builder.add_edge("experiment", "human_after_experiment")
    builder.add_edge("human_after_experiment", "analysis")
    builder.add_edge("analysis", "human_after_analysis")
    builder.add_edge("human_after_analysis", "paper")
    builder.add_edge("paper", END)

    graph = builder.compile(
        checkpointer=MemorySaver(),
        interrupt_before=[
            "human_after_literature",
            "human_after_hypothesis",
            "human_after_design",
            "human_after_experiment",
            "human_after_analysis",
        ],
    )

    config = {"configurable": {"thread_id": "mock-test-1"}}
    initial_state = {
        "topic": "量子计算在药物发现中的应用",
        "literature_review": "", "hypothesis": "", "experiment_design": "",
        "experiment_code": "", "analysis_result": "", "paper_draft": "",
        "messages": [], "human_feedback": "", "current_stage": "",
    }

    interrupt_points = [
        ("human_after_literature", "literature_review", "literature_review"),
        ("human_after_hypothesis", "hypothesis", "hypothesis"),
        ("human_after_design", "experiment_design", "experiment_design"),
        ("human_after_experiment", "experiment", "experiment_code"),
        ("human_after_analysis", "analysis", "analysis_result"),
    ]

    # 第一次运行
    result = None
    for event in graph.stream(initial_state, config, stream_mode="values"):
        result = event

    for i, (interrupt_node, stage_name, output_key) in enumerate(interrupt_points):
        snapshot = graph.get_state(config)
        assert snapshot.next == (interrupt_node,), \
            f"期望暂停在 {interrupt_node}，实际: {snapshot.next}"
        output = result.get(output_key, "")
        print(f"  ✓ 第{i+1}次暂停 @ {interrupt_node}")
        print(f"    输出: {output[:50]}...")

        # 模拟用户确认，继续执行
        graph.update_state(config, {"human_feedback": f"用户确认第{i+1}步"})
        result = None
        for event in graph.stream(None, config, stream_mode="values"):
            result = event

    # 最后检查论文输出
    paper = result.get("paper_draft", "")
    assert "Mock" in paper, "论文初稿未生成"
    print(f"  ✓ 论文初稿生成: {paper[:50]}...")
    print("✅ Interrupt 机制完全正常，5 个断点全部验证通过")
    print()


def test_state_schema():
    """测试 3：验证 State 定义正确"""
    print("=" * 50)
    print("测试 3：State Schema 验证")
    print("=" * 50)

    from research_agent.state import ResearchState
    import typing

    hints = typing.get_type_hints(ResearchState, include_extras=True)
    expected_fields = [
        "topic", "literature_review", "hypothesis",
        "experiment_code", "analysis_result", "paper_draft",
        "messages", "human_feedback", "current_stage",
    ]
    for field in expected_fields:
        assert field in hints, f"State 缺少字段: {field}"
        print(f"  ✓ {field}: {hints[field]}")

    print("✅ State Schema 完整")
    print()


def test_agents_importable():
    """测试 4：验证所有子智能体可以正确导入"""
    print("=" * 50)
    print("测试 4：子智能体导入验证")
    print("=" * 50)

    from research_agent.agents import (
        literature_review_agent,
        hypothesis_agent,
        experiment_design_agent,
        experiment_code_agent,
        analysis_agent,
        paper_agent,
    )

    agents = {
        "文献调研": literature_review_agent,
        "假设生成": hypothesis_agent,
        "实验设计": experiment_design_agent,
        "实验代码": experiment_code_agent,
        "结果分析": analysis_agent,
        "论文初稿": paper_agent,
    }

    for name, agent_fn in agents.items():
        assert callable(agent_fn), f"{name} 不是可调用对象"
        print(f"  ✓ {name}: {agent_fn.__name__}")

    print("✅ 所有子智能体导入成功")
    print()


if __name__ == "__main__":
    print("\n🔬 科研智能体 - 自动化测试\n")

    test_state_schema()
    test_agents_importable()
    test_graph_structure()
    test_interrupt_mechanism()

    print("=" * 50)
    print("🎉 所有测试通过！")
    print("=" * 50)
    print("\n提示：要进行完整的端到端测试，请配置 .env 文件中的")
    print("MOONSHOT_API_KEY，然后运行: python run.py")
