"""
代码研究员 Agent — 自动生成、验证、执行、修复代码

Agent Loop:
1. 生成代码
2. 语法检查（AST 解析）
3. 执行代码
4. 如果出错，分析错误并修复
5. 重试（最多 3 次）
6. 返回最终结果

所有步骤通过 SSE 实时推送到前端展示
"""

from __future__ import annotations

import ast
import os
import re
import json
import difflib
from typing import Generator

from langchain_moonshot import ChatMoonshot
from research_agent.streaming import push_status, push_token, get_stream
from research_agent.sandbox import execute_code, _static_check
from research_agent.logger import get_logger

log = get_logger("code_agent")

MAX_FIX_ATTEMPTS = 3

# ── Agent 步骤类型 ──────────────────────────────────────────────

STEP_TYPES = {
    "thinking": "🤔 思考中",
    "generating": "✍️ 生成代码",
    "syntax_check": "🔍 语法检查",
    "executing": "▶️ 执行代码",
    "analyzing_error": "🔧 分析错误",
    "fixing": "🛠️ 修复代码",
    "success": "✅ 执行成功",
    "failed": "❌ 执行失败",
}


def _push_step(sid: str, step_type: str, content: str = "", details: dict = None):
    """推送 Agent 步骤到前端"""
    step_data = {
        "type": step_type,
        "label": STEP_TYPES.get(step_type, step_type),
        "content": content,
        "details": details or {},
    }
    log.info(f"[{sid}] 推送步骤: {step_type} - {content[:50] if content else ''}")
    push_status(sid, "agent_step", step_data)


def _syntax_check(code: str) -> tuple[bool, str]:
    """
    检查 Python 代码语法。
    返回 (是否通过, 错误信息)
    """
    # 先做静态安全检查
    blocked = _static_check(code)
    if blocked:
        return False, f"安全检查失败: {blocked}"
    
    # AST 语法检查
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误 (行 {e.lineno}): {e.msg}"


def _extract_code(text: str) -> str:
    """从 LLM 输出中提取 Python 代码块"""
    # 尝试提取 ```python 代码块
    matches = re.findall(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return max(matches, key=len).strip()
    
    # 尝试提取 ``` 代码块
    matches = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return max(matches, key=len).strip()
    
    return ""


def _generate_diff(old_code: str, new_code: str) -> str:
    """生成两段代码之间的 unified diff"""
    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile='原始代码', tofile='修复后',
        lineterm=''
    )
    return ''.join(diff)


def _call_llm(sid: str, system: str, user: str, stream_tokens: bool = False) -> str:
    """直接调用 LLM，不使用 ChatPromptTemplate（避免花括号转义问题）
    
    Args:
        stream_tokens: 是否将 token 推送到前端（默认 False，代码生成时不需要）
    """
    # 从设置中读取模型配置
    model_name = "kimi-k2.5"
    try:
        settings_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")
        if os.path.exists(settings_file):
            with open(settings_file, "r") as f:
                _settings = json.load(f)
            if _settings.get("model_name"):
                model_name = _settings["model_name"]
    except Exception:
        pass
    
    llm = ChatMoonshot(model=model_name, thinking=False, temperature=0.6, timeout=120)
    
    # 构建消息列表，如果 system 为空则只用 human
    if system:
        messages = [
            ("system", system),
            ("human", user),
        ]
    else:
        messages = [
            ("human", user),
        ]
    
    q = get_stream(sid)
    log.info(f"[{sid}] Code Agent LLM 调用 | system={len(system)} user={len(user)}")
    
    full_text = ""
    try:
        for chunk in llm.stream(messages):
            token = chunk.content
            if token:
                full_text += token
                if stream_tokens and q:
                    push_token(sid, token)
        log.info(f"[{sid}] Code Agent LLM 完成 | {len(full_text)} 字符")
    except Exception as e:
        log.error(f"[{sid}] Code Agent LLM 错误: {e}")
        raise
    return full_text


# ── 代码生成 Prompt ──────────────────────────────────────────────

CODE_GEN_PROMPT = """\
你是一位专业的 Python 代码专家。根据用户需求生成完整可运行的代码。

## 可用工具函数

沙箱环境已预置以下工具函数，可以直接使用：

### 文件操作
- `fs_read(path)` - 读取文件内容
- `fs_write(path, content)` - 写入文件（支持 dict/list 自动转 JSON）
- `fs_list(path=".")` - 列出目录内容
- `fs_exists(path)` - 检查文件是否存在
- `fs_mkdir(path)` - 创建目录
- `fs_delete(path)` - 删除文件
- `fs_copy(src, dst)` - 复制文件
- `fs_rename(src, dst)` - 重命名文件

### Shell 命令
- `shell_exec(cmd, timeout=30)` - 执行 shell 命令，返回 dict 包含 returncode, stdout, stderr
- `pip_install(*packages)` - 安装 pip 包
- `run_python(script_path, *args)` - 运行 Python 脚本

## 要求
1. 代码必须完整可运行
2. 包含必要的 import 语句
3. 使用 print() 输出关键结果
4. 代码放在 ```python 代码块中
5. 如果需要安装依赖，先用 pip_install() 安装
"""

CODE_FIX_PROMPT = """\
代码执行出错，请分析错误并修复代码。

## 原始代码
```python
{code}
```

## 错误信息
```
{error}
```

## 可用工具函数
沙箱环境已预置以下工具函数，可以直接使用（无需 import）：
- `pip_install(*packages)` - 安装 pip 包，例如 `pip_install('torch', 'numpy')`
- `shell_exec(cmd)` - 执行 shell 命令
- `fs_read(path)`, `fs_write(path, content)` - 文件读写

## 修复要求
1. 分析错误原因
2. **如果是 ModuleNotFoundError（缺少模块），在代码开头添加 `pip_install('模块名')` 来安装**
3. 给出修复后的完整代码
4. 代码放在 ```python 代码块中

## 示例：修复缺少 torch 的错误
```python
# 先安装依赖
pip_install('torch', 'torchvision')

# 然后正常 import
import torch
import torchvision
# ... 其余代码
```
"""


def run_code_agent(
    sid: str,
    user_id: int,
    task: str,
    context: str = "",
    memory_context: str = "",
) -> dict:
    """
    运行代码研究员 Agent。
    
    Args:
        sid: 会话 ID
        user_id: 用户 ID
        task: 用户任务描述
        context: 上下文信息（如之前的对话）
        memory_context: 长期记忆上下文
    
    Returns:
        {
            "success": bool,
            "code": str,           # 最终代码
            "output": str,         # 执行输出
            "error": str,          # 错误信息（如果失败）
            "attempts": int,       # 尝试次数
            "steps": list[dict],   # 所有步骤记录
        }
    """
    log.info(f"[{sid}] 代码 Agent 启动 | task={task[:50]}")
    
    steps = []
    
    def record_step(step_type: str, content: str = "", details: dict = None):
        step = {
            "type": step_type,
            "label": STEP_TYPES.get(step_type, step_type),
            "content": content,
            "details": details or {},
        }
        steps.append(step)
        _push_step(sid, step_type, content, details)
    
    # Step 1: 思考
    record_step("thinking", "分析用户需求，规划代码结构...")
    
    # Step 2: 生成代码
    record_step("generating", "正在生成代码...")
    
    user_prompt = f"用户需求：{task}"
    if context:
        user_prompt = f"上下文：\n{context}\n\n{user_prompt}"
    
    llm_output = _call_llm(sid, CODE_GEN_PROMPT, user_prompt)
    
    log.info(f"[{sid}] LLM 输出长度: {len(llm_output)} 字符")
    
    code = _extract_code(llm_output)
    log.info(f"[{sid}] 提取代码长度: {len(code)} 字符")
    
    if not code:
        log.warning(f"[{sid}] 无法提取代码，LLM 输出前 500 字符: {llm_output[:500]}")
        record_step("failed", "无法从 LLM 输出中提取代码", {"raw_output": llm_output[:500]})
        return {
            "success": False,
            "code": "",
            "output": "",
            "error": "代码生成失败：无法提取有效代码",
            "attempts": 1,
            "steps": steps,
        }
    
    record_step("generating", f"代码生成完成 ({len(code)} 字符)", {"code": code})
    
    # Agent Loop: 语法检查 → 执行 → 修复
    current_code = code
    last_error = ""
    
    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        log.info(f"[{sid}] 尝试 {attempt}/{MAX_FIX_ATTEMPTS}")
        
        # Step 3: 语法检查
        record_step("syntax_check", f"第 {attempt} 次语法检查...")
        
        syntax_ok, syntax_error = _syntax_check(current_code)
        log.info(f"[{sid}] 语法检查: ok={syntax_ok} error={syntax_error[:100] if syntax_error else ''}")
        
        if not syntax_ok:
            record_step("syntax_check", f"语法检查失败: {syntax_error}", {"error": syntax_error})
            last_error = syntax_error
            
            if attempt < MAX_FIX_ATTEMPTS:
                # 尝试修复
                record_step("fixing", "正在修复语法错误...")
                fix_prompt = CODE_FIX_PROMPT.format(code=current_code, error=syntax_error)
                fix_output = _call_llm(sid, "", fix_prompt)
                fixed_code = _extract_code(fix_output)
                if fixed_code:
                    diff = _generate_diff(current_code, fixed_code)
                    current_code = fixed_code
                    record_step("fixing", "代码已修复", {"code": fixed_code, "diff": diff})
                    continue
            
            # 无法修复
            record_step("failed", f"语法错误无法修复: {syntax_error}")
            return {
                "success": False,
                "code": current_code,
                "output": "",
                "error": syntax_error,
                "attempts": attempt,
                "steps": steps,
            }
        
        record_step("syntax_check", "语法检查通过 ✓")
        
        # Step 4: 执行代码
        record_step("executing", f"第 {attempt} 次执行...")
        log.info(f"[{sid}] 开始执行代码...")
        
        # 从设置中获取 Python 路径和工作目录
        python_path = ""
        sandbox_work_dir = ""
        try:
            import json as _json
            settings_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r") as f:
                    _settings = _json.load(f)
                python_path = _settings.get("python_path", "")
                sandbox_work_dir = _settings.get("work_dir", "")
        except Exception:
            pass
        
        # 实时推送执行输出（每 2 秒推送一次，避免刷屏）
        import time as _time
        _last_push_time = [_time.monotonic()]
        _output_buf = []
        
        def _on_output(line: str):
            _output_buf.append(line)
            now = _time.monotonic()
            # 每 2 秒推送一次，或者是重要输出（如 epoch、error）
            if now - _last_push_time[0] >= 2.0:
                _last_push_time[0] = now
                preview = "".join(_output_buf[-8:]).strip()
                _push_step(sid, "executing", f"运行中...\n{preview}")
        
        result = execute_code(current_code, timeout=0, python_path=python_path, on_output=_on_output, work_dir=sandbox_work_dir)
        log.info(f"[{sid}] 执行结果: success={result.success} exit={result.exit_code} duration={result.duration}s")
        
        if result.success:
            log.info(f"[{sid}] 代码执行成功!")
            # 显示输出摘要
            output_preview = result.stdout.strip()
            if len(output_preview) > 300:
                output_preview = output_preview[:300] + "..."
            record_step("success", f"执行成功 ({result.duration:.1f}s)", {
                "stdout": result.stdout,
                "duration": result.duration,
            })
            return {
                "success": True,
                "code": current_code,
                "output": result.stdout,
                "error": "",
                "attempts": attempt,
                "steps": steps,
            }
        
        # 执行失败
        error_msg = result.stderr or result.error or result.blocked_reason or "未知错误"
        # 取 stderr 最后几行作为关键错误信息
        error_lines = [l for l in error_msg.strip().split('\n') if l.strip()]
        error_summary = "\n".join(error_lines[-5:]) if error_lines else error_msg
        log.warning(f"[{sid}] 执行失败: {error_summary[:300]}")
        # 如果有 stdout（比如 pip install 的输出），也展示出来
        stdout_info = ""
        if result.stdout and result.stdout.strip():
            stdout_info = result.stdout.strip()[:500]
        record_step("executing", f"执行失败: {error_msg[:200]}", {
            "stdout": stdout_info,
            "stderr": result.stderr,
            "error": result.error,
            "blocked": result.blocked_reason,
            "exit_code": result.exit_code,
        })
        last_error = error_msg
        
        if attempt < MAX_FIX_ATTEMPTS:
            # Step 5: 分析错误并修复
            record_step("analyzing_error", "分析错误原因...")
            record_step("fixing", "正在修复代码...")
            
            fix_prompt = CODE_FIX_PROMPT.format(code=current_code, error=error_msg)
            fix_output = _call_llm(sid, "", fix_prompt)
            fixed_code = _extract_code(fix_output)
            
            if fixed_code and fixed_code != current_code:
                diff = _generate_diff(current_code, fixed_code)
                current_code = fixed_code
                record_step("fixing", "代码已修复，准备重试", {"code": fixed_code, "diff": diff})
            else:
                record_step("fixing", "无法生成有效的修复代码")
                break
    
    # 所有尝试都失败
    record_step("failed", f"经过 {MAX_FIX_ATTEMPTS} 次尝试仍无法成功执行", {"last_error": last_error})
    
    return {
        "success": False,
        "code": current_code,
        "output": "",
        "error": last_error,
        "attempts": MAX_FIX_ATTEMPTS,
        "steps": steps,
    }
