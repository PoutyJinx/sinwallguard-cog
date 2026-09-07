from .sinwallguard import SINWallGuard


async def setup(bot):
    await bot.add_cog(SINWallGuard(bot))
