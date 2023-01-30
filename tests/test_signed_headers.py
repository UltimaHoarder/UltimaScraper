import asyncio

from ultima_scraper_api.apis.onlyfans.onlyfans import start as OnlyFans_API
from ultima_scraper_api.classes.make_settings import Config


async def example(time: int, dynamic_param: str, auth_id: int = 0):
    async def authenticate():
        onlyfans_api = OnlyFans_API(Config())
        auth = onlyfans_api.add_auth()
        authed = await auth.login(guest=True)
        return authed

    authed = await authenticate()
    link = "https://onlyfans.com/api2/v2/init"
    signed_headers = authed.session_manager.create_signed_headers(link, time_=time)
    static_1, _, static_2, static_3 = signed_headers["sign"].split(":")
    assert f"{static_1}:{dynamic_param}:{static_2}:{static_3}" == signed_headers["sign"]


if __name__ == "__main__":
    asyncio.run(example(1640531264796, "5f31297d3b4d02e2e278a943bdce703389cf90a4"))
