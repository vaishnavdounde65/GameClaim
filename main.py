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

# Load ping roles
PING_ROLES_FILE = 'ping_roles.json'
if os.path.exists(PING_ROLES_FILE):
    with open(PING_ROLES_FILE, "r") as f:
        ping_roles = json.load(f)
else:
    ping_roles = {}

def save_ping_roles():
    with open(PING_ROLES_FILE, "w") as f:
        json.dump(ping_roles, f, indent=4)

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

async def send_to_all_guilds(embed, platform, game_key, timestamp=None):
    """Helper function to send embeds to all configured guilds"""
    success_count = 0
    total_guilds = len(guild_channels)
    
    for guild_id, channel_id in guild_channels.items():
        try:
            # Get the channel
            channel = bot.get_channel(channel_id)
            if channel is None:
                print(f"❌ Channel {channel_id} not found for guild {guild_id}")
                continue
            
            # Get guild to check permissions
            guild = bot.get_guild(int(guild_id))
            if guild is None:
                print(f"❌ Guild {guild_id} not found")
                continue
                
            # Check if bot has permission to send messages
            if not channel.permissions_for(guild.me).send_messages:
                print(f"❌ No send permissions in channel {channel_id} for guild {guild_id}")
                continue
            
            # Get ping role if set
            ping_role_id = ping_roles.get(guild_id)
            ping_mention = f"<@&{ping_role_id}> " if ping_role_id else ""
            
            # Send the message
            await channel.send(ping_mention, embed=embed)
            success_count += 1
            
        except discord.Forbidden:
            print(f"❌ Missing permissions in guild {guild_id}")
        except discord.HTTPException as e:
            print(f"❌ Failed to send message in guild {guild_id}: {e}")
        except Exception as e:
            print(f"❌ Unexpected error in guild {guild_id}: {e}")
    
    # Only mark as sent if at least one guild received it
    if success_count > 0:
        if platform == "epic":
            sent_games["epic"][game_key] = timestamp or datetime.now(timezone.utc).isoformat()
        elif platform == "steam":
            sent_games["steam"][game_key] = datetime.now(timezone.utc).isoformat()
        save_sent_games()
        print(f"✅ Sent to {success_count}/{total_guilds} servers")
    else:
        print("❌ Failed to send to any servers")

@bot.command()
async def setchannel(ctx, channel: discord.TextChannel):
    """Set the channel for game alerts (Admin only)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("❌ You need administrator permissions to set the alert channel.")
        return
    
    guild_channels[str(ctx.guild.id)] = channel.id
    save_channels()
    
    # Check permissions
    if channel.permissions_for(ctx.guild.me).send_messages:
        await ctx.send(f"✅ Game alerts will now be sent to {channel.mention}")
    else:
        await ctx.reply(f"⚠️ Alerts channel set to {channel.mention} but I don't have send permissions there!")

@bot.command()
async def updateping(ctx, role: discord.Role = None):
    """Set a role to ping for new game alerts (Admin only)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("❌ You need administrator permissions to set the ping role.")
        return
    
    guild_id = str(ctx.guild.id)
    if role is None:
        ping_roles[guild_id] = None
        await ctx.send("✅ Ping role removed. No one will be pinged for new games.")
    else:
        ping_roles[guild_id] = role.id
        await ctx.send(f"✅ Ping role set to {role.mention}. This role will be mentioned for new game alerts.")
    save_ping_roles()

@bot.command()
async def currentchannel(ctx):
    """Check the current alert channel and ping role settings"""
    gid = str(ctx.guild.id)
    if gid in guild_channels:
        channel = bot.get_channel(guild_channels[gid])
        if channel:
            ping_role_id = ping_roles.get(gid)
            # Use role ID without triggering ping
            ping_info = "No ping role set" if ping_role_id is None else f"Ping role: `@{bot.get_guild(int(gid)).get_role(ping_role_id).name}`"
            await ctx.reply(f"📢 Current alert channel is: {channel.mention}\n{ping_info}")
        else:
            await ctx.reply("❌ The saved channel does not exist anymore.")
    else:
        await ctx.reply("⚠️ No alert channel set. Use `g!setchannel #channel`.")

@bot.command()
async def removechannel(ctx):
    """Remove the alert channel (Admin only)"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.reply("❌ You need administrator permissions to remove the alert channel.")
        return
    
    gid = str(ctx.guild.id)
    if gid in guild_channels:
        del guild_channels[gid]
        save_channels()
        await ctx.reply("✅ Alert channel removed.")
    else:
        await ctx.reply("⚠️ No alert channel set.")

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
    try:
        res = requests.get("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US", timeout=10).json()
    except Exception as e:
        print(f"❌ Failed to fetch Epic games: {e}")
        return
    
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
        
        slug = game.get("productSlug") or game.get("catalogNs", {}).get("mappings", [{}])[0].get("pageSlug", "")
        link = f"https://store.epicgames.com/en-US/p/{slug}" if slug else "https://store.epicgames.com/"
        price = game.get("price", {}).get("totalPrice", {}).get("originalPrice", 0) / 100
        images = game.get("keyImages", [])
        thumb = next((img["url"] for img in images if img.get("type") == "Thumbnail"), images[0]["url"] if images else None)
        
        embed = discord.Embed(
            title=f"🎮 **{title}**",
            description=f"[Click to claim the game here]({link})",
            color=discord.Color.light_gray()
        )
        embed.add_field(name="💲 Original Price", value=f"${price:.2f}", inline=True)
        embed.add_field(name="🕒 Offer Period", value=format_duration(end - now), inline=False)
        if thumb:
            embed.set_image(url=thumb)
        embed.set_footer(text="GameClaim • Epic Freebie")
        
        await send_to_all_guilds(embed, "epic", title, start.isoformat())

@tasks.loop(hours=1)
async def steam_games():
    await bot.wait_until_ready()
    try:
        res = requests.get("https://www.gamerpower.com/api/giveaways?platform=steam", timeout=10).json()
    except Exception as e:
        print(f"❌ Failed to fetch Steam games: {e}")
        return
    
    for game in res[:5]:  # Limit to 5 most recent
        game_id = str(game.get("id"))
        if game_id in sent_games["steam"]:
            continue
        
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
        
        await send_to_all_guilds(embed, "steam", game_id)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="**GameClaim Bot Commands**",
        description="Use `g!` as the prefix for all commands.",
        color=discord.Color.blue()
    )
    embed.add_field(name="`g!setchannel #channel`", value="Set the alert channel.", inline=False)
    embed.add_field(name="`g!updateping @role`", value="Set a role to ping for new games (or 'none' to disable), also bot should have permission to ping that role.", inline=False)
    embed.add_field(name="`g!currentchannel`", value="Show the current alert channel.", inline=False)
    embed.add_field(name="`g!removechannel`", value="Remove the alert channel.", inline=False)
    embed.add_field(name="`g!free epic/steam`", value="🎮 Get free games from Epic or Steam.", inline=False)
    embed.add_field(name="`g!ping`", value="Bot latency check.", inline=False)
    embed.add_field(name="`g!author`", value="Bot creator info.", inline=False)
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
            await ctx.send("❌ Failed to fetch Epic games. Please try again later.")

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
            await ctx.send("❌ Failed to fetch Steam games. Please try again later.")

    if embeds:
        for em in embeds:
            await ctx.send(embed=em)
    else:
        await ctx.send("😔 No free games found right now.")

bot.run(TOKEN)
