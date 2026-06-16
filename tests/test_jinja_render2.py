import json
from typing import Any, Dict
from jinja2 import Environment, Undefined

def finalize_value(value: Any) -> Any:
    if value is None or isinstance(value, Undefined):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)

def render_template(template: str, variables: Dict[str, Any]) -> str:
    env = Environment(finalize=finalize_value)
    try:
        tmpl = env.from_string(template)
        return tmpl.render(**variables)
    except Exception as e:
        print(f"Jinja2 error: {e}")
        return template

runtime_template = """
* 允许的 primary_intent: [ {{ PRIMARY_INTENTS | join(', ') }} ]
* 允许的 category: [ {{ CATEGORIES | join(', ') }} ]
"""

variables = {
    "PRIMARY_INTENTS": ["MODIFY_PLAN", "GREETING"],
    "CATEGORIES": ["TASK_MANAGEMENT", "CHAT"]
}

print("Rendered:", render_template(runtime_template, variables))
