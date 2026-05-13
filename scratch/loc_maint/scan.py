import os
import re
import sys

def is_binary(filepath):
    """Check if a file is binary."""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
            return b'\0' in chunk
    except:
        return True

def scan_files(root_dir):
    # Pattern for non-ASCII characters, excluding common emojis/symbols if needed
    # But usually for CTI-RAG, we want to find Chinese characters: [\u4e00-\u9fff]
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    results = []
    
    exclude_dirs = {'.git', '.venv', '__pycache__', 'venv', 'node_modules', '.gemini', 'scratch'}
    exclude_files = {'stopwords.py', 'dataset.xlsx'}

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        for file in files:
            if file in exclude_files:
                continue
            
            # Focus on code and documentation
            if not file.endswith(('.py', '.md', '.mdc', '.sh', '.txt', '.ini', '.txt')):
                continue
                
            filepath = os.path.join(root, file)
            if is_binary(filepath):
                continue
                
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        if chinese_pattern.search(line):
                            results.append({
                                'file': os.path.relpath(filepath, root_dir),
                                'line': i,
                                'content': line.strip()
                            })
            except Exception as e:
                # Silently skip files that can't be read as UTF-8
                pass
                
    return results

def main():
    # Handle Windows terminal encoding
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass

    root = os.getcwd()
    print(f"Scanning {root} for Chinese characters...")
    matches = scan_files(root)
    
    if not matches:
        print("Success: No Chinese characters found (excluding ignored files).")
        sys.exit(0)
    
    print(f"Found {len(matches)} occurrences in {len(set(m['file'] for m in matches))} files:")
    current_file = ""
    for match in matches:
        if match['file'] != current_file:
            print(f"\n[{match['file']}]")
            current_file = match['file']
        
        # Safely print content that might contain non-ASCII chars
        content = match['content']
        try:
            print(f"  Line {match['line']}: {content}")
        except UnicodeEncodeError:
            print(f"  Line {match['line']}: {content.encode('ascii', 'replace').decode()}")
    
    sys.exit(1)

if __name__ == "__main__":
    main()
