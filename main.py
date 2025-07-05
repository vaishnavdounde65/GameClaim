import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timezone, timedelta
import json
import tempfile

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="g!", intents=intents, help_command=None)

# Load alert channels
CHANNELS_FILE = 'channels.json'
if os.path.exists(CHANNELS_FILE):
    with open(CHANNELS_FILE, "r") as f:
        guild_channels = json.load(f)
else:
    guild_channels = {}

def save_channels():
    with open(CHANNELS_FILE, "w") as f:
        json.dump(guild_channels, f, indent=4)

# Load sent games
SENT_FILE = "sent_games.json"
sent_games = {"epic": {}, "steam": {}}
if os.path.exists(SENT_FILE):
    with open(SENT_FILE, "r") as f:
        try:
            data = json.load(f)
            sent_games["epic"].update(data.get("epic", {}))
            sent_games["steam"].update(data.get("steam", {}))
        except json.JSONDecodeError:
            print("⚠️ sent_games.json corrupted, using empty state.")

def save_sent_games():
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=".") as tf:
            json.dump(sent_games, tf, indent=4)
            tempname = tf.name
        os.replace(tempname, SENT_FILE)
    except Exception as e:
        print("❌ Failed to save sent_games.json:", e)

def cleanup_sent_games():
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    for platform in ["epic", "steam"]:
        new_data = {}
        for key, timestamp in sent_games.get(platform, {}).items():
            try:
                entry_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if entry_time > cutoff:
                    new_data[key] = timestamp
            except:
                continue
        sent_games[platform] = new_data
    save_sent_games()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}#{bot.user.discriminator}")
    activity = discord.Activity(type=discord.ActivityType.watching, name="g!help for free games 🎮")
    await bot.change_presence(activity=activity)
    if not check_free_games.is_running():
        check_free_games.start()
    if not steam_games.is_running():
        steam_games.start()
    cleanup_sent_games()

@bot.command()
@commands.has_permissions(administrator=True)
async def setchannel(ctx, channel: discord.TextChannel):
    guild_channels[str(ctx.guild.id)] = channel.id
    save_channels()
    await ctx.send(f"✅ Game alerts will now be sent to {channel.mention}")
    if not channel.permissions_for(ctx.guild.me).send_messages:
        await ctx.send("❌ I can't send messages in that channel. Please check my permissions.")

@bot.command()
@commands.has_permissions(administrator=True)
async def currentchannel(ctx):
    gid = str(ctx.guild.id)
    if gid in guild_channels:
        channel = bot.get_channel(guild_channels[gid])
        if channel:
            await ctx.send(f"📢 Current alert channel is: {channel.mention}")
        else:
            await ctx.send("❌ The saved channel does not exist anymore.")
    else:
        await ctx.send("⚠️ No alert channel set. Use `g!setchannel #channel`.")

@bot.command()
@commands.has_permissions(administrator=True)
async def removechannel(ctx):
    gid = str(ctx.guild.id)
    if gid in guild_channels:
        del guild_channels[gid]
        save_channels()
        await ctx.send("✅ Alert channel removed.")
    else:
        await ctx.send("⚠️ No alert channel set.")

@bot.command()
async def ping(ctx):
    await ctx.reply(f"🏓 Pong! Bot latency: {round(bot.latency * 1000)}ms")

@bot.command()
async def author(ctx):
    embed = discord.Embed(
        title="**GameClaim Bot Made by Argue**",
        description="🤖 Crafted with ❤️ to track & alert free games on Steam and Epic 🎮"
    )
    user = await bot.fetch_user(842978764690030593) 
    avatar = user.display_avatar.url
    embed.color = discord.Color.pink()
    embed.set_author(name=user.name, icon_url=avatar)
    embed.set_thumbnail(url=avatar)
    embed.add_field(name="Links", value="[GitHub](https://github.com/vaishnavdounde65) | [YouTube](https://youtube.com/@vaishnavdounde) | [Instagram](https://instagram.com/vaishnavdounde65)", inline=False)
    embed.set_footer(text="GameClaim • Free Game Tracker")  
    await ctx.reply(embed=embed)

def format_duration(delta):
    parts = []
    if delta.days > 0:
        parts.append(f"{delta.days} day{'s' if delta.days != 1 else ''}")
    hours = delta.seconds // 3600
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    minutes = (delta.seconds % 3600) // 60
    if minutes > 0 and delta.days == 0:
        parts.append(f"{minutes} min{'s' if minutes != 1 else ''}")
    return "" + " ".join(parts) if parts else "Ends soon!"

@tasks.loop(hours=1)
async def check_free_games():
    await bot.wait_until_ready()
    for guild in bot.guilds:
        gid = str(guild.id)
        if gid not in guild_channels:
            continue
        channel = bot.get_channel(guild_channels[gid])
        if not channel:
            continue
        try:
            res = requests.get("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US", timeout=10).json()
        except:
            continue
        for game in res["data"]["Catalog"]["searchStore"]["elements"]:
            title = game.get("title", "Unknown")
            promotions = game.get("promotions")
            if not promotions:
                continue
            offers = promotions.get("promotionalOffers", [])
            if not offers or not offers[0]["promotionalOffers"]:
                continue
            offer = offers[0]["promotionalOffers"][0]
            start = datetime.fromisoformat(offer["startDate"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(offer["endDate"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if not (start <= now <= end):
                continue
            if title in sent_games["epic"] and start.isoformat() <= sent_games["epic"][title]:
                continue
            sent_games["epic"][title] = start.isoformat()
            save_sent_games()
            slug = game.get("productSlug") or game.get("catalogNs", {}).get("mappings", [{}])[0].get("pageSlug", "")
            link = f"https://store.epicgames.com/en-US/p/{slug}" if slug else "https://store.epicgames.com/"
            price = game.get("price", {}).get("totalPrice", {}).get("originalPrice", 0) / 100
            images = game.get("keyImages", [])
            thumb = next((img["url"] for img in images if img.get("type") == "Thumbnail"), images[0]["url"] if images else None)
            embed = discord.Embed(title=f"🎮 **{title}**", description=f"[Click to claim the game here]({link})", color=discord.Color.light_gray())
            embed.add_field(name="💲 Original Price", value=f"${price:.2f}", inline=True)
            embed.add_field(name="🕒 Offer Period", value=format_duration(end - now), inline=False)
            if thumb:
                embed.set_image(url=thumb)
            embed.set_footer(text="GameClaim • Epic Freebie")
            await channel.send(embed=embed)

@tasks.loop(hours=1)
async def steam_games():
    await bot.wait_until_ready()
    for guild in bot.guilds:
        gid = str(guild.id)
        if gid not in guild_channels:
            continue
        channel = bot.get_channel(guild_channels[gid])
        if not channel:
            continue
        try:
            res = requests.get("https://www.gamerpower.com/api/giveaways?platform=steam", timeout=10).json()
        except:
            continue
        for game in res[:5]:
            game_id = str(game.get("id"))
            if game_id in sent_games["steam"]:
                continue
            sent_games["steam"][game_id] = datetime.now(timezone.utc).isoformat()
            save_sent_games()
            embed = discord.Embed(
                title=f"🎮 **{game.get('title')}**",
                description=game.get("description", "No description"),
                color=discord.Color.blue()
            )
            embed.add_field(name="💲 Original Price", value=game.get("worth", "N/A"), inline=True)
            embed.add_field(name="⏳ Free Till", value=game.get("end_date", "N/A"), inline=True)
            embed.add_field(name="🔗 Claim", value=f"[Click Here]({game.get('open_giveaway_url', '')})", inline=False)
            embed.set_image(url=game.get("thumbnail", ""))
            embed.set_footer(text="GameClaim • Steam Freebie")
            await channel.send(embed=embed)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="**GameClaim Bot Commands**",
        description="Use `g!` as the prefix for all commands.",
        color=discord.Color.blue()
    )
    embed.add_field(name="`g!setchannel #channel`", value="Set the alert channel.", inline=False)
    embed.add_field(name="`g!currentchannel`", value="Show the current alert channel.", inline=False)
    embed.add_field(name="`g!removechannel`", value="Remove the alert channel.", inline=False)
    embed.add_field(name="`g!free epic/steam`", value="🎮 Get free games from Epic or Steam.", inline=False)
    embed.add_field(name="`g!ping`", value="Bot latency check.", inline=False)
    embed.add_field(name="`g!author`", value="Bot creator info.", inline=False)
    embed.add_field(name="`g!sentlist epic/steam`", value="🧾 View sent games.", inline=False)
    embed.set_footer(text="GameClaim • Free Game Tracker")
    await ctx.reply(embed=embed)

@bot.command()
async def free(ctx, platform=None):
    platforms = []
    if platform is None:
        platforms = ["epic", "steam"]
    elif platform.lower() in ["epic", "steam"]:
        platforms = [platform.lower()]
    else:
        await ctx.send("❌ Invalid platform. Use `g!free`, `g!free epic`, or `g!free steam`.")
        return

    embeds = []

    if "epic" in platforms:
        try:
            res = requests.get("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US", timeout=10).json()
            now = datetime.now(timezone.utc)
            for game in res["data"]["Catalog"]["searchStore"]["elements"]:
                title = game.get("title", "Unknown")
                promotions = game.get("promotions")
                if not promotions:
                    continue
                offers = promotions.get("promotionalOffers", [])
                if not offers or not offers[0]["promotionalOffers"]:
                    continue
                offer = offers[0]["promotionalOffers"][0]
                start = datetime.fromisoformat(offer["startDate"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(offer["endDate"].replace("Z", "+00:00"))
                if not (start <= now <= end):
                    continue
                slug = game.get("productSlug")
                if not slug:
                    catalog_ns = game.get("catalogNs")
                    if catalog_ns and isinstance(catalog_ns.get("mappings"), list) and catalog_ns["mappings"]:
                        slug = catalog_ns["mappings"][0].get("pageSlug", "")
                link = f"https://store.epicgames.com/en-US/p/{slug}" if slug else "https://store.epicgames.com/"
                price = game.get("price", {}).get("totalPrice", {}).get("originalPrice", 0) / 100
                images = game.get("keyImages", [])
                thumb = next((img["url"] for img in images if img.get("type") == "Thumbnail"), images[0]["url"] if images else None)
                embed = discord.Embed(title=f"🎮 **{title}**", description=f"[Claim Here]({link})", color=discord.Color.dark_gray())
                embed.add_field(name="💲 Original Price", value=f"${price:.2f}", inline=True)
                embed.add_field(name="🕒 Free for", value=format_duration(end - now), inline=True)
                if thumb:
                    embed.set_image(url=thumb)
                embed.set_footer(text="GameClaim • Epic Freebie")
                embeds.append(embed)
        except Exception as e:
            print("Epic fetch error:", e)

    if "steam" in platforms:
        try:
            res = requests.get("https://www.gamerpower.com/api/giveaways?platform=steam", timeout=10).json()
            for game in res[:5]:
                embed = discord.Embed(title=f"🎮 **{game.get('title')}**", description=game.get("description", "No description"), color=discord.Color.blurple())
                embed.add_field(name="💲 Value", value=game.get("worth", "N/A"), inline=True)
                embed.add_field(name="⏳ Ends On", value=game.get("end_date", "N/A"), inline=True)
                embed.add_field(name="🔗 Claim", value=f"[Click Here]({game.get('open_giveaway_url', '')})", inline=False)
                embed.set_image(url=game.get("thumbnail", ""))
                embed.set_footer(text="GameClaim • Steam Freebie")
                embeds.append(embed)
        except Exception as e:
            print("Steam fetch error:", e)

    if embeds:
        for em in embeds:
            await ctx.send(embed=em)
    else:
        await ctx.send("😔 No free games found right now.")


bot.run(TOKEN)
