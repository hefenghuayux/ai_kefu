import uvicorn
from app.core.logger import get_logger, log_event
import os
from pathlib import Path
#powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1
#$env:PYTHONUTF8="1"; posting -c .\.posting -e .\.posting\.env
logger = get_logger(service="server")

def start_server():
    # 确保工作目录正确
    os.chdir(Path(__file__).parent)
    
    log_event(
        logger,
        "INFO",
        "server_started",
        host="0.0.0.0",
        port=8000,
        cwd=os.getcwd(),
        console=True,
    )
    
    uvicorn.run(
        "main:app",        # 使用模块路径
        host="0.0.0.0",
        port=8000,
        access_log=False,
        log_level="error",
        reload=True        #开发模式下启用热重载
    )

if __name__ == "__main__":
    start_server() 
