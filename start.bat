@echo off
chcp 65001 >nul
title 科研智能体服务

echo ========================================
echo    科研智能体 - 一键启动
echo ========================================
echo.

:: 检查虚拟环境
if not exist ".venv\Scripts\activate.bat" (
    echo [错误] 未找到虚拟环境 .venv
    echo 请先运行: python -m venv .venv
    pause
    exit /b 1
)

:: 激活虚拟环境
call .venv\Scripts\activate.bat

:: 安装/更新依赖
echo [Step 1/3] 安装依赖...
uv pip install -r research_agent/requirements.txt --python .venv\Scripts\python.exe -q

:: 构建前端（如果需要）
if not exist "Futuristic AI Chat Interface\dist\index.html" (
    echo [Step 2/3] 构建前端...
    cd "Futuristic AI Chat Interface"
    call npm install
    call npm run build
    cd ..
) else (
    echo [Step 2/3] 前端已构建，跳过...
)

:: 启动服务
echo [Step 3/3] 启动服务...
echo.
echo ========================================
echo    服务地址: http://localhost:8000
echo    按 Ctrl+C 停止服务
echo ========================================
echo.

.venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload

pause
