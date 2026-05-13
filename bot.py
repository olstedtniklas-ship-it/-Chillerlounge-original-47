import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import os
import traceback
import asyncio
from aiohttp import web

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# DATABASE (SQLite XP SYSTEM)
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

def get_config(key: str, default=None):
    cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
    result = cursor.fetchone()
    if result is None:
        return default
    val = result[0]
    if val == "None":
        return None
    if val in ("True", "False"):
        return val == "True"
    try:
        return int(val)
    except (ValueError, TypeError):
        return val

def set_config(key: str, value):
    cursor.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value))
    )
    conn.commit()

def get_xp(user_id: int):
    cursor.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0


def add_xp(user_id: int, amount: int):
    current = get_xp(user_id)

    if current == 0:
        cursor.execute(
            "INSERT INTO users (user_id, xp) VALUES (?, ?)",
            (user_id, amount)
        )
    else:
        cursor.execute(
            "UPDATE users SET xp = ? WHERE user_id = ?",
            (current + amount, user_id)
        )

    conn.commit()

# =========================================================
# CONFIG
# =========================================================

welcome_config = {
    "enabled": get_config("welcome_enabled", False),
    "channel_id": get_config("welcome_channel_id", None),
    "message": get_config("welcome_message", "Willkommen %user auf dem Server!"),
    "image": get_config("welcome_image", None),
    "autorole_id": get_config("welcome_autorole_id", None)
}

vip_config = {
    "role_id": get_config("vip_role_id", None),
    "required_xp": 10000
}

# =========================================================
# GLOBAL ERROR HANDLER
# =========================================================

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"❌ Fehler in Befehl '{interaction.command.name if interaction.command else 'unbekannt'}': {error}")
    traceback.print_exc()
    try:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Ein Fehler ist aufgetreten. Bitte versuche es erneut.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ein Fehler ist aufgetreten. Bitte versuche es erneut.", ephemeral=True)
    except Exception as e:
        print(f"❌ Konnte Fehlermeldung nicht senden: {e}")

# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():
    bot.add_view(WelcomeView())
    bot.add_view(RoleView())
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Befehle synchronisiert")
    except Exception as e:
        print(f"❌ Fehler beim Sync: {e}")
    if not xp_loop.is_running():
        xp_loop.start()
    print(f"✅ Bot online als {bot.user}")

# =========================================================
# XP SYSTEM (10 XP PRO STUNDE)
# =========================================================

@tasks.loop(minutes=60)
async def xp_loop():
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue

            add_xp(member.id, 10)
            xp = get_xp(member.id)

            if vip_config["role_id"]:
                role = guild.get_role(vip_config["role_id"])
                if role and xp >= vip_config["required_xp"]:
                    if role not in member.roles:
                        try:
                            await member.add_roles(role)
                            print(f"🎉 VIP vergeben an {member}")
                        except discord.Forbidden:
                            print("❌ Keine Rechte für VIP Rolle")

# =========================================================
# XP COMMAND
# =========================================================

@bot.tree.command(name="xp", description="Zeigt dein XP")
async def xp_cmd(interaction: discord.Interaction):
    try:
        xp = get_xp(interaction.user.id)
        embed = discord.Embed(
            title="📊 XP System",
            description=f"Du hast **{xp} XP**",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"❌ Fehler in /xp: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Fehler beim Laden deiner XP.", ephemeral=True)

# =========================================================
# VIP COMMAND
# =========================================================

@bot.tree.command(name="vip", description="Setzt VIP Rolle (10000 XP nötig)")
async def vip(interaction: discord.Interaction, role: discord.Role):
    try:
        vip_config["role_id"] = role.id
        set_config("vip_role_id", role.id)
        await interaction.response.send_message(
            f"💎 VIP Rolle gesetzt: {role.mention}",
            ephemeral=True
        )
    except Exception as e:
        print(f"❌ Fehler in /vip: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Fehler beim Setzen der VIP Rolle.", ephemeral=True)

# =========================================================
# WELCOME SYSTEM
# =========================================================

class WelcomeTextModal(discord.ui.Modal, title="Willkommensnachricht setzen"):
    nachricht = discord.ui.TextInput(
        label="Nachricht (%user = Erwähnung des Users)",
        placeholder="Willkommen %user auf dem Server!",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        welcome_config["message"] = self.nachricht.value
        set_config("welcome_message", self.nachricht.value)
        await interaction.response.send_message(
            f"✅ Nachricht gesetzt:\n> {self.nachricht.value}",
            ephemeral=True
        )


class WelcomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✏️ Text", style=discord.ButtonStyle.primary, custom_id="welcome_text")
    async def text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WelcomeTextModal())

    @discord.ui.button(label="🖼️ Bild hochladen", style=discord.ButtonStyle.primary, custom_id="welcome_bild")
    async def image(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_message(
                "🖼️ Schicke jetzt dein Bild in diesen Kanal! Du hast **60 Sekunden**.",
                ephemeral=True
            )

            def check(m):
                return m.author == interaction.user and m.channel == interaction.channel and m.attachments

            msg = await bot.wait_for("message", check=check, timeout=60)
            attachment = msg.attachments[0]

            async with web.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        ext = attachment.filename.split(".")[-1].lower()
                        filename = f"welcome_image.{ext}"
                        with open(filename, "wb") as f:
                            f.write(image_data)
                        welcome_config["image"] = filename
                        set_config("welcome_image", filename)

            try:
                await msg.delete()
            except Exception:
                pass

            await interaction.followup.send("✅ Bild gesetzt und gespeichert!", ephemeral=True)
        except Exception as e:
            print(f"❌ Fehler in Welcome Bild Button: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Zeitüberschreitung — bitte erneut versuchen.", ephemeral=True)

    @discord.ui.button(label="📢 Dieser Kanal", style=discord.ButtonStyle.primary, custom_id="welcome_kanal")
    async def channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            welcome_config["channel_id"] = interaction.channel.id
            set_config("welcome_channel_id", interaction.channel.id)
            await interaction.response.send_message(
                f"✅ Willkommenskanal gesetzt: {interaction.channel.mention}", ephemeral=True
            )
        except Exception as e:
            print(f"❌ Fehler in Welcome Kanal Button: {e}")
            await interaction.response.send_message("❌ Fehler.", ephemeral=True)

    @discord.ui.button(label="🔔 An/Aus", style=discord.ButtonStyle.success, custom_id="welcome_toggle")
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            welcome_config["enabled"] = not welcome_config["enabled"]
            set_config("welcome_enabled", welcome_config["enabled"])
            status = "✅ Aktiviert" if welcome_config["enabled"] else "❌ Deaktiviert"
            await interaction.response.send_message(
                f"Willkommensnachricht: **{status}**", ephemeral=True
            )
        except Exception as e:
            print(f"❌ Fehler in Welcome Toggle Button: {e}")
            await interaction.response.send_message("❌ Fehler.", ephemeral=True)

@bot.tree.command(name="welcome", description="Welcome System einstellen")
async def welcome(interaction: discord.Interaction):
    try:
        kanal_text = f"<#{welcome_config['channel_id']}>" if welcome_config["channel_id"] else "Nicht gesetzt"
        embed = discord.Embed(
            title="👋 Welcome Setup",
            description=(
                f"**Status:** {'✅ Aktiv' if welcome_config['enabled'] else '❌ Inaktiv'}\n"
                f"**Kanal:** {kanal_text}\n"
                f"**Nachricht:** {welcome_config['message']}\n"
                f"**Bild:** {'✅ Gesetzt' if welcome_config['image'] else '❌ Kein Bild'}"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=WelcomeView(), ephemeral=True)
    except Exception as e:
        print(f"❌ Fehler in /welcome: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Fehler beim Öffnen des Welcome Setups.", ephemeral=True)

# =========================================================
# AUTOROLE
# =========================================================

@bot.tree.command(name="autorole", description="Automatische Rolle bei Beitritt setzen")
async def autorole(interaction: discord.Interaction, role: discord.Role):
    try:
        welcome_config["autorole_id"] = role.id
        set_config("welcome_autorole_id", role.id)
        await interaction.response.send_message(
            f"🤖 AutoRole gesetzt: {role.mention}",
            ephemeral=True
        )
    except Exception as e:
        print(f"❌ Fehler in /autorole: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Fehler beim Setzen der AutoRole.", ephemeral=True)

# =========================================================
# ROLE MENU
# =========================================================

async def _role_select_callback(interaction: discord.Interaction, values: list):
    try:
        added = []
        for r_id in values:
            if r_id == "0":
                continue
            role = interaction.guild.get_role(int(r_id))
            if role:
                await interaction.user.add_roles(role)
                added.append(role.name)
        if added:
            await interaction.response.send_message(
                f"✅ Rollen vergeben: **{', '.join(added)}**",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Keine Rollen gefunden.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Keine Rechte zum Vergeben der Rollen.", ephemeral=True)
    except Exception as e:
        print(f"❌ Fehler in RoleSelect: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Fehler beim Vergeben der Rollen.", ephemeral=True)


class PersistentRoleSelect(discord.ui.Select):
    def __init__(self, options=None):
        if options is None:
            options = [discord.SelectOption(label="-", value="0")]
        super().__init__(
            custom_id="persistent_role_select",
            placeholder="🎭 Rollen wählen",
            options=options,
            min_values=1,
            max_values=len(options)
        )

    async def callback(self, interaction: discord.Interaction):
        await _role_select_callback(interaction, self.values)


class RoleView(discord.ui.View):
    def __init__(self, roles=None):
        super().__init__(timeout=None)
        if roles:
            options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in roles]
            self.add_item(PersistentRoleSelect(options))
        else:
            self.add_item(PersistentRoleSelect())

@bot.tree.command(name="rolenaussuchen", description="Rollen-Auswahlmenü erstellen")
async def rolen(
    interaction: discord.Interaction,
    role1: discord.Role,
    role2: discord.Role = None,
    role3: discord.Role = None
):
    try:
        roles = [r for r in [role1, role2, role3] if r]
        embed = discord.Embed(
            title="🎭 Rolle auswählen",
            description="Wähle eine oder mehrere Rollen aus dem Menü unten.",
            color=discord.Color.purple()
        )
        await interaction.channel.send(embed=embed, view=RoleView(roles))
        await interaction.response.send_message("✅ Rollenmenü erstellt!", ephemeral=True)
    except Exception as e:
        print(f"❌ Fehler in /rolenaussuchen: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Fehler beim Erstellen des Rollenmenüs.", ephemeral=True)

# =========================================================
# MEMBER JOIN
# =========================================================

@bot.event
async def on_member_join(member: discord.Member):
    try:
        if welcome_config["autorole_id"]:
            role = member.guild.get_role(welcome_config["autorole_id"])
            if role:
                await member.add_roles(role)
    except discord.Forbidden:
        print("❌ Keine Rechte für AutoRole")
    except Exception as e:
        print(f"❌ Fehler bei AutoRole: {e}")

    try:
        if welcome_config["enabled"] and welcome_config["channel_id"]:
            channel = member.guild.get_channel(welcome_config["channel_id"])
            if channel:
                text = welcome_config["message"].replace("%user", member.mention)
                embed = discord.Embed(description=text, color=discord.Color.green())
                image_path = welcome_config["image"]
                if image_path and os.path.isfile(image_path):
                    file = discord.File(image_path, filename=os.path.basename(image_path))
                    embed.set_image(url=f"attachment://{os.path.basename(image_path)}")
                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)
    except Exception as e:
        print(f"❌ Fehler beim Willkommensnachricht senden: {e}")
        traceback.print_exc()

# =========================================================
# WEBSERVER (hält den Bot wach via UptimeRobot)
# =========================================================

async def health(request):
    return web.Response(text="✅ Bot ist online!")

async def start_webserver():
    port = int(os.environ.get("PORT", 8000))
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Webserver läuft auf Port {port}")

async def main():
    async with bot:
        await start_webserver()
        await bot.start(token)

# =========================================================
# START BOT
# =========================================================

token = os.environ.get("DISCORD_TOKEN")
if not token:
    raise ValueError("❌ DISCORD_TOKEN Umgebungsvariable nicht gesetzt!")

asyncio.run(main())
