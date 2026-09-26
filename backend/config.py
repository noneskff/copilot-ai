import os
from dotenv import load_dotenv

load_dotenv()

BOB_MODE: str = os.getenv("BOB_MODE", "mock")          # "mock" or "real"
BOBSHELL_API_KEY: str = os.getenv("BOBSHELL_API_KEY", "")
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./codepilot.db")
WORKSPACE_DIR: str = os.getenv("WORKSPACE_DIR", "./workspaces")
