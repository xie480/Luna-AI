import json
from jinja2 import Environment, Undefined

def finalize_value(value):
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

env = Environment(finalize=finalize_value)

template = """
1: {{ PRIMARY_INTENTS }}
2: {{ PRIMARY_INTENTS | join(', ') }}
"""

variables = {
    "PRIMARY_INTENTS": ["MODIFY_PLAN", "GREETING"]
}

print("Result:", env.from_string(template).render(**variables))
