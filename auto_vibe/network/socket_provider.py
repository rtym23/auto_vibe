"""Socket provider for network connections."""

from typing import Optional
import httpx


class SocketProvider:
    """Manages socket connections and HTTP clients."""
    
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def get(self, url: str) -> str:
        response = await self.client.get(url)
        return response.text
    
    async def post(self, url: str, data: dict) -> str:
        response = await self.client.post(url, json=data)
        return response.text
