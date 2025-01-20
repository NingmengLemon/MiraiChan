import aiohttp
from yarl import URL

from .annotations import Speaker, AudioQueryResult


class VoicevoxEngineClient(aiohttp.ClientSession):
    def __init__(self, base_url: str | URL = "http://127.0.0.1:50021", **kwargs):
        super().__init__(base_url=base_url, **kwargs)

    async def audio_query(self, text: str, speaker: int = 1) -> AudioQueryResult:
        async with self.post(
            "audio_query", params={"text": text, "speaker": speaker}
        ) as resp:
            return await resp.json()

    async def synthesis(
        self,
        accent_data: AudioQueryResult,
        speaker: int = 1,
        enable_interrogative_upspeak=True,
    ):
        async with self.post(
            "synthesis",
            params={
                "speaker": speaker,
                "enable_interrogative_upspeak": int(enable_interrogative_upspeak),
            },
            json=accent_data,
        ) as resp:
            return await resp.read()

    async def simple_tts(self, text: str, speaker: int = 1):
        data = await self.audio_query(text, speaker)
        return await self.synthesis(data, speaker)

    async def get_speakers(self) -> list[Speaker]:
        async with self.post("speakers") as resp:
            return await resp.json()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
