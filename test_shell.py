"""测试 Shell 执行工具"""
from research_agent.sandbox import execute_code

# Test 1: 基本 shell 命令
print("=" * 50)
print("Test 1: 基本 shell 命令")
print("=" * 50)
code1 = '''
# 查看 Python 版本
result = shell_exec("python --version")
print(f"Python 版本: {result['stdout'].strip()}")

# 查看 pip 版本
result = shell_exec("pip --version")
print(f"Pip 版本: {result['stdout'].strip()}")

# 列出当前目录
result = shell_exec("dir" if _os.name == "nt" else "ls -la")
print(f"目录内容:\\n{result['stdout']}")
'''
result = execute_code(code1, timeout=30)
print(f"success: {result.success}")
print(f"stdout:\n{result.stdout}")
if result.stderr:
    print(f"stderr: {result.stderr}")

# Test 2: 写入并运行 Python 脚本
print("\n" + "=" * 50)
print("Test 2: 写入并运行 Python 脚本")
print("=" * 50)
code2 = '''
# 写入一个简单的 Python 脚本
script = """
import sys
print("Hello from script!")
print(f"Arguments: {sys.argv[1:]}")
for i in range(3):
    print(f"Count: {i}")
"""
fs_write("hello.py", script)

# 运行脚本
result = run_python("hello.py", "--test", "arg1", "arg2")
print(f"返回码: {result['returncode']}")
print(f"输出:\\n{result['stdout']}")
'''
result = execute_code(code2, timeout=30)
print(f"success: {result.success}")
print(f"stdout:\n{result.stdout}")

# Test 3: 检查已安装的包
print("\n" + "=" * 50)
print("Test 3: 检查已安装的包")
print("=" * 50)
code3 = '''
# 列出已安装的包
result = shell_exec("pip list")
lines = result['stdout'].strip().split('\\n')[:10]  # 只显示前10个
print("已安装的包（前10个）:")
for line in lines:
    print(f"  {line}")
'''
result = execute_code(code3, timeout=30)
print(f"success: {result.success}")
print(f"stdout:\n{result.stdout}")

# Test 4: 危险命令拦截
print("\n" + "=" * 50)
print("Test 4: 危险命令拦截")
print("=" * 50)
code4 = '''
try:
    result = shell_exec("rm -rf /")
    print("命令执行了（不应该发生）")
except PermissionError as e:
    print(f"命令被拦截: {e}")
'''
result = execute_code(code4, timeout=10)
print(f"success: {result.success}")
print(f"stdout:\n{result.stdout}")

print("\n" + "=" * 50)
print("所有测试完成!")
print("=" * 50)
