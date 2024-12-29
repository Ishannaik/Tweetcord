import asyncio
import os
import sys
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from configs.load_configs import configs
from src.checker import check_configs, check_env, check_db, check_upgrade
from src.db_function.init_db import init_db
from src.db_function.repair_db import auto_repair_mismatched_clients
from src.presence_updater import update_presence
from src.log import setup_logger

log = setup_logger(__name__)

load_dotenv()

bot = commands.Bot(command_prefix=configs['prefix'], intents=discord.Intents.all())

# Web server handler with HTML content
async def handle_web(request):
    html_content = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Discord Bot Status</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 40px;
                    line-height: 1.6;
                    background: #f5f5f5;
                }
                .container {
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    max-width: 600px;
                    margin: 0 auto;
                }
                h1 { color: #5865F2; }
                .status { color: #43B581; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Discord Bot Status</h1>
                <p class="status">✅ Bot is running!</p>
                <p>This is the status page for the Discord bot.</p>
            </div>
        </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_web)
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    log.info(f"Web server started and bound to port {port}")
    return runner

async def run_bot():
    discord.utils.setup_logging()
    async with bot:
        await bot.start(os.getenv('BOT_TOKEN'))

@bot.event
async def on_ready():
    if not (os.path.isfile(os.path.join(os.getenv('DATA_PATH'), 'tracked_accounts.db'))):
        await init_db()
        
    check_upgrade()
        
    if not check_env():
        log.warning('incomplete environment variables detected, will retry in 30 seconds')
        await asyncio.sleep(30)
        load_dotenv()
        
    if not check_configs(configs):
        log.warning('incomplete configs file detected, will retry in 30 seconds')
        await asyncio.sleep(30)
        os.execv(sys.executable, ['python'] + sys.argv)
        
    invalid_clients = await check_db()
    if invalid_clients:
        log.warning('detected environment variable undefined client name in database')
        if configs['auto_repair_mismatched_clients']:
            await auto_repair_mismatched_clients(invalid_clients)
            log.info('automatically replace mismatched client names with the first client name in the environment variable, use the sync slash command in discord to ensure notifications are turned on')
        else:
            log.warning('set auto_repair_mismatched_clients to true in configs to automatically fix this error or manually update the database or environment variables')
    else:
        log.info('database check passed')

    await update_presence(bot)

    bot.tree.on_error = on_tree_error
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')
    log.info(f'{bot.user} is online')
    slash = await bot.tree.sync()
    log.info(f'synced {len(slash)} slash commands')


@bot.command()
@commands.is_owner()
async def load(ctx: commands.context.Context, extension):
    await bot.load_extension(f'cogs.{extension}')
    await ctx.send(f'Loaded {extension} done.')


@bot.command()
@commands.is_owner()
async def unload(ctx: commands.context.Context, extension):
    await bot.unload_extension(f'cogs.{extension}')
    await ctx.send(f'Un - Loaded {extension} done.')


@bot.command()
@commands.is_owner()
async def reload(ctx: commands.context.Context, extension):
    await bot.reload_extension(f'cogs.{extension}')
    await ctx.send(f'Re - Loaded {extension} done.')


@bot.command()
@commands.is_owner()
async def download_log(ctx: commands.context.Context):
    message = await ctx.send(file=discord.File('console.log'))
    await message.delete(delay=15)


@bot.command()
@commands.is_owner()
async def download_data(ctx: commands.context.Context):
    message = await ctx.send(file=discord.File(os.path.join(os.getenv('DATA_PATH'), 'tracked_accounts.db')))
    await message.delete(delay=15)


@bot.command()
@commands.is_owner()
async def upload_data(ctx: commands.context.Context):
    raw = await [attachment for attachment in ctx.message.attachments if attachment.filename[-3:] == '.db'][0].read()
    with open(os.path.join(os.getenv('DATA_PATH'), 'tracked_accounts.db'), 'wb') as wbf:
        wbf.write(raw)
    message = await ctx.send('successfully uploaded data')
    await message.delete(delay=5)


@bot.event
async def on_tree_error(itn: discord.Interaction, error: app_commands.AppCommandError):
    await itn.response.send_message(error, ephemeral=True)
    log.warning(f'an error occurred but was handled by the tree error handler, error message : {error}')


@bot.event
async def on_command_error(ctx: commands.context.Context, error: commands.errors.CommandError):
    if isinstance(error, commands.errors.CommandNotFound):
        return
    else:
        await ctx.send(error)
    log.warning(f'an error occurred but was handled by the command error handler, error message : {error}')


async def main():
    # Start web server first and ensure it's running
    runner = await start_web_server()
    try:
        # Then start the bot
        await run_bot()
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    # Use asyncio.run() to properly handle the async main function
    asyncio.run(main())
