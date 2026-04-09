from langchain_openai import ChatOpenAI
from langchain.messages import SystemMessage

from typing import Dict
from pathlib import Path
from datetime import datetime
import jinja2
from jinja2 import Template

class BaseAgent:
    def __init__(
            self,
            model: str = 'gpt-5-mini',
            temperature: float = 0.7,
            max_tokens: int = None,
            streaming: bool = False,
            openai_api_key: str = ""
    ):
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            api_key=openai_api_key
        )
        self.instruction_prompt: Dict[str, jinja2.Template] = {}

    def _load_prompts(self, prompts_dir: str):
        prompts = {}
        path = Path(prompts_dir)

        if not path.exists():
            raise FileNotFoundError(f"Prompt directory not found at {prompts_dir}")

        for file_path in path.glob("*.md"):
            # Uses the filename (without .md) as the dictionary key
            key = file_path.stem
            with open(file_path, "r", encoding="utf-8") as f:
                prompts[key] = Template(f.read())

        return prompts

    def _build_system_message(self, content: str) -> SystemMessage:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return SystemMessage(f"Current date and time: {now}\n\n{content}")