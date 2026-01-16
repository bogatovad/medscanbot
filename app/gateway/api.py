import httpx

class HttpClient:
    async def get(
            self,
            url: str,
            headers: dict = None,
    ):
        async with httpx.AsyncClient() as client:
            repsonse = await client.get(url)
            return repsonse.json()