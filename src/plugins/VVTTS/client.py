import aiohttp
from melobot import get_logger


logger = get_logger()


async def tts(text: str, base_url="http://127.0.0.1:50021", speaker: int = 1):
    async with aiohttp.ClientSession(base_url) as session:
        async with session.post(
            "audio_query", params={"text": text, "speaker": speaker}
        ) as resp:
            d = await resp.json()
        logger.debug(f"kana from vv: {d["kana"]!r}")
        if not d["kana"]:
            return
        async with session.post(
            "synthesis",
            params={"speaker": speaker, "enable_interrogative_upspeak": 1},
            json=d,
        ) as resp:
            return await resp.read()
