import sys
from pathlib import Path
import pytest

# Add project root to sys.path so tests can import top-level modules
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest_plugins = []
