import asyncio
import json
from app.prompt.types import render_template

template = """
{% if TTS_LANGUAGE == "ja" %}
{"check":"[感知与记忆]...","thought":"...","emotion":"<枚举情绪>","reply":"<回复内容>","replay_translation":"<日语的、自然的、口语化的翻译>"}
{% else %}
{"check":"[感知与记忆]...","thought":"...","emotion":"<枚举情绪>","reply":"<回复内容>"}
{% endif %}
"""

variables = {"TTS_LANGUAGE": "ja"}
print("JA:", json.dumps(render_template(template, variables)))

variables = {"TTS_LANGUAGE": "zh"}
print("ZH:", json.dumps(render_template(template, variables)))

variables = {}
print("Missing:", json.dumps(render_template(template, variables)))
