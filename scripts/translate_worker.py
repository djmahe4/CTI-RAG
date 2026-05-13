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
    with open(filepath, 'rb') as f:
        tokens = list(tokenize.tokenize(f.readline))
    
    result = []
    for toknum, tokval, start, end, line in tokens:
        if toknum == tokenize.COMMENT:
            # Preserve the leading '#' and whitespace
            match = re.match(r'(#\s*)(.*)', tokval)
            if match:
                prefix, content = match.groups()
                translated = translate_text(content)
                result.append((toknum, prefix + translated))
            else:
                result.append((toknum, tokval))
        elif toknum == tokenize.STRING:
            # Only translate if it's a docstring or a likely message string
            # We avoid translating keys in dicts or f-string placeholders if possible
            # For simplicity in this worker, we focus on long strings or strings with Chinese
            if any('\u4e00' <= char <= '\u9fff' for char in tokval):
                # Try to preserve string markers (''' or """ or ' or ")
                match = re.match(r'(\"\"\"|\'\'\'|\"|\')(.*)(\"\"\"|\'\'\'|\"|\')', tokval, re.DOTALL)
                if match:
                    quote_start, content, quote_end = match.groups()
                    translated = translate_text(content)
                    result.append((toknum, quote_start + translated + quote_end))
                else:
                    result.append((toknum, tokval))
            else:
                result.append((toknum, tokval))
        else:
            result.append((toknum, tokval))
            
    # Reconstruction logic for tokens is complex, so we'll use a simpler regex-based approach for comments
    # as tokenize reconstruction is error-prone for whitespace preservation.
    # Actually, for comments we can just do line-by-line.
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    new_lines = []
    for line in lines:
        # 1. Handle full-line or trailing comments
        if '#' in line:
            parts = line.split('#', 1)
            code_part = parts[0]
            comment_part = parts[1]
            if any('\u4e00' <= char <= '\u9fff' for char in comment_part):
                translated_comment = translate_text(comment_part.strip())
                # Restore indentation if it was a trailing comment
                new_lines.append(f"{code_part}# {translated_comment}\n")
            else:
                new_lines.append(line)
        # 2. Handle strings (rough approach for now, better to use LLM for the actual edit)
        elif any('\u4e00' <= char <= '\u9fff' for char in line):
            # If it's a string literal in the line, translate the Chinese part
            def repl(match):
                return translate_text(match.group(0))
            
            # Simple regex for Chinese segments
            translated_line = re.sub(r'[\u4e00-\u9fff]+', lambda m: translate_text(m.group(0)), line)
            new_lines.append(translated_line)
        else:
            new_lines.append(line)
            
    return "".join(new_lines)

def translate_markdown_file(filepath):
    """Translates a Markdown file, preserving code blocks."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Split by code blocks
    parts = re.split(r'(```.*?```)', content, flags=re.DOTALL)
    new_parts = []
    for part in parts:
        if part.startswith('```'):
            new_parts.append(part) # Preserve code blocks
        else:
            # Translate prose segments line by line or paragraph by paragraph
            translated = translate_text(part)
            new_parts.append(translated)
            
    return "".join(new_parts)

def main():
    parser = argparse.ArgumentParser(description="Translate a file using argostranslate.")
    parser.add_argument("file", help="Path to the file to translate")
    parser.add_argument("--tmp", action="store_true", help="Write to .tmp file and lint")
    parser.add_argument("--commit", action="store_true", help="Replace original if lint passes")
    
    args = parser.parse_args()
    filepath = args.file
    
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        sys.exit(1)
        
    print(f"Translating {filepath}...")
    
    if filepath.endswith('.py'):
        new_content = translate_python_file(filepath)
    elif filepath.endswith('.md') or filepath.endswith('.mdc'):
        new_content = translate_markdown_file(filepath)
    else:
        with open(filepath, 'r', encoding='utf-8') as f:
            new_content = translate_text(f.read())
            
    if args.tmp:
        tmp_path = filepath + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Wrote to {tmp_path}")
        
        # Lint
        if filepath.endswith('.py'):
            result = subprocess.run([sys.executable, "-m", "py_compile", tmp_path], capture_output=True)
            if result.returncode == 0:
                print("Lint passed (py_compile).")
                if args.commit:
                    os.replace(tmp_path, filepath)
                    print(f"Committed changes to {filepath}")
            else:
                print(f"Lint FAILED:\n{result.stderr.decode()}")
                sys.exit(1)
        else:
            print("No lint defined for this file type.")
            if args.commit:
                os.replace(tmp_path, filepath)
                print(f"Committed changes to {filepath}")
    else:
        print(new_content)

if __name__ == "__main__":
    main()
