import os
import re

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False

    new_content = content
    
    # 1. CSS variables and class names
    new_content = re.sub(r'--cyber-accent-green', '--cyber-accent-purple', new_content)
    
    # Catch-all for green in CSS vars
    new_content = re.sub(r'--([a-zA-Z0-9_-]*?)green([a-zA-Z0-9_-]*)', r'--\g<1>purple\g<2>', new_content)
    new_content = re.sub(r'--([a-zA-Z0-9_-]*?)Green([a-zA-Z0-9_-]*)', r'--\g<1>Purple\g<2>', new_content)
    
    # Tailwind/CSS class names containing green (e.g., text-green-500, bg-green)
    new_content = re.sub(r'\b([a-zA-Z0-9_]+)-green([a-zA-Z0-9_-]*)\b', r'\1-purple\2', new_content)
    new_content = re.sub(r'\bgreen-([a-zA-Z0-9_-]+)\b', r'purple-\1', new_content)
    
    # CamelCase green (e.g. isGreen)
    new_content = re.sub(r'([a-z])Green([A-Z\b]?)', r'\1Purple\2', new_content)
    
    # Isolated 'green' or 'Green' or 'GREEN'
    new_content = re.sub(r'\bgreen\b', 'purple', new_content)
    new_content = re.sub(r'\bGreen\b', 'Purple', new_content)
    new_content = re.sub(r'\bGREEN\b', 'PURPLE', new_content)
    
    # 2. Hex colors
    new_content = re.sub(r'(?i)#00ff41\b', '#a082ff', new_content)
    new_content = re.sub(r'(?i)#0f4\b', '#a082ff', new_content)
    new_content = re.sub(r'(?i)#00ff00\b', '#a082ff', new_content)
    new_content = re.sub(r'(?i)#0f0\b', '#a082ff', new_content)
    new_content = re.sub(r'(?i)#22c55e\b', '#a082ff', new_content)
    new_content = re.sub(r'(?i)#4caf50\b', '#a082ff', new_content)
    
    # 3. rgb/rgba colors
    # RGBA
    new_content = re.sub(r'(?i)rgba\(\s*0\s*,\s*255\s*,\s*65\s*,\s*(.*?)\)', r'rgba(160, 130, 255, \1)', new_content)
    new_content = re.sub(r'(?i)rgba\(\s*0\s*,\s*255\s*,\s*0\s*,\s*(.*?)\)', r'rgba(160, 130, 255, \1)', new_content)
    new_content = re.sub(r'(?i)rgba\(\s*34\s*,\s*197\s*,\s*94\s*,\s*(.*?)\)', r'rgba(160, 130, 255, \1)', new_content)
    new_content = re.sub(r'(?i)rgba\(\s*76\s*,\s*175\s*,\s*80\s*,\s*(.*?)\)', r'rgba(160, 130, 255, \1)', new_content)
    
    # RGB
    new_content = re.sub(r'(?i)rgb\(\s*0\s*,\s*255\s*,\s*65\s*\)', 'rgb(160, 130, 255)', new_content)
    new_content = re.sub(r'(?i)rgb\(\s*0\s*,\s*255\s*,\s*0\s*\)', 'rgb(160, 130, 255)', new_content)
    new_content = re.sub(r'(?i)rgb\(\s*34\s*,\s*197\s*,\s*94\s*\)', 'rgb(160, 130, 255)', new_content)
    new_content = re.sub(r'(?i)rgb\(\s*76\s*,\s*175\s*,\s*80\s*\)', 'rgb(160, 130, 255)', new_content)

    if new_content != content:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated: {filepath}")
            return True
        except Exception as e:
            print(f"Error writing {filepath}: {e}")
    return False

def main():
    target_dir = os.path.join('frontend', 'src', 'renderer')
    if not os.path.exists(target_dir):
        print(f"Target directory {target_dir} does not exist.")
        return

    updated_files = 0
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith(('.css', '.tsx', '.ts')):
                filepath = os.path.join(root, file)
                if process_file(filepath):
                    updated_files += 1
                    
    print(f"Total files updated: {updated_files}")

if __name__ == '__main__':
    main()
