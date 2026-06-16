import json
from jinja2 import Environment, Undefined

def finalize_value(value):
    if value is None or isinstance(value, Undefined):
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return value

env = Environment(finalize=finalize_value)

template = """
Direct output: {{ my_list }}
Loop output:
{% for item in my_list %}
- {{ item.name }}
{% endfor %}
"""

variables = {
    "my_list": [{"name": "A"}, {"name": "B"}]
}

print(env.from_string(template).render(**variables))
