import os
import shutil
from pathlib import Path

def is_test_file(file_path):
    name = file_path.name
    # Python tests
    if name.startswith('test') and name.endswith('.py'):
        return True
    if name.endswith('_test.py'):
        return True
    # Go tests
    if name.endswith('_test.go'):
        return True
    # JS/TS tests
    if name.endswith('.test.ts') or name.endswith('.test.js') or name.endswith('.spec.ts') or name.endswith('.spec.js'):
        return True
    if name.startswith('test') and name.endswith('.js'):
        return True
    return False

def main():
    root_dir = Path('.')
    test_dir = root_dir / 'test'
    
    if not test_dir.exists():
        test_dir.mkdir()
        
    report = []
    
    for filepath in root_dir.rglob('*'):
        if not filepath.is_file():
            continue
            
        # Skip files already in test dir
        if filepath.parts[0] == 'test':
            continue
                
        # Skip hidden directories like .git
        if any(part.startswith('.') and part != '.' for part in filepath.parts):
            continue
            
        if 'node_modules' in filepath.parts:
            continue
            
        if is_test_file(filepath):
            # Calculate target path
            rel_path = filepath.relative_to(root_dir)
            target_path = test_dir / rel_path
            
            # Create target directory
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Move file
            shutil.move(str(filepath), str(target_path))
            
            report.append(f"{rel_path} -> {target_path.relative_to(root_dir)}")
            
    print("Migration Report:")
    for line in report:
        print(line)
        
if __name__ == '__main__':
    main()
