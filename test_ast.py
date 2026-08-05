from typing import Optional, List
import json


def greet(name: str, age: Optional[int] = None) -> str:
    """Say hello to someone."""
    return f"Hello {name}!"


async def fetch_data(url: str) -> List[dict]:
    """Fetch data from URL asynchronously."""
    return []


class UserManager:
    """Manages user accounts."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url

    def create_user(self, name: str) -> int:
        """Create a new user."""
        return 1
