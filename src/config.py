from dotenv import load_dotenv
import os

from src.runtime_dry_run import RuntimeDryRunConfig

load_dotenv()

FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]

LLM_BASE_URL = os.environ["LLM_BASE_URL"]
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "dummy")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TOOLBOX_BASE_URL = os.environ.get("TOOLBOX_BASE_URL", "http://localhost:80")
ENV = os.environ.get("ENV", "development")
AGENT_RUNTIME_DRY_RUN = RuntimeDryRunConfig.from_env(os.environ)

# Skill 仓库路径（含 manifest.yaml 的子目录）
# dev 默认 ./skills（本地 git clone XD-AIGC-skills 到此）
# prod 通过 docker -v mount /AIGC_Group/XD-AIGC-skills/skills 进容器 /app/skills
SKILLS_DIR = os.environ.get("SKILLS_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills"))
