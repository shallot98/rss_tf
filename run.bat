@echo off
chcp 65001 >nul
echo 启动RSS监控程序...

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.7+
    pause
    exit /b 1
)

echo Python已安装

REM 运行启动向导
echo 启动配置向导...
python start.py

pause 