from dotenv import load_dotenv
import os

load_dotenv()

FEISHU_APP_ID = os.environ["FEISHU_APP_ID"]
FEISHU_APP_SECRET = os.environ["FEISHU_APP_SECRET"]

LLM_BASE_URL = os.environ["LLM_BASE_URL"]
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "dummy")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TOOLBOX_BASE_URL = os.environ.get("TOOLBOX_BASE_URL", "http://localhost:80")
ENV = os.environ.get("ENV", "development")
