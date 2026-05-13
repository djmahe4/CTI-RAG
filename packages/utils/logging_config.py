import logging
import os
import sys
from datetime import datetime


DATETIME = datetime.now().strftime('%Y-%m-%d-%H%M%S')
# DATETIME = "debug" # For convenience, output to debug.log during debugging
LOG_FILE = f'saves/log/project-{DATETIME}.log'

def setup_logger(name, level=logging.DEBUG, console=True):
    os.makedirs("saves/log", exist_ok=True)

    """Function to setup logger with the given name and log file."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers to prevent duplicate addition
    if logger.hasHandlers():
        logger.handlers.clear()

    # File handler for logging to a file with UTF-8 encoding
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(level)

    # Formatter for the logs
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler for logging to the console (optional)
    if console:
        # Create a safe log handler for the Windows console
        if sys.platform == "win32":
            # Create a custom StreamHandler to handle encoding issues
            console_handler = SafeConsoleHandler()
        else:
            console_handler = logging.StreamHandler()
            
        # Set console output level to INFO to reduce output volume
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


class SafeConsoleHandler(logging.StreamHandler):
    """Safe console handler to address Unicode encoding issues"""
    
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            # Securely write on Windows to avoid Unicode errors
            if hasattr(stream, 'encoding') and stream.encoding:
                # Use console encoding; replace characters if encoding fails
                msg = msg.encode(stream.encoding, errors='replace').decode(stream.encoding)
            stream.write(msg + self.terminator)
            self.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


# Setup the root logger
logger = setup_logger('ThreatRAG')

# If you want to disable logging from external libraries
# logging.getLogger('some_external_library').setLevel(logging.CRITICAL)
