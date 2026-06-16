import asyncio
from app.prompt.types import render_template

template = """
* 允许的 primary_intent: [ {{ PRIMARY_INTENTS | join(', ') }} ]
* 允许的 route_strategy: [ {{ ROUTE_STRATEGIES | join(', ') }} ]
"""

variables = {
    "PRIMARY_INTENTS": ["A", "B"]
}

print("Result:")
print(render_template(template, variables))
