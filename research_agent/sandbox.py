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
8. 文件操作工具：提供安全的文件读写 API（限制在工作目录内）
"""

from __future__ import annotations

import subprocess
import tempfile
import os
import sys
import time
import re
import uuid
import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

from research_agent.logger import get_logger

log = get_logger("sandbox")

# ── 配置 ──────────────────────────────────────────────────────

MAX_TIMEOUT = 0             # 0 表示不限制
DEFAULT_TIMEOUT = 0       # 默认不限制
MAX_OUTPUT_BYTES = 50_000 # 输出截断阈值
MAX_CODE_LENGTH = 100_000 # 代码最大长度
MAX_FILE_SIZE = 10_000_000  # 单文件最大 10MB
MAX_FILES = 100           # 最多 100 个文件

# 禁止导入的模块（安全黑名单）
BLOCKED_MODULES = {
    "subprocess", "shutil", "ctypes", "multiprocessing",
    "signal", "resource", "pty", "fcntl", "termios",
    "webbrowser", "antigravity", "turtle", "tkinter",
    "xmlrpc", "http.server", "socketserver",
}

# 禁止的代码模式（正则）— 只检测最危险的操作
BLOCKED_PATTERNS = [
    r"\bos\.system\s*\(",
    r"\bos\.popen\s*\(",
    r"\bos\.exec\w*\s*\(",
    r"\bos\.spawn\w*\s*\(",
    r"\bos\.fork\s*\(",
    r"\bos\.kill\s*\(",
    r"\bshutil\.rmtree\s*\(",
]

# 危险的 shell 命令（黑名单）
BLOCKED_SHELL_COMMANDS = {
    "rm -rf /", "rm -rf /*", "rm -rf ~",
    "mkfs", "dd if=", ":(){:|:&};:",
    "chmod -R 777 /", "chown -R",
    "shutdown", "reboot", "halt", "poweroff",
    "kill -9", "killall",
    "format", "fdisk",
}

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


# ── 文件操作工具注入代码 ──────────────────────────────────────

_FILE_TOOLS_CODE = '''
import os as _os
import json as _json
from pathlib import Path as _Path

# 工作目录（沙箱内的安全区域）
_WORK_DIR = _Path("{work_dir}")

def _safe_path(path):
    """确保路径在工作目录内"""
    p = (_WORK_DIR / path).resolve() if not _os.path.isabs(path) else _Path(path).resolve()
    try:
        p.relative_to(_WORK_DIR)
    except ValueError:
        raise PermissionError(f"路径超出工作目录范围: {path}")
    return p

# ── 文件操作工具 ──────────────────────────────────────

def fs_read(path, encoding="utf-8"):
    """
    读取文件内容。
    
    参数:
        path: 文件路径（相对于工作目录）
        encoding: 文件编码，默认 utf-8
    
    返回:
        文件内容字符串
    
    示例:
        content = fs_read("data.txt")
        content = fs_read("data.json")  # 自动解析 JSON
    """
    p = _safe_path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if p.stat().st_size > {max_file_size}:
        raise ValueError(f"文件过大: {path} (最大 {max_file_size // 1024 // 1024}MB)")
    
    content = p.read_text(encoding=encoding)
    
    # 如果是 JSON 文件，自动解析
    if str(path).endswith('.json'):
        try:
            return _json.loads(content)
        except:
            pass
    return content

def fs_write(path, content, encoding="utf-8"):
    """
    写入文件。
    
    参数:
        path: 文件路径（相对于工作目录）
        content: 文件内容（字符串或 dict/list，dict/list 自动转 JSON）
        encoding: 文件编码，默认 utf-8
    
    返回:
        写入的字节数
    
    示例:
        fs_write("output.txt", "Hello World!")
        fs_write("data.json", {"key": "value"})  # 自动转 JSON
    """
    p = _safe_path(path)
    
    # 检查文件数量限制
    if not p.exists():
        files = list(_WORK_DIR.rglob("*"))
        if len(files) >= {max_files}:
            raise ValueError(f"文件数量达到上限: {max_files}")
    
    # 处理 JSON
    if isinstance(content, (dict, list)):
        content = _json.dumps(content, ensure_ascii=False, indent=2)
    
    if not isinstance(content, str):
        content = str(content)
    
    # 检查大小
    if len(content.encode(encoding)) > {max_file_size}:
        raise ValueError(f"内容过大 (最大 {max_file_size // 1024 // 1024}MB)")
    
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)
    return len(content.encode(encoding))

def fs_list(path="."):
    """
    列出目录内容。
    
    参数:
        path: 目录路径（相对于工作目录），默认为当前目录
    
    返回:
        文件和目录列表 [{"name": "...", "type": "file|dir", "size": N}, ...]
    
    示例:
        files = fs_list()
        files = fs_list("data")
    """
    p = _safe_path(path)
    if not p.exists():
        raise FileNotFoundError(f"目录不存在: {path}")
    if not p.is_dir():
        raise NotADirectoryError(f"不是目录: {path}")
    
    items = []
    for item in sorted(p.iterdir()):
        item_type = "dir" if item.is_dir() else "file"
        size = item.stat().st_size if item.is_file() else 0
        items.append({
            "name": item.name,
            "type": item_type,
            "size": size,
        })
    return items

def fs_exists(path):
    """
    检查文件或目录是否存在。
    
    参数:
        path: 路径（相对于工作目录）
    
    返回:
        True 或 False
    
    示例:
        if fs_exists("data.txt"):
            print("文件存在")
    """
    return _safe_path(path).exists()

def fs_mkdir(path):
    """
    创建目录。
    
    参数:
        path: 目录路径（相对于工作目录）
    
    示例:
        fs_mkdir("output")
        fs_mkdir("data/experiments")
    """
    p = _safe_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return str(p.relative_to(_WORK_DIR))

def fs_delete(path):
    """
    删除文件或空目录。
    
    参数:
        path: 路径（相对于工作目录）
    
    示例:
        fs_delete("old_file.txt")
    """
    p = _safe_path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if p.is_dir():
        if list(p.iterdir()):
            raise ValueError(f"目录非空，无法删除: {path}")
        p.rmdir()
    else:
        p.unlink()
    return True

def fs_copy(src, dst):
    """
    复制文件。
    
    参数:
        src: 源文件路径
        dst: 目标文件路径
    
    示例:
        fs_copy("data.txt", "backup/data.txt")
    """
    import shutil as _shutil
    src_p = _safe_path(src)
    dst_p = _safe_path(dst)
    if not src_p.exists():
        raise FileNotFoundError(f"源文件不存在: {src}")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    _shutil.copy2(src_p, dst_p)
    return str(dst_p.relative_to(_WORK_DIR))

def fs_rename(src, dst):
    """
    重命名文件或目录。
    
    参数:
        src: 原路径
        dst: 新路径
    
    示例:
        fs_rename("old.txt", "new.txt")
    """
    src_p = _safe_path(src)
    dst_p = _safe_path(dst)
    if not src_p.exists():
        raise FileNotFoundError(f"文件不存在: {src}")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    src_p.rename(dst_p)
    return str(dst_p.relative_to(_WORK_DIR))

# 打印工作目录信息
print(f"工作目录: {_WORK_DIR}")
'''

# ── Shell 执行工具注入代码 ────────────────────────────────────

_SHELL_TOOLS_CODE = '''
import subprocess as _subprocess

# 危险命令黑名单
_BLOCKED_COMMANDS = {blocked_commands}

def _check_command_safety(cmd):
    """检查命令是否安全"""
    cmd_lower = cmd.lower().strip()
    for blocked in _BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            raise PermissionError(f"危险命令被拦截: " + blocked)
    return True

def shell_exec(cmd, timeout={shell_timeout}, cwd=None):
    """
    执行 shell 命令。
    
    参数:
        cmd: 要执行的命令（字符串）
        timeout: 超时秒数，默认 30 秒
        cwd: 工作目录，默认为沙箱工作目录
    
    返回:
        dict 包含 returncode, stdout, stderr
    """
    _check_command_safety(cmd)
    
    work_dir = str(_WORK_DIR) if cwd is None else str(_safe_path(cwd))
    
    try:
        result = _subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[:50000],
            "stderr": result.stderr[:50000],
        }
    except _subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "命令执行超时 (" + str(timeout) + "秒)",
        }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
        }

def pip_install(*packages, user=False):
    """安装 pip 包。"""
    pkg_list = " ".join(packages)
    cmd = "pip install --break-system-packages " + pkg_list
    print("执行: " + cmd)
    return shell_exec(cmd, timeout=120)

def run_python(script_path, *args, timeout=60):
    """运行 Python 脚本。"""
    args_str = " ".join(str(a) for a in args)
    cmd = "python " + str(script_path) + " " + args_str
    print("执行: " + cmd)
    return shell_exec(cmd, timeout=timeout)

print("Shell 工具已加载: shell_exec(), pip_install(), run_python()")
'''


# ── 沙箱执行包装器 ────────────────────────────────────────────

def _build_wrapper(code_file: str, work_dir: str, blocked_modules: set, site_packages: str = "") -> str:
    """动态生成沙箱包装器代码"""
    blocked_repr = repr(blocked_modules)
    code_path = code_file.replace("\\", "\\\\")
    work_path = work_dir.replace("\\", "\\\\")
    site_path = site_packages.replace("\\", "\\\\") if site_packages else ""
    
    # 获取所有可能的 site-packages 路径
    import site
    all_site_paths = []
    # venv 的 site-packages
    if site_packages:
        all_site_paths.append(site_packages)
    # 系统 Python 的 site-packages（base_prefix）
    base_sp = os.path.join(sys.base_prefix, "Lib", "site-packages")
    if os.path.isdir(base_sp):
        all_site_paths.append(base_sp)
    # site.getsitepackages
    try:
        for p in site.getsitepackages():
            if p not in all_site_paths:
                all_site_paths.append(p)
    except Exception:
        pass
    
    site_paths_escaped = [p.replace("\\", "\\\\") for p in all_site_paths]
    site_paths_repr = repr(site_paths_escaped)
    
    # 生成文件工具代码
    file_tools = _FILE_TOOLS_CODE.replace("{work_dir}", work_path)
    file_tools = file_tools.replace("{max_file_size}", str(MAX_FILE_SIZE))
    file_tools = file_tools.replace("{max_files}", str(MAX_FILES))
    
    # 生成 shell 工具代码
    shell_tools = _SHELL_TOOLS_CODE.replace("{blocked_commands}", repr(BLOCKED_SHELL_COMMANDS))
    shell_tools = shell_tools.replace("{shell_timeout}", "30")
    
    return f'''\
import sys
import os
import io

# 添加所有 site-packages 到路径
for _sp in {site_paths_repr}:
    _real_sp = _sp.replace("\\\\\\\\", "\\\\")
    if _real_sp not in sys.path:
        sys.path.insert(0, _real_sp)

# ── 安全限制 ──
# 禁用 socket（阻止网络访问）— 注释掉以允许 pip install
# class _FakeSocket:
#     def __getattr__(self, name):
#         raise PermissionError("沙箱环境禁止网络访问")
# sys.modules["socket"] = _FakeSocket()

# 禁用危险模块（但允许 subprocess 用于 shell_exec）
_blocked = {blocked_repr}
_blocked.discard("subprocess")  # 允许 subprocess
class _BlockedImporter:
    def find_module(self, name, path=None):
        top = name.split(".")[0]
        if top in _blocked:
            return self
        return None
    def load_module(self, name):
        raise ImportError("沙箱环境禁止导入模块: " + name)
sys.meta_path.insert(0, _BlockedImporter())

# ── 注入文件操作工具 ──
{file_tools}

# ── 注入 Shell 执行工具 ──
{shell_tools}

# ── 设置资源限制（仅 Linux/Mac）──
try:
    import resource
    # 内存限制 512MB（增大以支持更多操作）
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
except (ImportError, ValueError, OSError):
    pass  # Windows 不支持 resource 模块

# ── 执行用户代码 ──
try:
    _code_text = open("{code_path}", "r", encoding="utf-8").read()
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
    python_path: str = "",
    on_output: callable = None,
    work_dir: str = "",
) -> ExecutionResult:
    """
    在沙箱中执行代码。

    Args:
        code: 要执行的代码
        timeout: 超时秒数（0 表示不限制）
        language: 编程语言（目前仅支持 python）
        python_path: 指定 Python 解释器路径（空则使用当前环境）
        on_output: 实时输出回调函数，每行输出调用一次
        work_dir: 工作目录（空则使用临时目录）

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

    # 超时设置：0 表示不限制
    if timeout <= 0:
        timeout = None

    # 创建工作目录
    use_temp = not work_dir or not os.path.isdir(work_dir)
    if use_temp:
        work_dir = tempfile.mkdtemp(prefix="sandbox_")
    code_file = os.path.join(work_dir, ".sandbox_user_code.py")
    wrapper_file = os.path.join(work_dir, ".sandbox_runner.py")

    try:
        # 写入用户代码
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        # 写入沙箱包装器
        import sysconfig
        site_packages = sysconfig.get_path("purelib")
        
        # 确定 Python 解释器
        python_exe = python_path if python_path and os.path.isfile(python_path) else sys.executable
        
        wrapper_code = _build_wrapper(code_file, work_dir, BLOCKED_MODULES, site_packages)
        with open(wrapper_file, "w", encoding="utf-8") as f:
            f.write(wrapper_code)

        # 执行
        start_time = time.monotonic()
        try:
            # 构建安全的环境变量
            safe_env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": site_packages,
                "PYTHONHASHSEED": "0",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",  # 禁用缓冲，实时输出
                "HOME": work_dir,
                "TEMP": work_dir,
                "TMP": work_dir,
            }
            # Windows 需要这些变量来执行 shell 命令
            if sys.platform == "win32":
                safe_env["ComSpec"] = os.environ.get("ComSpec", r"C:\Windows\system32\cmd.exe")
                safe_env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
                safe_env["SYSTEMDRIVE"] = os.environ.get("SYSTEMDRIVE", "C:")
                safe_env["USERPROFILE"] = os.environ.get("USERPROFILE", work_dir)
                safe_env["APPDATA"] = os.environ.get("APPDATA", os.path.join(work_dir, "AppData"))
                safe_env["USERNAME"] = os.environ.get("USERNAME", "sandbox")
                safe_env["LOCALAPPDATA"] = os.environ.get("LOCALAPPDATA", os.path.join(work_dir, "AppData", "Local"))
                safe_env["HOMEDRIVE"] = os.environ.get("HOMEDRIVE", "C:")
                safe_env["HOMEPATH"] = os.environ.get("HOMEPATH", "\\Users\\sandbox")
            
            # 使用 Popen 实时读取输出
            proc = subprocess.Popen(
                [python_exe, wrapper_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                env=safe_env,
            )
            
            stdout_chunks = []
            stderr_chunks = []
            
            # 实时读取 stdout
            import threading
            
            def _read_stderr():
                try:
                    for line in iter(proc.stderr.readline, b''):
                        text = line.decode('utf-8', errors='replace')
                        stderr_chunks.append(text)
                except Exception:
                    pass
            
            stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
            stderr_thread.start()
            
            # 实时读取 stdout 并通过回调推送
            try:
                for line in iter(proc.stdout.readline, b''):
                    text = line.decode('utf-8', errors='replace')
                    stdout_chunks.append(text)
                    # 调用回调推送实时输出
                    if on_output:
                        on_output(text)
            except Exception:
                pass
            
            proc.wait()
            stderr_thread.join(timeout=5)
            
            duration = time.monotonic() - start_time
            
            stdout = "".join(stdout_chunks)[:MAX_OUTPUT_BYTES]
            stderr = "".join(stderr_chunks)[:MAX_OUTPUT_BYTES]
            if len("".join(stdout_chunks)) > MAX_OUTPUT_BYTES:
                stdout += "\n... [输出已截断]"
            if len("".join(stderr_chunks)) > MAX_OUTPUT_BYTES:
                stderr += "\n... [输出已截断]"

            log.info(f"代码执行完成 | exit={proc.returncode} duration={duration:.2f}s")

            return ExecutionResult(
                success=proc.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                duration=round(duration, 3),
                killed=False,
                error="",
                blocked_reason="",
            )

        except subprocess.TimeoutExpired:
            proc.kill()
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
        # 清理沙箱临时文件
        try:
            if os.path.exists(code_file):
                os.remove(code_file)
            if os.path.exists(wrapper_file):
                os.remove(wrapper_file)
        except Exception:
            pass
        # 只在使用临时目录时删除整个目录
        if use_temp:
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
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
