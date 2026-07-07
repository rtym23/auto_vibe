"""Authority resolver for network lookups."""

import socket
from typing import Optional


class AuthorityResolver:
    """Resolves authority/hostnames to IP addresses."""
    
    def __init__(self):
        self._cache: dict[str, str] = {}
    
    def resolve(self, hostname: str) -> Optional[str]:
        """Resolve hostname to IP address."""
        if hostname in self._cache:
            return self._cache[hostname]
        
        try:
            ip = socket.gethostbyname(hostname)
            self._cache[hostname] = ip
            return ip
        except socket.gaierror:
            return None
    
    def clear_cache(self):
        """Clear the DNS cache."""
        self._cache.clear()
