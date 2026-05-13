import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import os
import asyncio
import traceback

# ================== INTENTS ==================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================== DATABASE ==================
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
    r = cursor.fetchone()
    if not r:
        return default
    val = r[0]
    if val == "None":
        return None
    return val

def set_config(key, value):
    cursor.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    conn.commit()

# ================== XP SYSTEM ==================
def get_xp(uid):
    cursor.execute("SELECT xp FROM users WHERE user_id = ?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def add_xp(uid, amount):
    xp = get_xp(uid)
    if xp == 0:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, xp) VALUES (?, ?)", (uid, amount))
    else:
        cursor.execute("UPDATE users SET xp = ? WHERE user_id = ?", (xp + amount, uid))
    conn.commit()

vip_config = {
    "role_id": int(get_config("vip_role_id", 0)),
    "required_xp": 10000
}

@tasks.loop(hours=1)
async def xp_loop():
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            add_xp(member.id, 10)
            xp = get_xp(member.id)

            if vip_config["role_id"]:
                role = guild.get_role(vip_config["role_id"])
                if role and xp >= vip_config["required_xp"] and role not in member.roles:
                    try:
                        await member.add_roles(role)
                    except discord.Forbidden:
                        pass

# ================== XP COMMAND ==================
@bot.tree.command(name="xp", description="Zeigt deine XP")
async def xp(interaction: discord.Interaction):
    xp = get_xp(interaction.user.id)
    embed = discord.Embed(
        title="📊 XP",
        description=f"Du hast **{xp} XP**",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vip", description="Setzt VIP Rolle")
async def vip(interaction: discord.Interaction, role: discord.Role):
    vip_config["role_id"] = role.id
    set_config("vip_role_id", role.id)
    await interaction.response.send_message(f"💎 VIP Rolle gesetzt: {role.mention}", ephemeral=True)

# ================== WELCOME CONFIG ==================
welcome_config = {
    "enabled": get_config("welcome_enabled", "False") == "True",
    "channel_id": int(get_config("welcome_channel_id", 0)),
    "message": get_config("welcome_message", "Willkommen %user 💖"),
    "image_url": get_config("welcome_image_url", None),
    "autorole_id": int(get_config("welcome_autorole_id", 0))
}

# ================== WELCOME COMMAND ==================
@bot.tree.command(name="welcome", description="Welcome System einstellen")
async def welcome(
    interaction: discord.Interaction,
    status: bool,
    channel: discord.TextChannel,
    message: str,
    image_url: str = None
):
    welcome_config["enabled"] = status
    welcome_config["channel_id"] = channel.id
    welcome_config["message"] = message
    welcome_config["image_url"] = image_url

    set_config("welcome_enabled", status)
    set_config("welcome_channel_id", channel.id)
    set_config("welcome_message", message)
    set_config("welcome_image_url", image_url)

    await interaction.response.send_message("✅ Welcome-System gespeichert!", ephemeral=True)

# ================== AUTOROLE ==================
@bot.tree.command(name="autorole", description="AutoRole setzen")
async def autorole(interaction: discord.Interaction, role: discord.Role):
    welcome_config["autorole_id"] = role.id
    set_config("welcome_autorole_id", role.id)
    await interaction.response.send_message(f"🤖 AutoRole gesetzt: {role.mention}", ephemeral=True)

# ================== ROLE MENU ==================
class RoleSelect(discord.ui.Select):
    def __init__(self, roles):
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in roles]
        super().__init__(placeholder="🎭 Rolle wählen", options=options, min_values=1, max_values=len(options))

    async def callback(self, interaction: discord.Interaction):
        for r_id in self.values:
            role = interaction.guild.get_role(int(r_id))
            if role:
                await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ Rollen vergeben!", ephemeral=True)

class RoleView(discord.ui.View):
    def __init__(self, roles):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(roles))

@bot.tree.command(name="rolenaussuchen", description="Rollen-Auswahl erstellen")
async def rolen(interaction: discord.Interaction, role1: discord.Role, role2: discord.Role = None, role3: discord.Role = None):
    roles = [r for r in [role1, role2, role3] if r]
    embed = discord.Embed(title="🎭 Rollen auswählen", description="Wähle deine Rollen", color=discord.Color.pink())
    await interaction.channel.send(embed=embed, view=RoleView(roles))
    await interaction.response.send_message("✅ Rollenmenü erstellt!", ephemeral=True)

# ================== MEMBER JOIN ==================
@bot.event
async def on_member_join(member):
    try:
        if welcome_config["autorole_id"]:
            role = member.guild.get_role(welcome_config["autorole_id"])
            if role:
                await member.add_roles(role)

        if welcome_config["enabled"] and welcome_config["channel_id"]:
            channel = member.guild.get_channel(welcome_config["channel_id"])
            if not channel:
                return

            text = welcome_config["message"].replace("%user", member.mention)
            embed = discord.Embed(description=text, color=discord.Color.from_rgb(255, 105, 180))

            if welcome_config["image_url"]:
                embed.set_image(url=welcome_config["image_url"])

            await channel.send(embed=embed)
    except Exception:
        traceback.print_exc()

# ================== READY ==================
@bot.event
async def on_ready():
    await bot.tree.sync()
    if not xp_loop.is_running():
        xp_loop.start()
    print(f"🟢 Online als {bot.user}")

# ================== START ==================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt!")

asyncio.run(bot.start(TOKEN))
