"""Central configuration, read from environment variables (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Any provider string accepted by langchain's init_chat_model, e.g.
#   anthropic:claude-sonnet-5-5   openai:gpt-4.1   google_genai:gemini-2.5-pro
MODEL = os.getenv("SUPPORT_MODEL", "anthropic:claude-sonnet-5-5")
# A cheaper/faster model is fine for intent classification.
TRIAGE_MODEL = os.getenv("SUPPORT_TRIAGE_MODEL", MODEL)

DB_PATH = Path(os.getenv("SUPPORT_DB_PATH", BASE_DIR / "data" / "support.db"))

# Guardrails
MAX_HANDOFFS_PER_TURN = int(os.getenv("SUPPORT_MAX_HANDOFFS", "3"))
MAX_TOOL_STEPS_PER_AGENT = int(os.getenv("SUPPORT_MAX_TOOL_STEPS", "8"))

# Business policy (used by billing tools, not just prompts — policy is enforced in code)
REFUND_AUTO_APPROVE_LIMIT = float(os.getenv("SUPPORT_REFUND_LIMIT", "50"))
REFUND_WINDOW_DAYS = int(os.getenv("SUPPORT_REFUND_WINDOW_DAYS", "30"))
RETURN_WINDOW_DAYS = int(os.getenv("SUPPORT_RETURN_WINDOW_DAYS", "30"))
