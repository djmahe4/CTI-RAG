import sys
import os
import tokenize
import io
import argostranslate.translate
import subprocess
import re
import argparse

def translate_text(text):
    """Translates text from Chinese to English using argostranslate."""
    if not any('\u4e00' <= char <= '\u9fff' for char in text):
        return text
    try:
        translated = argostranslate.translate.translate(text, "zh", "en")
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return text

def translate_python_file(filepath):
    """Translates comments and docstrings in a Python file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    new_lines = []
    for line in lines:
        if '#' in line:
            parts = line.split('#', 1)
            code_part = parts[0]
            comment_part = parts[1]
            if any('\u4e00' <= char <= '\u9fff' for char in comment_part):
                translated_comment = translate_text(comment_part.strip())
                new_lines.append(f"{code_part}# {translated_comment}\n")
            else:
                new_lines.append(line)
        elif any('\u4e00' <= char <= '\u9fff' for char in line):
            # Simple regex for Chinese segments in strings
            translated_line = re.sub(r'[\u4e00-\u9fff]+', lambda m: translate_text(m.group(0)), line)
            new_lines.append(translated_line)
        else:
            new_lines.append(line)
    return "".join(new_lines)

def translate_markdown_file(filepath):
    """Translates a Markdown file, preserving code blocks."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    parts = re.split(r'(```.*?```)', content, flags=re.DOTALL)
    new_parts = []
    for part in parts:
        if part.startswith('```'):
            new_parts.append(part)
        else:
            new_parts.append(translate_text(part))
    return "".join(new_parts)

def main():
    parser = argparse.ArgumentParser(description="Translate a file and validate.")
    parser.add_argument("file", help="Path to the file to translate")
    parser.add_argument("--apply", action="store_true", help="Apply changes directly")
    parser.add_argument("--lint", action="store_true", help="Only lint the file for Chinese characters")
    
    args = parser.parse_args()
    filepath = args.file
    
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        sys.exit(1)
        
    if args.lint:
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
        found = False
        with open(filepath, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if chinese_pattern.search(line):
                    print(f"LINT FAIL: {filepath} L{i}: {line.strip()}")
                    found = True
        if found: sys.exit(1)
        else: print(f"LINT PASS: {filepath}"); sys.exit(0)

    print(f"Translating {filepath}...")
    if filepath.endswith('.py'):
        new_content = translate_python_file(filepath)
    elif filepath.endswith(('.md', '.mdc')):
        new_content = translate_markdown_file(filepath)
    else:
        with open(filepath, 'r', encoding='utf-8') as f:
            new_content = translate_text(f.read())
            
    if args.apply:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Applied translation to {filepath}")
        if filepath.endswith('.py'):
            res = subprocess.run([sys.executable, "-m", "py_compile", filepath], capture_output=True)
            if res.returncode == 0: print("Validation: Python syntax OK.")
            else: print(f"Validation: Python syntax ERROR!\n{res.stderr.decode()}")
    else:
        print(new_content)

if __name__ == "__main__":
    main()
