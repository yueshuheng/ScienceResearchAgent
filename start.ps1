# 科研智能体 - 一键启动脚本 (PowerShell)
$Host.UI.RawUI.WindowTitle = "科研智能体服务"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   科研智能体 - 一键启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查虚拟环境
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "[错误] 未找到虚拟环境 .venv" -ForegroundColor Red
    Write-Host "请先运行: python -m venv .venv"
    Read-Host "按回车退出"
    exit 1
}

# 激活虚拟环境
& .venv\Scripts\Activate.ps1

# 检查依赖
Write-Host "[1/3] 检查环境..." -ForegroundColor Yellow
try {
    python -c "import fastapi" 2>$null
} catch {
    Write-Host "[提示] 正在安装依赖..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# 构建前端（如果需要）
$distPath = "Futuristic AI Chat Interface\dist\index.html"
if (-not (Test-Path $distPath)) {
    Write-Host "[2/3] 构建前端..." -ForegroundColor Yellow
    Push-Location "Futuristic AI Chat Interface"
    npm install
    npm run build
    Pop-Location
} else {
    Write-Host "[2/3] 前端已构建，跳过..." -ForegroundColor Green
}

# 启动服务
Write-Host "[3/3] 启动服务..." -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "   服务地址: http://localhost:8000" -ForegroundColor Green
Write-Host "   按 Ctrl+C 停止服务" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

uvicorn server:app --host 0.0.0.0 --port 8000 --reload
