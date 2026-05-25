import sys, asyncio
sys.path.insert(0, '/mnt/d/GIT/XD-AIGC-agent')

import lark_oapi.ws.client as wsc

async def _patched_receive_loop(self):
    print("[PATCH] receive loop started", flush=True)
    try:
        while True:
            if self._conn is None:
                break
            msg = await self._conn.recv()
            t = "bytes" if isinstance(msg, bytes) else "str"
            preview = msg.hex()[:80] if isinstance(msg, bytes) else str(msg)[:200]
            print(f"[FRAME] {t} len={len(msg)} :: {preview}", flush=True)
            asyncio.get_event_loop().create_task(self._handle_message(msg))
    except Exception as e:
        print(f"[LOOP EXIT] {e}", flush=True)

wsc.Client._receive_message_loop = _patched_receive_loop

from src.config import FEISHU_APP_ID, FEISHU_APP_SECRET
from src.feishu.adapter import build_event_handler
import lark_oapi as lark

def on_message(data):
    print(f"[ON_MESSAGE] {data}", flush=True)

handler = build_event_handler(on_message)
ws = lark.ws.Client(FEISHU_APP_ID, FEISHU_APP_SECRET,
    event_handler=handler, log_level=lark.LogLevel.DEBUG)
print("Starting...", flush=True)
ws.start()
