import asyncio, aiohttp
from modules.anime_telegram_worker import extract_qualities_from_kuramanime, extract_qualities_from_nontonanimeid, check_episode_on_all_sources

async def test():
    async with aiohttp.ClientSession() as session:
        kq = await extract_qualities_from_kuramanime(session, 'https://v20.kuramanime.ing/anime/2860/sekai-saikyou-no-majo-hajimemashita/episode/1')
        print('Kuramanime qualities:', kq)
        all_s = await check_episode_on_all_sources(session, 'Sekai Saikyou no Majo, Hajimemashita', 1, skip_source='AnimeSail')
        print('All sources without AnimeSail:', all_s)

asyncio.run(test())
