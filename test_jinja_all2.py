import os
import glob
from jinja2 import Environment

env = Environment()
has_error = False
for filepath in glob.glob("backend/ai-service/app/prompt/**/*.j2", recursive=True):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        env.parse(content)
    except Exception as e:
        print(f"Error in {filepath}: {e}")
        has_error = True

if not has_error:
    print("All templates parsed successfully!")
