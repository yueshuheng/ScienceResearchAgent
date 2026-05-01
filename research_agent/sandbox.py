"""
安全沙箱 — 在隔离环境中执行用户/AI 生成的 Python 代码

安全措施：
1. subprocess 隔离：代码在独立子进程中运行
2. 超时限制：默认 30 秒
3. 内存限制：默认 256MB（通过 resource 模块，仅 Linux/Mac）
4. 禁止危险模块：os.system, subprocess, shutil.rmtree 等
5. 禁止网络访问：屏蔽 socket 模块
6. 工作目录隔离：在临时目录中执行
7. 输出截断：stdout/stderr 最大 50KB
"""

from __future__ import annotations

import subprocess
import tempfile
import os
import sys
import time
import re
import uuid
from dataclasses import dataclass, asdict

from research_agent.logger import get_logger

log = get_logger("sandbox")

# ── 配置 ──────────────────────────────────────────────────────

MAX_TIMEOUT = 60          # 最大允许超时（秒）
DEFAULT_TIMEOUT = 30      # 默认超时
MAX_OUTPUT_BYTES = 50_000 # 输出截断阈值
MAX_CODE_LENGTH = 100_000 # 代码最大长度

# 禁止导入的模块（安全黑名单）
BLOCKED_MODULES = {
    "subprocess", "shutil", "ctypes", "multiprocessing",
    "signal", "resource", "pty", "fcntl", "termios",
    "webbrowser", "antigravity", "turtle", "tkinter",
    "xmlrpc", "http.server", "socketserver",
}

# 禁止的代码模式（正则）
BLOCKED_PATTERNS = [
    r"\bos\.system\b",
    r"\bos\.popen\b",
    r"\bos\.exec\w*\b",
    r"\bos\.spawn\w*\b",
    r"\bos\.fork\b",
    r"\bos\.kill\b",
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bos\.rmdir\b",
    r"\bos\.removedirs\b",
    r"\bshutil\.rmtree\b",
    r"\bshutil\.move\b",
    r"\b__import__\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\bopen\s*\(.*(w|a|x)\b",  # 禁止写模式 open
]

# 允许的安全模块白名单（用于提示，不做强制限制）
SAFE_MODULES = {
    "math", "random", "statistics", "collections", "itertools",
    "functools", "operator", "string", "re", "json", "csv",
    "datetime", "time", "copy", "typing", "dataclasses",
    "numpy", "pandas", "scipy", "sklearn", "matplotlib",
    "seaborn", "torch", "tensorflow", "transformers",
}


@dataclass
class ExecutionResult:
    """代码执行结果"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration: float       # 秒
    killed: bool          # 是否被超时杀死
    error: str            # 沙箱层面的错误信息
    blocked_reason: str   # 如果代码被拦截，说明原因

    def to_dict(self) -> dict:
        return asdict(self)


# ── 静态安全检查 ──────────────────────────────────────────────

def _static_check(code: str) -> str | None:
    """
    静态扫描代码，检查是否包含危险操作。
    返回 None 表示通过，否则返回拦截原因。
    """
    # 检查代码长度
    if len(code) > MAX_CODE_LENGTH:
        return f"代码过长（{len(code)} 字符），最大允许 {MAX_CODE_LENGTH} 字符"

    # 检查危险模式
    for pattern in BLOCKED_PATTERNS:
        match = re.search(pattern, code)
        if match:
            return f"检测到危险操作: {match.group()}"

    # 检查危险 import
    import_pattern = r"(?:^|\n)\s*(?:import|from)\s+([\w.]+)"
    for m in re.finditer(import_pattern, code):
        module_name = m.group(1).split(".")[0]
        if module_name in BLOCKED_MODULES:
            return f"禁止导入模块: {module_name}"

    return None


# ── 沙箱执行包装器 ────────────────────────────────────────────

def _build_wrapper(code_file: str, blocked_modules: set) -> str:
    """动态生成沙箱包装器代码"""
    blocked_repr = repr(blocked_modules)
    code_path = code_file.replace("\\", "\\\\")
    return f'''\
import sys
import io

# ── 安全限制 ──
# 禁用 socket（阻止网络访问）
class _FakeSocket:
    def __getattr__(self, name):
        raise PermissionError("沙箱环境禁止网络访问")
sys.modules["socket"] = _FakeSocket()

# 禁用危险模块
_blocked = {blocked_repr}
class _BlockedImporter:
    def find_module(self, name, path=None):
        top = name.split(".")[0]
        if top in _blocked:
            return self
        return None
    def load_module(self, name):
        raise ImportError("沙箱环境禁止导入模块: " + name)
sys.meta_path.insert(0, _BlockedImporter())

# 限制 open 只能读
_builtin_open = open
def _safe_open(file, mode="r", *args, **kwargs):
    if any(c in mode for c in "wax"):
        raise PermissionError("沙箱环境禁止写文件 (mode=" + mode + ")")
    return _builtin_open(file, mode, *args, **kwargs)
import builtins
builtins.open = _safe_open

# ── 设置资源限制（仅 Linux/Mac）──
try:
    import resource
    # 内存限制 256MB
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
except (ImportError, ValueError, OSError):
    pass  # Windows 不支持 resource 模块

# ── 执行用户代码 ──
try:
    _code_text = _builtin_open("{code_path}", "r", encoding="utf-8").read()
    exec(_code_text)
except SystemExit:
    pass
except Exception as _e:
    print(type(_e).__name__ + ": " + str(_e), file=sys.stderr)
    sys.exit(1)
'''


def execute_code(
    code: str,
    timeout: int = DEFAULT_TIMEOUT,
    language: str = "python",
) -> ExecutionResult:
    """
    在沙箱中执行代码。

    Args:
        code: 要执行的代码
        timeout: 超时秒数（最大 MAX_TIMEOUT）
        language: 编程语言（目前仅支持 python）

    Returns:
        ExecutionResult 包含执行结果
    """
    if language != "python":
        return ExecutionResult(
            success=False, stdout="", stderr="",
            exit_code=-1, duration=0, killed=False,
            error=f"暂不支持 {language} 语言，目前仅支持 Python",
            blocked_reason="",
        )

    # 静态安全检查
    blocked = _static_check(code)
    if blocked:
        log.warning(f"代码被拦截: {blocked}")
        return ExecutionResult(
            success=False, stdout="", stderr="",
            exit_code=-1, duration=0, killed=False,
            error="", blocked_reason=blocked,
        )

    # 限制超时
    timeout = min(max(timeout, 1), MAX_TIMEOUT)

    # 创建临时目录和文件
    work_dir = tempfile.mkdtemp(prefix="sandbox_")
    code_file = os.path.join(work_dir, "user_code.py")
    wrapper_file = os.path.join(work_dir, "runner.py")

    try:
        # 写入用户代码
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # 写入沙箱包装器
        wrapper_code = _build_wrapper(code_file, BLOCKED_MODULES)
        with open(wrapper_file, "w", encoding="utf-8") as f:
            f.write(wrapper_code)

        # 执行
        start_time = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, wrapper_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work_dir,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": "",
                    "PYTHONHASHSEED": "0",
                    "HOME": work_dir,
                    "TEMP": work_dir,
                    "TMP": work_dir,
                },
            )
            duration = time.monotonic() - start_time

            stdout = result.stdout[:MAX_OUTPUT_BYTES]
            stderr = result.stderr[:MAX_OUTPUT_BYTES]
            if len(result.stdout) > MAX_OUTPUT_BYTES:
                stdout += "\n... [输出已截断]"
            if len(result.stderr) > MAX_OUTPUT_BYTES:
                stderr += "\n... [输出已截断]"

            log.info(f"代码执行完成 | exit={result.returncode} duration={duration:.2f}s")

            return ExecutionResult(
                success=result.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
                duration=round(duration, 3),
                killed=False,
                error="",
                blocked_reason="",
            )

        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start_time
            log.warning(f"代码执行超时 ({timeout}s)")
            return ExecutionResult(
                success=False, stdout="", stderr="",
                exit_code=-1, duration=round(duration, 3),
                killed=True,
                error=f"执行超时（{timeout} 秒限制）",
                blocked_reason="",
            )

    except Exception as e:
        log.error(f"沙箱执行异常: {e}", exc_info=True)
        return ExecutionResult(
            success=False, stdout="", stderr="",
            exit_code=-1, duration=0, killed=False,
            error=f"沙箱内部错误: {str(e)}",
            blocked_reason="",
        )

    finally:
        # 清理临时文件
        try:
            for f in os.listdir(work_dir):
                fp = os.path.join(work_dir, f)
                if os.path.isfile(fp):
                    os.unlink(fp)
            os.rmdir(work_dir)
        except OSError:
            pass


def extract_code_blocks(text: str) -> list[dict]:
    """
    从 Markdown 文本中提取所有代码块。

    Returns:
        [{"language": "python", "code": "..."}]
    """
    pattern = r"```(\w*)\s*\n(.*?)```"
    blocks = []
    for m in re.finditer(pattern, text, re.DOTALL):
        lang = m.group(1).lower() or "text"
        code = m.group(2).strip()
        if code:
            blocks.append({"language": lang, "code": code})
    return blocks
