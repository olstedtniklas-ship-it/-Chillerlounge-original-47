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
    r = cursor.fetchone()
    return r[0] if r else default

def set_config(key, value):
    cursor.execute(
        "INSERT INTO config (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value))
    )
    conn.commit()

# =========================================================
# CONFIG
# =========================================================

welcome_config = {
    "enabled": get_config("welcome_enabled", "False") == "True",
    "channel_id": int(get_config("welcome_channel_id", 0)),
    "message": get_config("welcome_message", "Willkommen %user 💖"),
    "image_url": get_config("welcome_image_url", None),
    "autorole_id": int(get_config("welcome_autorole_id", 0))
}

# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    bot.add_view(RoleView())
    synced = await bot.tree.sync()
    print(f"✅ {len(synced)} Commands geladen")
    print(f"🟢 Online als {bot.user}")

# =========================================================
# WELCOME SETUP
# =========================================================

class WelcomeTextModal(discord.ui.Modal, title="Willkommensnachricht"):
    text = discord.ui.TextInput(label="Text (%user = Erwähnung)", max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        welcome_config["message"] = self.text.value
        set_config("welcome_message", self.text.value)
        await interaction.response.send_message("✅ Nachricht gespeichert", ephemeral=True)

class WelcomeImageModal(discord.ui.Modal, title="Welcome Bild URL"):
    url = discord.ui.TextInput(label="Bild URL (https://...)", max_length=300)

    async def on_submit(self, interaction: discord.Interaction):
        welcome_config["image_url"] = self.url.value
        set_config("welcome_image_url", self.url.value)
        await interaction.response.send_message("✅ Bild URL gespeichert", ephemeral=True)

class WelcomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✍️ Text", style=discord.ButtonStyle.primary)
    async def text(self, interaction, _):
        await interaction.response.send_modal(WelcomeTextModal())

    @discord.ui.button(label="🖼️ Bild URL", style=discord.ButtonStyle.primary)
    async def image(self, interaction, _):
        await interaction.response.send_modal(WelcomeImageModal())

    @discord.ui.button(label="📢 Kanal", style=discord.ButtonStyle.secondary)
    async def channel(self, interaction, _):
        welcome_config["channel_id"] = interaction.channel.id
        set_config("welcome_channel_id", interaction.channel.id)
        await interaction.response.send_message("✅ Kanal gesetzt", ephemeral=True)

    @discord.ui.button(label="🔔 An / Aus", style=discord.ButtonStyle.success)
    async def toggle(self, interaction, _):
        welcome_config["enabled"] = not welcome_config["enabled"]
        set_config("welcome_enabled", welcome_config["enabled"])
        await interaction.response.send_message(
            f"Welcome {'aktiviert' if welcome_config['enabled'] else 'deaktiviert'}",
            ephemeral=True
        )

@bot.tree.command(name="welcome", description="Welcome System einstellen")
async def welcome(interaction: discord.Interaction):
    embed = discord.Embed(
        title="👋 Welcome Setup",
        description=(
            f"**Status:** {'✅ Aktiv' if welcome_config['enabled'] else '❌ Inaktiv'}\n"
            f"**Nachricht:** {welcome_config['message']}\n"
            f"**Bild:** {'Gesetzt' if welcome_config['image_url'] else 'Keins'}"
        ),
        color=discord.Color.pink()
    )
    await interaction.response.send_message(embed=embed, view=WelcomeView(), ephemeral=True)

# =========================================================
# MEMBER JOIN
# =========================================================

@bot.event
async def on_member_join(member: discord.Member):
    if welcome_config["autorole_id"]:
        role = member.guild.get_role(welcome_config["autorole_id"])
        if role:
            await member.add_roles(role)

    if not welcome_config["enabled"]:
        return

    channel = member.guild.get_channel(welcome_config["channel_id"])
    if not channel:
        return

    text = welcome_config["message"].replace("%user", member.mention)
    embed = discord.Embed(description=text, color=discord.Color.pink())

    if welcome_config["image_url"]:
        embed.set_image(url=welcome_config["image_url"])

    await channel.send(embed=embed)

# =========================================================
# AUTOROLE
# =========================================================

@bot.tree.command(name="autorole", description="AutoRole setzen")
async def autorole(interaction: discord.Interaction, role: discord.Role):
    welcome_config["autorole_id"] = role.id
    set_config("welcome_autorole_id", role.id)
    await interaction.response.send_message("✅ AutoRole gesetzt", ephemeral=True)

# =========================================================
# ROLE SELECT
# =========================================================

class RoleSelect(discord.ui.Select):
    def __init__(self, roles):
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in roles]
        super().__init__(placeholder="🎭 Rollen auswählen", options=options, min_values=1)

    async def callback(self, interaction: discord.Interaction):
        for rid in self.values:
            role = interaction.guild.get_role(int(rid))
            if role:
                await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ Rollen vergeben", ephemeral=True)

class RoleView(discord.ui.View):
    def __init__(self, roles=None):
        super().__init__(timeout=None)
        if roles:
            self.add_item(RoleSelect(roles))

@bot.tree.command(name="rolenaussuchen", description="Rollenmenü erstellen")
async def rolen(interaction: discord.Interaction, role1: discord.Role, role2: discord.Role = None):
    roles = [r for r in [role1, role2] if r]
    embed = discord.Embed(title="🎭 Rollen", description="Wähle deine Rollen", color=discord.Color.purple())
    await interaction.channel.send(embed=embed, view=RoleView(roles))
    await interaction.response.send_message("✅ Menü erstellt", ephemeral=True)

# =========================================================
# KEEP ALIVE
# =========================================================

async def health(req):
    return web.Response(text="online")

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    await bot.start(os.environ["DISCORD_TOKEN"])

asyncio.run(main())
