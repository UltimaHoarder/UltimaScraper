from apis.onlyfans.classes.user_model import create_user
from apis.onlyfans.onlyfans import start as OnlyFans_API
import asyncio


async def example():
    async def authenticate():
        onlyfans_api = OnlyFans_API()
        auth = onlyfans_api.add_auth()
        authed = await auth.login(guest=True)
        return authed

    authed = await authenticate()
    user = await authed.get_user("cummies")
    if isinstance(user, create_user):
        # Do stuff with user
        pass


if __name__ == "__main__":
    asyncio.run(example())
