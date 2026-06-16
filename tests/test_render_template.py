import sys
import os

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "backend/ai-service")))

from app.prompt.types import render_template

template = "{% for skill in CANDIDATE_SKILLS %}{{ skill.name }} - {{ skill.description }}\n{% endfor %}"
variables = {
    "CANDIDATE_SKILLS": [
        {"name": "Skill A", "description": "A description"},
        {"name": "Skill B", "description": "B description"}
    ]
}

print(render_template(template, variables))
