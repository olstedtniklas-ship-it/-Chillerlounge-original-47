import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import os
import traceback
import asyncio
from aiohttp import web

# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# DATABASE
# =========================================================

conn = sqlite3.connect("xp.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

conn.commit()

def get_config(key, default=None):
    cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
    result = cursor.fetchone()
    return result[0] if result else default

def set_config(key, value):
    cursor.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value))
    )
    conn.commit()

def get_xp(user_id):
    cursor.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,))
    r = cursor.fetchone()
    return r[0] if r else 0

def add_xp(user_id, amount):
    xp = get_xp(user_id)
    if xp == 0:
        cursor.execute("INSERT INTO users (user_id, xp) VALUES (?, ?)", (user_id, amount))
    else:
        cursor.execute("UPDATE users SET xp = ? WHERE user_id = ?", (xp + amount, user_id))
    conn.commit()

# =========================================================
# CONFIG
# =========================================================

welcome_config = {
    "enabled": True,
    "channel_id": int(get_config("welcome_channel_id", 0)),
    "message": get_config("welcome_message", "Willkommen %user auf dem Server! 💖"),
    "image": "welcome.png",
    "autorole_id": int(get_config("welcome_autorole_id", 0))
}

vip_config = {
    "role_id": int(get_config("vip_role_id", 0)),
    "required_xp": 10000
}

# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Slash Commands synchronisiert")
    except Exception as e:
        print(e)

    if not xp_loop.is_running():
        xp_loop.start()

    print(f"🟢 Bot online als {bot.user}")

# =========================================================
# XP LOOP
# =========================================================

@tasks.loop(minutes=60)
async def xp_loop():
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue

            add_xp(member.id, 10)

            if vip_config["role_id"]:
                role = guild.get_role(vip_config["role_id"])
                if role and get_xp(member.id) >= vip_config["required_xp"]:
                    if role not in member.roles:
                        await member.add_roles(role)

# =========================================================
# XP COMMAND
# =========================================================

@bot.tree.command(name="xp", description="Zeigt dein XP")
async def xp(interaction: discord.Interaction):
    xp = get_xp(interaction.user.id)
    embed = discord.Embed(
        title="📊 XP",
        description=f"Du hast **{xp} XP**",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================================================
# AUTOROLE COMMAND
# =========================================================

@bot.tree.command(name="autorole", description="Setzt AutoRole")
async def autorole(interaction: discord.Interaction, role: discord.Role):
    welcome_config["autorole_id"] = role.id
    set_config("welcome_autorole_id", role.id)
    await interaction.response.send_message(
        f"✅ AutoRole gesetzt: {role.mention}", ephemeral=True
    )

# =========================================================
# WELCOME COMMAND
# =========================================================

@bot.tree.command(name="welcome", description="Setzt Welcome Kanal")
async def welcome(interaction: discord.Interaction):
    welcome_config["channel_id"] = interaction.channel.id
    set_config("welcome_channel_id", interaction.channel.id)
    await interaction.response.send_message(
        f"✅ Welcome-Kanal gesetzt: {interaction.channel.mention}", ephemeral=True
    )

# =========================================================
# MEMBER JOIN
# =========================================================

@bot.event
async def on_member_join(member: discord.Member):
    # AutoRole
    try:
        if welcome_config["autorole_id"]:
            role = member.guild.get_role(welcome_config["autorole_id"])
            if role:
                await member.add_roles(role)
    except Exception as e:
        print(e)

    # Welcome Message
    try:
        channel = member.guild.get_channel(welcome_config["channel_id"])
        if not channel:
            return

        text = welcome_config["message"].replace("%user", member.mention)

        embed = discord.Embed(
            description=text,
            color=discord.Color.from_rgb(255, 105, 180)
        )

        if os.path.isfile("welcome.png"):
            file = discord.File("welcome.png", filename="welcome.png")
            embed.set_image(url="attachment://welcome.png")
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)

    except Exception as e:
        traceback.print_exc()

# =========================================================
# KEEP ALIVE WEBSERVER
# =========================================================

async def health(request):
    return web.Response(text="Bot läuft!")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8000)))
    await site.start()

async def main():
    await start_web()
    await bot.start(os.environ["DISCORD_TOKEN"])

asyncio.run(main())
