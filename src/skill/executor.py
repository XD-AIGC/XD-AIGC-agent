from src.skill.schema import Skill
from src.http_client.allowlist import allowed_client
from src.config import TOOLBOX_BASE_URL


async def execute(skill: Skill, params: dict) -> bytes:
    url = TOOLBOX_BASE_URL.rstrip("/") + skill.api.endpoint_path
    async with allowed_client() as client:
        if skill.api.content_type == "multipart/form-data":
            resp = await client.request(skill.api.method, url, files=params)
        else:
            resp = await client.request(skill.api.method, url, json=params)
        resp.raise_for_status()
        return resp.content
