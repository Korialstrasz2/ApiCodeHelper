import threading
from typing import Dict, Deque, Tuple
from collections import deque


LOCK: threading.Lock = threading.Lock()
CONVERSATIONS: Dict[Tuple[str, int], Deque[Tuple[str, str]]] = {}

HASCREATEDJSONSKILLS:bool = False