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
from src.conversation.option_resolver import OptionResolver, build_resource_option_set
from src.conversation.options import OptionSet
from src.session.redis_store import SessionStore
from src.session.step1_cache import Step1Cache
from src.skill.actions import SkillActionError, SkillActionObservation, execute_skill_action
from src.skill.executor import ExecuteResult, execute, poll_existing_job, SkillExecutionError
from src.skill.registry import get_registry
from src.skill.schema import Skill, PollBackend, HttpResource
from src.http_client.allowlist import allowed_client
from src.config import FEISHU_APP_ID, FEISHU_APP_SECRET
import time

_MAX_AUTO_LOOKUPS_PER_TURN = 3  # 防 LLM 无限 lookup
_MAX_SKILL_ACTIONS_PER_TURN = 8  # 防 LLM 在单轮里无限调 skill action

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

_SKILL_CHITCHAT_PHRASES = {
    "你好", "您好", "hi", "hello", "哈喽", "嗨", "在吗",
    "好", "好的", "嗯", "嗯嗯", "ok", "收到",
    "谢谢", "感谢", "辛苦了", "这张不错", "不错",
}

_NUMBERED_REPLY_RE = re.compile(r"^\s*(?:选|选择|第)?\s*(\d{1,2})\s*(?:号|个)?\s*[。.!！?？]?\s*$")
_NUMBERED_OPTION_RE = re.compile(r"^\s*(\d{1,2})[.．、)]\s*(.+?)\s*$")
_OPTION_KEY_RE = re.compile(r"[（(]([A-Za-z0-9_-]+)[）)]")


def _matches_phrase(text: str, phrases: set[str]) -> bool:
    t = text.strip().rstrip("。.!！?？ ").lower()
    return t in {p.lower() for p in phrases}


def _is_retry(text: str) -> bool:
    return _matches_phrase(text, _RETRY_PHRASES)


def _is_skill_chitchat(text: str) -> bool:
    return _matches_phrase(text, _SKILL_CHITCHAT_PHRASES)


def _compact_text(text: str) -> str:
    return re.sub(r"[\s，,。.!！?？~～]", "", text).lower().replace("其它", "其他")


def _is_capability_question(text: str) -> bool:
    t = _compact_text(text)
    if not t:
        return False
    explicit = (
        "你能做什么",
        "能做什么",
        "可以做什么",
        "有什么功能",
        "哪些功能",
        "支持什么",
        "能帮我什么",
        "还能帮我什么",
    )
    if any(p in t for p in explicit):
        return True
    return ("还能" in t or "还可以" in t) and (
        "做什么" in t or "什么事" in t or "哪些" in t or "啥" in t
    )


def _is_completed_skill_continuation(text: str) -> bool:
    """Completed skill sessions only continue on explicit retry or edit intent."""
    t = _compact_text(text)
    if not t:
        return False
    markers = (
        "再来", "再生成", "再做", "再画", "重新生成", "重做",
        "改", "换", "调整", "变成", "设成",
        "标题", "主标题", "副标题", "文案", "比例", "构图",
        "角色", "动作", "颜色", "色调", "风格", "尺寸",
        "横版", "竖版", "方图", "手机",
    )
    return any(marker in t for marker in markers)


def _last_assistant_message(session) -> str:
    for msg in reversed(session.chat_history):
        if msg.get("role") == "assistant":
            return msg.get("content") or ""
    return ""


def _flatten_character_resources(data) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    result: list[dict] = []
    for key in ("characters", "npcCharacters", "animals", "seasonCharacters"):
        val = data.get(key)
        if isinstance(val, list):
            result.extend(item for item in val if isinstance(item, dict))
    return result


def _loaded_character_index(session) -> dict[str, dict]:
    raw = session.loaded_resources.get("lookup_characters")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    index: dict[str, dict] = {}
    for item in _flatten_character_resources(data):
        for field in ("key", "id", "name"):
            val = item.get(field)
            if isinstance(val, str) and val:
                index[val] = item
    return index


def _parse_numbered_options(message: str, resource_index: dict[str, dict]) -> dict[int, dict]:
    options: dict[int, dict] = {}
    for line in message.splitlines():
        match = _NUMBERED_OPTION_RE.match(line)
        if not match:
            continue
        idx = int(match.group(1))
        body = re.sub(r"[*`]", "", match.group(2)).strip()
        key_match = _OPTION_KEY_RE.search(body)
        key = key_match.group(1) if key_match else None
        name = re.split(r"[（(]|—|-|：|:", body, maxsplit=1)[0].strip()
        item = resource_index.get(key or "") or resource_index.get(name)
        if not item:
            continue
        resolved_key = item.get("key") or item.get("id") or key or name
        resolved_name = item.get("name") or name or resolved_key
        if isinstance(resolved_key, str) and resolved_key:
            options[idx] = {"key": resolved_key, "name": resolved_name}
    return options


def _legacy_option_set_from_last_message(session) -> OptionSet | None:
    message = _last_assistant_message(session)
    if not message:
        return None
    resource_index = _loaded_character_index(session)
    character_options = _parse_numbered_options(message, resource_index)
    if character_options:
        items = [
            {"key": value["key"], "name": value["name"]}
            for _, value in sorted(character_options.items())
        ]
        option_set = build_resource_option_set("characters", items)
        return option_set
    pending_param = getattr(session, "pending_param", None)
    if not pending_param:
        return None
    option_items = []
    for line in message.splitlines():
        match = _NUMBERED_OPTION_RE.match(line)
        if not match:
            continue
        idx = int(match.group(1))
        label = re.sub(r"[*`]", "", match.group(2)).strip()
        value = label.split()[0] if pending_param == "ratio" else label
        option_items.append({
            "index": idx,
            "label": label,
            "value": value,
            "param_name": pending_param,
        })
    if not option_items:
        return None
    return OptionSet(
        id=f"legacy:{pending_param}",
        param_name=pending_param,
        source="skill_runtime",
        items=option_items,
    )


def _resolve_numbered_character_reply(text: str, session) -> tuple[str, str] | None:
    """Resolve structured option replies, with legacy character parsing fallback."""
    if session.mode != "skill" or session.completed:
        return None

    structured = _resolve_last_options_reply(text, session)
    if structured is not None:
        return structured

    match = _NUMBERED_REPLY_RE.match(text)
    if not match:
        return None
    resource_index = _loaded_character_index(session)
    options = _parse_numbered_options(_last_assistant_message(session), resource_index)
    if not options:
        return None
    idx = int(match.group(1))
    if idx not in options:
        max_idx = max(options)
        return "error", f"编号 {idx} 超出范围，我目前列出的是 1-{max_idx}。请回复范围内编号，或回复“更多”查看后续角色。"
    selected = options[idx]
    session.collected_params["characters"] = [selected["key"]]
    prompt = (
        f"[系统已解析用户编号选择：用户回复编号 {idx}，对应角色 "
        f"{selected['name']}（key={selected['key']}）。"
        f"characters 已更新为 [\"{selected['key']}\"]. 请继续收集 actionDesc，"
        f"如果 actionDesc 已有则继续按 SKILL.md 执行下一步。]"
    )
    return "resolved", prompt


def _resolve_last_options_reply(text: str, session) -> tuple[str, str] | None:
    raw_options = getattr(session, "last_options", None)
    if raw_options is None:
        raw_options = _legacy_option_set_from_last_message(session)
        if raw_options is None:
            return None
        session.last_options = raw_options
    option_set = raw_options if isinstance(raw_options, OptionSet) else OptionSet.model_validate(raw_options)
    result = OptionResolver().resolve(text, option_set)
    if result.status == "no_match" and not _NUMBERED_REPLY_RE.match(text):
        return None
    if result.status in {"expired", "out_of_range", "no_match", "page"}:
        if result.status == "page":
            session.last_options = result.option_set
        return "error", result.message
    if result.status != "matched" or result.item is None:
        return None
    values = result.values if option_set.allow_multi else [result.item.value]
    session.collected_params[option_set.param_name] = values if option_set.allow_multi else values[0]
    prompt = (
        f"[系统已解析用户选项：用户回复编号 {result.item.index}，对应参数 `{option_set.param_name}`，"
        f"值为 {json.dumps(session.collected_params[option_set.param_name], ensure_ascii=False)}。"
        "请继续按 SKILL.md 执行下一步。]"
    )
    return "resolved", prompt


_HISTORY_MAX_TURNS = 10  # 最近 10 条（5 轮 user+assistant）
_HISTORY_MAX_CHAR = 800  # 单条 truncate 防 context 撑爆


def _append_history(session, role: str, content: str) -> None:
    """把一条 message 加到 session.chat_history，自动 truncate + 滚动保留最近 N 条。"""
    if not content:
        return
    if len(content) > _HISTORY_MAX_CHAR:
        content = content[:_HISTORY_MAX_CHAR] + "...(truncated)"
    session.chat_history.append({"role": role, "content": content})
    # 只留最近 N 条
    if len(session.chat_history) > _HISTORY_MAX_TURNS:
        session.chat_history = session.chat_history[-_HISTORY_MAX_TURNS:]


def _friendly_skill_error(e: Exception) -> str:
    """把后端技术错误转成用户友好提示，HTTP 类错误带上 URL + 状态码方便定位。"""
    import httpx

    msg = str(e)
    if "轮询超时" in msg or "timeout" in msg.lower():
        return "⏰ 生成超时，后端可能繁忙。可以说「再来一张」重试，或换个角色/动作试试。"
    if "submit 成功但缺" in msg or "完成但取结果失败" in msg:
        return "⚠️ 后端返回了意外格式，已记录。请稍后重试，或换个简单一点的需求。"
    if "任务失败" in msg or "failed" in msg.lower():
        return f"❌ 后端处理失败：{msg.split('：', 1)[-1][:80]}\n可以试试换个角色/动作。"
    if isinstance(e, httpx.HTTPStatusError):
        url = str(e.request.url)
        code = e.response.status_code
        return (
            f"⚠️ 后端 HTTP {code}：`{url}`\n"
            f"通常是 manifest.yaml 里 base_url / submit_path 指错了端口（看 docs/L20-1-SERVICES.md 端口表），"
            f"或目标服务挂了。"
        )
    if isinstance(e, (httpx.ConnectError, httpx.ReadError, httpx.NetworkError)):
        return f"⚠️ 连不上后端：{type(e).__name__}。可能服务挂了，让维护者看下 toolbox 子工具是否在跑。"
    # 其他（未知异常）
    return f"⚠️ 处理失败（{type(e).__name__}），稍后再试一次。"


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


async def _send_skill_action_artifact(message_id: str, obs: SkillActionObservation) -> None:
    """If a skill action returned image bytes, send them immediately as an artifact."""
    if obs.content_bytes is None:
        return
    await _reply_with_result(message_id, ExecuteResult(kind="binary", content_bytes=obs.content_bytes))
    obs.artifact["sent_to_user"] = True


def _extract_image_file_id(data) -> str | None:
    """Find a toolbox fileId in common image-generation response shapes."""
    if not isinstance(data, dict):
        return None
    file_id = data.get("fileId")
    if isinstance(file_id, str) and file_id:
        return file_id
    images = data.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            file_id = first.get("fileId")
            if isinstance(file_id, str) and file_id:
                return file_id
    return None


def _extract_job_id(data, skill: Skill) -> str | None:
    if not isinstance(data, dict) or not isinstance(skill.api, PollBackend):
        return None
    candidates = [skill.api.job_id_field, "v2JobId", "jobId", "job_id"]
    for key in candidates:
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return None


async def _maybe_send_skill_image_by_file_id(skill: Skill, message_id: str, obs: SkillActionObservation) -> None:
    """Deterministically fetch/send image previews when an action returns only fileId."""
    if obs.status != "success" or obs.content_bytes is not None or obs.artifact.get("sent_to_user"):
        return
    file_id = _extract_image_file_id(obs.data)
    if not file_id:
        return
    try:
        image_obs = await execute_skill_action(skill, "get_image", {"path_params": {"fileId": file_id}})
    except SkillActionError:
        return
    except Exception:
        log.exception("failed to fetch skill image by fileId")
        return
    await _send_skill_action_artifact(message_id, image_obs)
    if image_obs.artifact.get("sent_to_user"):
        obs.artifact["sent_to_user"] = True
        obs.artifact["image_fileId"] = file_id


async def _send_execute_result(message_id: str, result: ExecuteResult, skill: Skill) -> bool:
    if result.kind == "url" and not result.result_url:
        file_id = _extract_image_file_id(result.metadata)
        if file_id:
            obs = await execute_skill_action(skill, "get_image", {"path_params": {"fileId": file_id}})
            await _send_skill_action_artifact(message_id, obs)
            return bool(obs.artifact.get("sent_to_user"))
    await _reply_with_result(message_id, result)
    return True


async def _maybe_poll_skill_job(skill: Skill, message_id: str, obs: SkillActionObservation) -> bool:
    job_id = _extract_job_id(obs.data, skill)
    if not job_id:
        return False
    try:
        result = await poll_existing_job(skill, job_id)
        await _send_execute_result(message_id, result, skill)
        obs.artifact["job_id"] = job_id
        obs.artifact["polled_to_completion"] = True
        obs.artifact["sent_to_user"] = True
        return True
    except SkillExecutionError as e:
        await reply_text(_client, message_id, _friendly_skill_error(e))
        obs.artifact["job_id"] = job_id
        obs.artifact["poll_failed"] = str(e)
        return True
    except Exception as e:
        log.exception("failed to poll skill job")
        await reply_text(_client, message_id, _friendly_skill_error(e))
        obs.artifact["job_id"] = job_id
        obs.artifact["poll_failed"] = f"{type(e).__name__}: {e}"
        return True


class LazyResourceError(Exception):
    """lazy_resource 配置或文件缺失。区分于"数据加载成功但内容为空"。"""


# HTTP 资源缓存：url → (fetched_at_ts, content)
_http_resource_cache: dict[str, tuple[float, str]] = {}


async def _load_lazy_resource(skill: Skill, action_name: str) -> str:
    """根据 skill.lazy_resources 配置加载资源内容（文件或 HTTP）。

    支持两种类型：
    - str（文件路径，registry 已转绝对）：直接 read_text
    - HttpResource（HTTP 端点，registry 已注册到 allowlist）：GET/POST 拉，带 TTL 缓存

    资源未配置 / 文件不存在 / HTTP 失败均抛 LazyResourceError——
    LLM 把错误字符串当"已加载"会无法判断而陷入重复 lookup 死循环。
    """
    resource = skill.lazy_resources.get(action_name)
    if resource is None:
        raise LazyResourceError(f"{action_name} 未在 manifest.yaml 配置 lazy_resources")

    if isinstance(resource, str):
        abs_path = Path(resource)
        if not abs_path.exists():
            raise LazyResourceError(f"资源文件不存在: {resource}")
        return abs_path.read_text(encoding="utf-8")

    if isinstance(resource, HttpResource):
        return await _fetch_http_resource(resource)

    raise LazyResourceError(f"未知 lazy_resource 类型: {type(resource).__name__}")


async def _fetch_http_resource(res: HttpResource) -> str:
    """HTTP 拉取资源，带内存 TTL 缓存避免每轮都打后端。"""
    now = time.time()
    cached = _http_resource_cache.get(res.url)
    if cached and res.cache_ttl_sec > 0 and (now - cached[0]) < res.cache_ttl_sec:
        return cached[1]
    try:
        async with allowed_client() as client:
            resp = await client.request(res.method, res.url, timeout=10.0)
            resp.raise_for_status()
            content = resp.text
    except Exception as e:
        raise LazyResourceError(f"HTTP 拉取失败 {res.url}: {type(e).__name__}: {e}") from e
    if res.cache_ttl_sec > 0:
        _http_resource_cache[res.url] = (now, content)
    return content

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_store = SessionStore()
_step1_cache = Step1Cache()
_client = build_client()

def _out_of_scope_msg() -> str:
    """动态列出当前所有可用 skill，不要硬编码（避免新接 skill 时忘改）。"""
    skills = get_registry().values()
    if not skills:
        return "我目前还没有可用的工具。"
    lines = ["我目前可以帮你做这些事："]
    for s in skills:
        lines.append(f"- {s.description}")
    lines.append("\n请告诉我你想做哪个？")
    return "\n".join(lines)


def _completion_followup_msg() -> str:
    return "已完成。要继续这个任务、调整哪里，还是换别的需求？"


def _completed_capability_msg() -> str:
    return f"{_completion_followup_msg()}\n\n{_out_of_scope_msg()}"


def _completed_boundary_msg() -> str:
    return f"我主要处理 AIGC 工具任务。\n\n{_completion_followup_msg()}"


async def _reply_completion_followup(message_id: str, session) -> None:
    msg = _completion_followup_msg()
    await reply_text(_client, message_id, msg)
    _append_history(session, "assistant", msg)


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
        await reply_text(_client, message_id, "已完成。还要继续处理另一张图，还是换别的需求？")
    except Exception as e:
        log.exception("image skill execution failed")
        await reply_text(_client, message_id, _friendly_skill_error(e))
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
        await reply_text(_client, message_id, _out_of_scope_msg())
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
                await _reply_completion_followup(message_id, session)
                # session.completed 保持 True，允许继续连续 retry
                await _store.save(user_id, session)
            except SkillExecutionError as e:
                await reply_text(_client, message_id, _friendly_skill_error(e))
                # 保留 session，用户可继续 retry 或 adjust
            except Exception as e:
                log.exception("retry submit failed")
                await reply_text(_client, message_id, _friendly_skill_error(e))
            return

    if session.completed and session.mode == "skill" and _is_capability_question(text):
        msg = _completed_capability_msg()
        _append_history(session, "user", text)
        _append_history(session, "assistant", msg)
        await reply_text(_client, message_id, msg)
        await _store.save(user_id, session)
        return

    if (
        session.completed
        and session.mode == "skill"
        and not _is_completed_skill_continuation(text)
    ):
        msg = _completed_boundary_msg()
        _append_history(session, "user", text)
        _append_history(session, "assistant", msg)
        await reply_text(_client, message_id, msg)
        await _store.save(user_id, session)
        return

    # Skill mode 下的问候/含糊短句不要交给 Skill LLM，避免误判为继续 submit。
    if (
        session.mode == "skill"
        and _is_skill_chitchat(text)
    ):
        msg = "我还在当前任务里。要继续、调整参数，还是换别的需求？"
        if session.completed:
            msg = "我还在上一个任务里。要再做一张相同的、调整哪里，还是换别的需求？"
        _append_history(session, "user", text)
        _append_history(session, "assistant", msg)
        await reply_text(_client, message_id, msg)
        await _store.save(user_id, session)
        return

    numbered_reply = _resolve_numbered_character_reply(text, session)
    if numbered_reply is not None:
        status, resolved_text = numbered_reply
        if status == "error":
            _append_history(session, "user", text)
            _append_history(session, "assistant", resolved_text)
            await reply_text(_client, message_id, resolved_text)
            await _store.save(user_id, session)
            return
        text = resolved_text

    lookup_count = 0
    skill_action_count = 0
    current_text = text
    # 把本轮用户原始输入加进 history（仅一次，loop 内部 lookup continue 时不重复加）
    _append_history(session, "user", text)

    iter_count = 0
    while True:
        iter_count += 1
        log.info(f"[LOOP iter={iter_count} mode={session.mode} skill={session.skill_name} text={current_text[:60]!r}]")
        try:
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
        except Exception as e:
            log.exception("LLM call failed")
            await reply_text(_client, message_id, f"⚠️ AI 暂时不可用（{type(e).__name__}），稍后再试一次。")
            # session 保留，用户可以直接重发
            return
        log.info(
            f"[ACT mode={session.mode}] {action.action} skill={action.skill_name} "
            f"param_name={action.param_name} action_name={action.action_name} updated={action.updated_params}"
        )

        # 应用 LLM 声明的 updated_params
        if isinstance(action.updated_params, dict) and action.updated_params:
            session.collected_params.update(action.updated_params)

        # 自动 continue：lazy load 资源后再问 LLM
        if action.action in ("lookup_characters", "lookup_options"):
            if action.action not in session.loaded_resources:
                skill = get_registry().get(session.skill_name)
                if skill is None:
                    await reply_text(_client, message_id, "内部错误：skill 丢失")
                    return
                try:
                    resource = await _load_lazy_resource(skill, action.action)
                except LazyResourceError as e:
                    # 资源配置缺失立即报错，不让 LLM 不停 retry
                    log.error(f"[LAZY] skill={skill.name} {action.action} 失败: {e}")
                    await reply_text(
                        _client, message_id,
                        f"⚠️ 技能 `{skill.name}` 缺少 {action.action} 数据（{e}），请联系 skill 维护者补全 manifest 和 references。",
                    )
                    await _store.clear(user_id)
                    return
                session.loaded_resources[action.action] = resource
            # lookup 后把 current_text 换成"继续"信号。
            # 原因：若保持原始"[系统注入：用户刚选择了 skill...]"，LLM 每轮都判断为
            # 新开始而重复 lookup。换成明确的继续指令，LLM 才能判断"上步已完成"。
            current_text = f"[{action.action} 已完成，数据已在已加载资源中，请继续下一步]"
            await _store.save(user_id, session)
            lookup_count += 1
            if lookup_count > _MAX_AUTO_LOOKUPS_PER_TURN:
                log.warning(f"超过 {_MAX_AUTO_LOOKUPS_PER_TURN} 次 lookup，回退")
                await reply_text(_client, message_id, "处理超时，请重新描述需求。")
                await _store.clear(user_id)
                return
            continue

        # 终态 action：处理后退出循环
        if action.action == "out_of_scope":
            await reply_text(_client, message_id, _out_of_scope_msg())
            await _store.clear(user_id)
            return

        if action.action == "reply":
            msg = action.message or ""
            await reply_text(_client, message_id, msg)
            _append_history(session, "assistant", msg)
            await _store.save(user_id, session)
            return

        if action.action == "exit_skill":
            await reply_text(_client, message_id, action.message or "好的，需要其他帮助随时叫我。")
            await _store.clear(user_id)
            return

        if action.action == "ask_param":
            if action.param_name and action.param_name in session.collected_params:
                session.pending_param = None
                current_text = (
                    f"[参数 `{action.param_name}` 已收集为 "
                    f"{json.dumps(session.collected_params[action.param_name], ensure_ascii=False)}，"
                    "请继续下一步，不要重复询问该参数。]"
                )
                await _store.save(user_id, session)
                continue
            session.pending_param = action.param_name
            skill = get_registry().get(session.skill_name) if session.skill_name else None
            base_msg = action.message or "请提供参数。"
            full_msg = base_msg + _enum_options_block(skill, action.param_name)
            await reply_text(_client, message_id, full_msg)
            _append_history(session, "assistant", full_msg)
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

        if action.action == "call_skill_action":
            skill = get_registry().get(session.skill_name)
            if skill is None:
                await reply_text(_client, message_id, "内部错误：skill 丢失")
                return

            skill_action_count += 1
            if skill_action_count > _MAX_SKILL_ACTIONS_PER_TURN:
                await reply_text(_client, message_id, "处理步骤过多，请重新描述需求或稍后再试。")
                await _store.save(user_id, session)
                return

            try:
                obs = await execute_skill_action(skill, action.action_name, action.action_params)
            except SkillActionError as e:
                obs = SkillActionObservation(status="error", summary=str(e))
            except Exception as e:
                log.exception("skill action failed")
                obs = SkillActionObservation(
                    status="error",
                    summary=f"{action.action_name or 'unknown'} 调用异常: {type(e).__name__}: {e}",
                )

            await _send_skill_action_artifact(message_id, obs)
            await _maybe_send_skill_image_by_file_id(skill, message_id, obs)
            if await _maybe_poll_skill_job(skill, message_id, obs):
                session.pending_param = None
                session.loaded_resources = {}
                if obs.artifact.get("polled_to_completion"):
                    session.completed = True
                    await _reply_completion_followup(message_id, session)
                await _store.save(user_id, session)
                return
            current_text = (
                f"[skill action `{action.action_name}` 已执行，observation 如下。"
                f"请读取结果，保存关键 fileId/jobId 到 updated_params，并按 SKILL.md 继续下一步。]\n"
                f"{obs.for_prompt()}"
            )
            await _store.save(user_id, session)
            continue

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
                await _reply_completion_followup(message_id, session)
                await _store.save(user_id, session)
            except SkillExecutionError as e:
                await reply_text(_client, message_id, _friendly_skill_error(e))
                # 保留 session 让用户能 retry / adjust，不 clear
                await _store.save(user_id, session)
            except Exception as e:
                log.exception("submit failed")
                await reply_text(_client, message_id, _friendly_skill_error(e))
                await _store.save(user_id, session)
            return

        log.warning(f"未处理的 action: {action.action}")
        return


def main() -> None:
    skills = get_registry()
    # 启动健康检查：ping 每个 skill 的 base_url，提前发现 manifest 端口写错。
    # 失败不阻断启动（其他 skill 仍可用），只在日志报警。
    try:
        from src.skill.health import health_check_skills
        asyncio.run(health_check_skills(skills))
    except Exception:
        log.exception("[HEALTH] startup check failed (non-fatal)")
    # 启动 skill 文件 watcher，同事 push skill + cron 拉到本地后自动 hot-reload，不重启 bot
    try:
        from src.skill.watcher import start_skills_watcher
        start_skills_watcher()
    except Exception:
        log.exception("[WATCHER] failed to start, continuing without hot-reload")
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
