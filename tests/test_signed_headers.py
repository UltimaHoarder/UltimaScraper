from apis.onlyfans.onlyfans import start as OnlyFans_API
import asyncio


async def example(auth_id: int = 0):
    async def authenticate():
        onlyfans_api = OnlyFans_API()
        auth = onlyfans_api.add_auth()
        authed = await auth.login(guest=True)
        return authed

    authed = await authenticate()
    link = "https://onlyfans.com/api2/v2/init"
    signed_headers = authed.session_manager.create_signed_headers(
        link, time_=1640531264796
    )
    static_1, _, static_2, static_3 = signed_headers["sign"].split(":")
    assert (
        f"{static_1}:5f31297d3b4d02e2e278a943bdce703389cf90a4:{static_2}:{static_3}"
        == signed_headers["sign"]
    )


if __name__ == "__main__":
    asyncio.run(example())
