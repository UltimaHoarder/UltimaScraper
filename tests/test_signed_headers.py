import asyncio

from ultima_scraper_api.apis.onlyfans.onlyfans import OnlyFansAPI
from ultima_scraper_api.classes.make_settings import Config


async def example(
    time: int,
    dynamic_param: str,
    link: str = "https://onlyfans.com/api2/v2/init",
    auth_id: int = 0,
):
    async def authenticate():
        onlyfans_api = OnlyFansAPI(Config())
        authed = await onlyfans_api.login(guest=True)
        return authed

    authed = await authenticate()
    signed_headers = authed.session_manager.create_signed_headers(link, auth_id, time)
    new_sign = signed_headers["sign"]
    static_1, _, static_2, static_3 = new_sign.split(":")
    middle_part = dynamic_param.split(":")[1]
    assert f"{static_1}:{middle_part}:{static_2}:{static_3}" == new_sign


if __name__ == "__main__":
    asyncio.run(
        example(
            1675150502748, "6820:148f109177631164a099641019e951d9f0c1edf7:7db:63d81407"
        )
    )
