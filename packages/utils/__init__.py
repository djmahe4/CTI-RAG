import imp
import time
import random
import os
from pathlib import Path
from .logging_config import logger
from .bm25 import AbstractBM25
from .query_preprocessor import QueryPreprocessor

def is_text_pdf(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    if total_pages == 0:
        return False

    text_pages = 0
    for page_num in range(total_pages):
        page = doc.load_page(page_num)
        text = page.get_text()
        if text.strip():  # Check for text contents
            text_pages += 1

    # Calculate the proportion of pages with text content
    text_ratio = text_pages / total_pages
    # Text is considered PDF if more than 50% of pages contain text
    return text_ratio > 0.5

def hashstr(input_string, length=8, with_salt=False):
    import hashlib
    # Add time stamp as interference
    if with_salt:
        input_string += str(time.time() + random.random())

    hash = hashlib.md5(str(input_string).encode()).hexdigest()
    return hash[:length]


def get_project_root():
    """
    Fetch the root directory path
    Determine the root directory by searching for a directory containing a specific identification file
    """
    current_path = Path(__file__).resolve()

    # Look up from the current file until the root directory identifier is found
    # The root directory should contain one of these files: .git, references.txt, project.toml, setup.py
    root_indicators = ['.git', 'requirements.txt', 'pyproject.toml', 'setup.py', 'README.md']

    for parent in current_path.parents:
        if any((parent / indicator).exists() for indicator in root_indicators):
            return str(parent)

    # If no identification file is found, return the top two-tier directory of the current file (father directory of packages)
    return str(current_path.parent.parent.parent)


def get_docker_safe_url(base_url):
    if os.getenv("RUNNING_IN_DOCKER") == "true":
        # Replace all possible local address forms
        base_url = base_url.replace("http://localhost", "http://host.docker.internal")
        base_url = base_url.replace("http://127.0.0.1", "http://host.docker.internal")
        logger.info(f"Running in docker, using {base_url} as base url")
    return base_url