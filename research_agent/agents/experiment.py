"""子智能体：实验设计 + 实验代码生成（流式输出）"""

from __future__ import annotations
import py_compile, re, tempfile, os

from research_agent.state import ResearchState
from research_agent.llm_utils import invoke_llm_streaming
from research_agent.streaming import push_status

DESIGN_PROMPT = """\
你是一位资深科研实验设计专家。基于研究课题、文献调研和研究假设，设计一份详细的实验方案。
请包含：1.数据集选择 2.模型/方法选择 3.评估指标 4.实验流程 5.计算资源估算
请以结构化的 Markdown 格式输出。
"""

CODE_PROMPT = """\
你是一位科研实验代码专家。基于已确认的实验方案，生成完整可运行的 Python 实验代码。
要求：完整可运行、详细中文注释、包含依赖说明、使用 argparse 管理超参数、设置随机种子、日志输出、结果保存。
先给出运行说明，然后给出完整代码放在 ```python 代码块中，最后给出预期输出描述。
"""

FIX_PROMPT = """\
以下 Python 代码存在语法错误，请修复。只输出修复后的完整代码，放在 ```python 代码块中。
错误信息：{error}
原始代码：
```python
{code}
```
"""


def _extract_python_code(text: str) -> str:
    matches = re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL)
    return max(matches, key=len).strip() if matches else ""


def _check_syntax(code: str) -> str | None:
    if not code.strip():
        return "代码为空"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name
        py_compile.compile(tmp_path, doraise=True)
        return None
    except py_compile.PyCompileError as e:
        return str(e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def experiment_design_agent(state: ResearchState) -> dict:
    sid = state.get("session_id", "")
    feedback = state.get("human_feedback", "") or "无"
    memory = state.get("memory_context", "")
    push_status(sid, "stage_start", {"stage": "experiment_design", "agent": "@实验设计研究员"})

    content = invoke_llm_streaming(
        sid, DESIGN_PROMPT,
        "研究课题：{topic}\n\n文献调研结果：\n{literature}\n\n研究假设：\n{hypothesis}\n\n用户补充信息：{feedback}",
        {"topic": state["topic"], "literature": state["literature_review"],
         "hypothesis": state["hypothesis"], "feedback": feedback},
        thinking=True, memory_context=memory,
    )
    return {"experiment_design": content, "current_stage": "experiment_design", "human_feedback": ""}


def experiment_code_agent(state: ResearchState) -> dict:
    sid = state.get("session_id", "")
    feedback = state.get("human_feedback", "") or "无"
    memory = state.get("memory_context", "")
    push_status(sid, "stage_start", {"stage": "experiment", "agent": "@代码实现研究员"})

    full_output = invoke_llm_streaming(
        sid, CODE_PROMPT,
        "研究课题：{topic}\n\n研究假设：\n{hypothesis}\n\n实验方案：\n{design}\n\n用户补充信息：{feedback}",
        {"topic": state["topic"], "hypothesis": state["hypothesis"],
         "design": state["experiment_design"], "feedback": feedback},
        thinking=True, memory_context=memory,
    )

    code = _extract_python_code(full_output)
    if code:
        for attempt in range(2):
            error = _check_syntax(code)
            if error is None:
                break
            push_status(sid, "info", {"message": f"语法错误（第{attempt+1}次），自动修复中..."})
            fix_text = invoke_llm_streaming(sid, FIX_PROMPT, "", {"error": error, "code": code}, thinking=True)
            fixed = _extract_python_code(fix_text)
            if fixed:
                code = fixed
                full_output = re.sub(r"```python\s*\n.*?```", f"```python\n{code}\n```",
                                     full_output, count=1, flags=re.DOTALL)

    return {"experiment_code": full_output, "current_stage": "experiment", "human_feedback": ""}
