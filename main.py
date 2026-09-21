"""兼容直接使用 ``main:app`` 启动服务的工具入口。"""

from app.main import app

# 允许直接导入 ASGI 应用对象，以便于测试和部署。
__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    # 允许开发环境直接执行 ``python main.py``，无需手工输入完整 Uvicorn 命令。
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
