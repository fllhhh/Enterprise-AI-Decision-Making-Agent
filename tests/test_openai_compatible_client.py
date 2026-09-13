from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.infra.llm import OpenAICompatibleChatModel


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        prompt = payload["messages"][-1]["content"]
        if "只输出 JSON" in prompt:
            content = '{"route":"data","confidence":0.91,"reason":"test"}'
        else:
            content = "测试回答 [E1]"
        body = json.dumps(
            {"choices": [{"message": {"content": content}}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


async def test_openai_compatible_client_contract() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAICompatibleChatModel(
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="test-key",
            model="test-model",
        )
        text = await client.generate_text("请回答")
        structured = await client.generate_json("只输出 JSON")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert text == "测试回答 [E1]"
    assert structured["route"] == "data"

