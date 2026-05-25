import asyncio
import json
import logging
import re
import lark_oapi as lark

from src.feishu.adapter import build_client, build_event_handler
from src.feishu.reply import reply_text, reply_image
from src.feishu.upload import upload_image
from src.feishu.download import download_image, download_url
from pathlib import Path

from src.orchestrator.llm import router_decide, skill_decide
from src.session.redis_store import SessionStore
from src.session.step1_cache import Step1Cache
from src.skill.executor import execute, SkillExecutionError
from src.skill.registry import get_registry
from src.skill.schema import Skill, PollBackend
from src.config import FEISHU_APP_ID, FEISHU_APP_SECRET

_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_MAX_AUTO_LOOKUPS_PER_TURN = 3  # 防 LLM 无限 lookup

# Per-user 串行化锁：同 user 的消息不并发处理，避免 submit 阻塞期间新消息进 LLM 瞎回
_user_locks: dict[str, asyncio.Lock] = {}


def _get_user_lock(user_id: str) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


# 完全匹配触发 retry 快路径（不进 LLM 直接重 submit）
_RETRY_PHRASES = {
    "再来一张", "再来一个", "再来", "再生成", "再画一张", "再做一张",
    "重新生成", "重做", "again",
}


def _is_retry(text: str) -> bool:
    t = text.strip().rstrip("。.!！?？ ").lower()
    return t in {p.lower() for p in _RETRY_PHRASES}


async def _maybe_inject_cached_step1(payload: dict, user_id: str) -> dict:
    """如果 payload 含 characters + actionDesc 且未指定 cachedStep1FileId，查 cache 命中就注入。"""
    if not isinstance(payload, dict) or payload.get("cachedStep1FileId"):
        return payload
    chars = payload.get("characters") or []
    action_desc = payload.get("actionDesc")
    if not chars or not action_desc:
        return payload
    cached = await _step1_cache.get(user_id, chars, action_desc)
    if cached:
        log.info(f"[CACHE HIT] step1 fileId={cached[:32]} chars={chars} actionDesc={action_desc[:40]!r}")
        return {**payload, "cachedStep1FileId": cached}
    return payload


async def _maybe_save_cached_step1(payload: dict, result, user_id: str) -> None:
    """从 poll result.metadata.intermediateImages.characterActionFileId 提取并存 cache。"""
    if not isinstance(payload, dict):
        return
    chars = payload.get("characters") or []
    action_desc = payload.get("actionDesc")
    if not chars or not action_desc:
        return
    file_id = (result.metadata or {}).get("intermediateImages", {}).get("characterActionFileId")
    if file_id:
        await _step1_cache.save(user_id, chars, action_desc, file_id)
        log.info(f"[CACHE SAVE] step1 fileId={file_id[:32]} chars={chars}")


def _enum_options_block(skill: Skill | None, param_name: str | None) -> str:
    """如果 param 是 skill 声明过的 enum 字段，返回追加到 reply 的可选值块；否则空串。

    兜底防 LLM 漏列选项；无论 LLM 是否自己列了，都追加一遍（确定性 > 简洁性）。
    """
    if skill is None or not param_name:
        return ""
    param = next((p for p in skill.params if p.name == param_name), None)
    if param is None or param.type != "enum" or not param.values:
        return ""
    lines = [f"\n\n📋 {param.prompt_to_user} 可选值（回复其中一个）："]
    lines.extend(f"- {v}" for v in param.values)
    return "\n".join(lines)


async def _reply_with_result(message_id: str, result) -> None:
    """统一处理 ExecuteResult 三种返回：binary 直接上传；url 下载再上传；text 文字回复。"""
    if result.kind == "binary":
        uploaded_key = await upload_image(_client, result.content_bytes)
        await reply_image(_client, message_id, uploaded_key)
    elif result.kind == "url":
        img_bytes = await download_url(result.result_url)
        uploaded_key = await upload_image(_client, img_bytes)
        await reply_image(_client, message_id, uploaded_key)
    else:
        await reply_text(_client, message_id, result.text or "完成")


def _load_lazy_resource(skill: Skill, action_name: str) -> str:
    """根据 skill.lazy_resources 配置加载资源文件内容。

    skill.lazy_resources = {
        'lookup_characters': 'xd-poster-gen-skill/references/characters.tsv',
        'lookup_options': 'xd-poster-gen-skill/references/options.md',
    }
    """
    rel_path = skill.lazy_resources.get(action_name)
    if not rel_path:
        return f"（{action_name} 没有配置 lazy_resources）"
    abs_path = _SKILLS_DIR / rel_path
    if not abs_path.exists():
        return f"（资源文件不存在: {rel_path}）"
    return abs_path.read_text(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_store = SessionStore()
_step1_cache = Step1Cache()
_client = build_client()

_OUT_OF_SCOPE = "我只能帮你：去除图片背景（抠图）。请告诉我你想做什么。"

# 飞书群里 @mention 在 content.text 里渲染为 "@_user_N" 占位符
_MENTION_PLACEHOLDER = re.compile(r"@_user_\d+\s*")


def _strip_mentions(text: str) -> str:
    """去掉群里 @mention 占位符（@_user_1 / @_user_2 ...），便于 LLM 理解纯意图。"""
    return _MENTION_PLACEHOLDER.sub("", text).strip()


def _normalize_message(msg_type: str, content: dict) -> tuple[str, str | None]:
    """归一化飞书消息为 (text, image_key)。post 类型会自动提取文字 + 第一张图。"""
    if msg_type == "text":
        return _strip_mentions(content.get("text", "")), None
    if msg_type == "image":
        return "", content.get("image_key")
    if msg_type == "post":
        text_parts: list[str] = []
        image_key: str | None = None
        for line in content.get("content", []):
            for tag in line:
                tag_type = tag.get("tag")
                if tag_type == "text":
                    text_parts.append(tag.get("text", ""))
                elif tag_type == "img" and image_key is None:
                    image_key = tag.get("image_key")
                # 'at' tag 直接忽略（在群聊里就是 @bot 本身）
        return " ".join(text_parts).strip(), image_key
    return "", None


async def _execute_image_skill(skill_name: str, image_key: str, message_id: str, user_id: str) -> None:
    """下载图片 → 调 skill → 上传结果 → 回图。统一的 image-skill 执行路径。"""
    skill = get_registry().get(skill_name)
    if skill is None:
        await reply_text(_client, message_id, f"未知 skill: {skill_name}")
        return
    image_param = next((p for p in skill.params if p.type == "image"), None)
    if image_param is None:
        await reply_text(_client, message_id, f"skill {skill_name} 不接受图片输入")
        return
    try:
        image_bytes = await download_image(_client, message_id, image_key)
        params = {image_param.name: ("frame.png", image_bytes, "image/png")}
        result = await execute(skill, params)
        await _reply_with_result(message_id, result)
    except Exception as e:
        log.exception("image skill execution failed")
        await reply_text(_client, message_id, f"处理失败：{e}")
    finally:
        await _store.clear(user_id)


def _single_image_skill() -> str | None:
    """如果只有一个接受 image 输入的 skill，返回它的名字；否则 None。"""
    skills = [s for s in get_registry().values() if any(p.type == "image" for p in s.params)]
    return skills[0].name if len(skills) == 1 else None


def on_message(data) -> None:
    """lark-oapi dispatcher 是同步的，把 async 任务挂到已运行的事件循环上。"""
    try:
        asyncio.ensure_future(_process(data))
    except Exception:
        log.exception("on_message scheduling failed")


async def _process(data) -> None:
    msg = data.event.message
    message_id = msg.message_id
    msg_type = msg.message_type
    chat_id = msg.chat_id
    chat_type = getattr(msg, "chat_type", "p2p")
    user_id = data.event.sender.sender_id.open_id
    content = json.loads(msg.content)
    log.info(f"[MSG] chat={chat_id} type={chat_type}/{msg_type} user={user_id} content={content}")

    # 同一 user 的消息串行化：submit 阻塞期间新消息排队等候
    async with _get_user_lock(user_id):
        await _process_locked(message_id, msg_type, content, user_id)


async def _process_locked(message_id: str, msg_type: str, content: dict, user_id: str) -> None:
    text, image_key = _normalize_message(msg_type, content)
    session = await _store.get(user_id)

    # 智能路径 1：用户一次性给了 text + image（典型场景：群里 @bot 配图说意图）
    if text and image_key:
        action = await decide(text, session.model_dump_json())
        log.info(f"[ACT] {action}")
        if action.action == "select_skill" and action.skill_name:
            await _execute_image_skill(action.skill_name, image_key, message_id, user_id)
            return
        # text 不构成 select_skill，回退到纯 image 自动路由
        single = _single_image_skill()
        if single:
            await _execute_image_skill(single, image_key, message_id, user_id)
            return

    # 智能路径 2：多轮对话中正在收图（state=collecting 且 pending=image）
    if image_key and session.state == "collecting" and session.pending_param:
        await _execute_image_skill(session.skill_name, image_key, message_id, user_id)
        return

    # 智能路径 3：用户裸发一张图，session 是 idle —— 若只有 1 个 image skill，直接执行
    if image_key:
        single = _single_image_skill()
        if single:
            await _execute_image_skill(single, image_key, message_id, user_id)
            return
        await reply_text(_client, message_id, "你想用这张图做什么？请告诉我。")
        return

    # 纯文字路径：Agentic Loop（支持 lazy lookup 自动 continue）
    if not text:
        await reply_text(_client, message_id, "请告诉我你想做什么，比如「帮我去白底」。")
        return

    await _agentic_loop(text, session, user_id, message_id)


async def _agentic_loop(text: str, session, user_id: str, message_id: str) -> None:
    """主决策循环：根据 mode 调 router/skill，自动 handle lookup，遇到终态退出。"""
    # Retry 快路径：session 已完成 + 用户说「再来一张」类短语 → 不进 LLM，直接重 submit
    if (
        session.completed
        and session.mode == "skill"
        and session.skill_name
        and session.collected_params
        and _is_retry(text)
    ):
        skill = get_registry().get(session.skill_name)
        if skill is not None:
            log.info(f"[RETRY] skill={session.skill_name} payload_keys={list(session.collected_params.keys())}")
            payload = await _maybe_inject_cached_step1(dict(session.collected_params), user_id)
            if isinstance(skill.api, PollBackend):
                await reply_text(_client, message_id, "✅ 已开始重新生成，预计 30-60 秒，请稍候…")
            try:
                result = await execute(skill, payload)
                await _reply_with_result(message_id, result)
                await _maybe_save_cached_step1(payload, result, user_id)
                # session.completed 保持 True，允许继续连续 retry
                await _store.save(user_id, session)
            except SkillExecutionError as e:
                await reply_text(_client, message_id, f"处理失败：{e}")
            except Exception as e:
                log.exception("retry submit failed")
                await reply_text(_client, message_id, f"处理失败：{e}")
            return

    lookup_count = 0
    current_text = text

    iter_count = 0
    while True:
        iter_count += 1
        log.info(f"[LOOP iter={iter_count} mode={session.mode} skill={session.skill_name} text={current_text[:60]!r}]")
        if session.mode == "router":
            action = await router_decide(current_text, session)
        else:
            skill = get_registry().get(session.skill_name)
            if skill is None:
                log.error(f"skill {session.skill_name} 不存在，回 router")
                session.mode = "router"
                session.skill_name = None
                await _store.save(user_id, session)
                continue
            action = await skill_decide(current_text, session, skill)
        log.info(f"[ACT mode={session.mode}] {action.action} skill={action.skill_name} updated={action.updated_params}")

        # 应用 LLM 声明的 updated_params
        if action.updated_params:
            session.collected_params.update(action.updated_params)

        # 自动 continue：lazy load 资源后再问 LLM
        if action.action in ("lookup_characters", "lookup_options"):
            lookup_count += 1
            if lookup_count > _MAX_AUTO_LOOKUPS_PER_TURN:
                log.warning(f"超过 {_MAX_AUTO_LOOKUPS_PER_TURN} 次 lookup，回退")
                await reply_text(_client, message_id, "处理超时，请重新描述需求。")
                await _store.clear(user_id)
                return
            skill = get_registry().get(session.skill_name)
            if skill is None:
                await reply_text(_client, message_id, "内部错误：skill 丢失")
                return
            resource = _load_lazy_resource(skill, action.action)
            session.loaded_resources[action.action] = resource
            await _store.save(user_id, session)
            # 保持原始 user text 不变（资源已经在 session.loaded_resources 里，
            # 下轮 skill_decide 会自动注入到 system prompt）
            continue

        # 终态 action：处理后退出循环
        if action.action == "out_of_scope":
            await reply_text(_client, message_id, _OUT_OF_SCOPE)
            await _store.clear(user_id)
            return

        if action.action == "reply":
            await reply_text(_client, message_id, action.message or "")
            await _store.save(user_id, session)
            return

        if action.action == "exit_skill":
            await reply_text(_client, message_id, action.message or "好的，需要其他帮助随时叫我。")
            await _store.clear(user_id)
            return

        if action.action == "ask_param":
            session.pending_param = action.param_name
            skill = get_registry().get(session.skill_name) if session.skill_name else None
            base_msg = action.message or "请提供参数。"
            full_msg = base_msg + _enum_options_block(skill, action.param_name)
            await reply_text(_client, message_id, full_msg)
            await _store.save(user_id, session)
            return

        if action.action == "select_skill":
            skill = get_registry().get(action.skill_name)
            if skill is None:
                await reply_text(_client, message_id, f"未知 skill: {action.skill_name}")
                return
            session.skill_name = action.skill_name

            if skill.system_prompt_core:
                # 复杂 skill：进入 Skill Mode，让 skill_decide 主导对话
                session.mode = "skill"
                session.loaded_resources = {}
                session.collected_params = {}
                session.initial_intent = text  # 记下原始意图，防止多轮后 LLM 忘
                await _store.save(user_id, session)
                current_text = f"[系统注入：用户刚选择了 skill `{skill.name}`。请按 SKILL.md 规则启动 brief 收集流程]"
                continue
            else:
                # 简单 skill：保持旧行为（按 prompt_to_user 问第一个 param）
                session.state = "collecting"  # 旧字段
                first_param = next((p for p in skill.params if p.required), None)
                if first_param:
                    session.pending_param = first_param.name
                    msg = first_param.prompt_to_user + _enum_options_block(skill, first_param.name)
                    await reply_text(_client, message_id, msg)
                    await _store.save(user_id, session)
                else:
                    result = await execute(skill, {})
                    await _reply_with_result(message_id, result)
                    await _store.clear(user_id)
                return

        if action.action == "submit":
            skill = get_registry().get(session.skill_name)
            payload = action.submit_payload or session.collected_params
            payload = await _maybe_inject_cached_step1(dict(payload) if isinstance(payload, dict) else payload, user_id)
            # 异步 skill 通常要 30-60s，先给用户一个"开始生成"信号
            if isinstance(skill.api, PollBackend):
                await reply_text(_client, message_id, "✅ 已开始生成，预计 30-60 秒，请稍候…")
            try:
                result = await execute(skill, payload)
                await _reply_with_result(message_id, result)
                await _maybe_save_cached_step1(payload, result, user_id)
                # 保留 session（同一 skill 下用户可能想「再来一张」「换个标题」）
                # 清掉 pending_param 和 loaded_resources 节省 token，但保留 skill_name + collected_params
                session.pending_param = None
                session.loaded_resources = {}
                # 把上次提交的 payload 也存进 collected_params，让下轮 LLM 看到
                if isinstance(payload, dict):
                    session.collected_params.update(payload)
                session.completed = True  # 触发 retry 快路径 + LLM completed 引导
                await _store.save(user_id, session)
            except SkillExecutionError as e:
                await reply_text(_client, message_id, f"处理失败：{e}")
                await _store.clear(user_id)
            except Exception as e:
                log.exception("submit failed")
                await reply_text(_client, message_id, f"处理失败：{e}")
                await _store.clear(user_id)
            return

        log.warning(f"未处理的 action: {action.action}")
        return


def main() -> None:
    get_registry()
    handler = build_event_handler(on_message)
    ws = lark.ws.Client(
        FEISHU_APP_ID,
        FEISHU_APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    log.info("starting WebSocket client")
    ws.start()


if __name__ == "__main__":
    main()
