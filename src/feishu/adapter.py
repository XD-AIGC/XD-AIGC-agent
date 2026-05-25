import lark_oapi as lark
from src.config import FEISHU_APP_ID, FEISHU_APP_SECRET


def build_client() -> lark.Client:
    return lark.Client.builder() \
        .app_id(FEISHU_APP_ID) \
        .app_secret(FEISHU_APP_SECRET) \
        .build()


def build_event_handler(on_message) -> lark.EventDispatcherHandler:
    return lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message) \
        .build()
