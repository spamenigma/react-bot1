import os
import discord
from discord.ext import commands
from datetime import datetime
from collections import defaultdict
import re
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

MONITOR_CHANNEL_ID = 1384853874967449640  # Where reactions happen
LOG_CHANNEL_ID = 1384854378820800675      # Where logs & threads go

# Store sign-ups per emoji per message
reaction_signups = defaultdict(lambda: defaultdict(set))

# Cache summary messages and threads per monitored message
summary_messages = {}
summary_threads = {}

# Emoji ID mappings for wording and emoji display
EMOJI_MAP = {
    1025015433054662676: ("Carrier Star Wing", None),
    718534017082720339: ("Squadron 1", None),
    663133357592412181: ("Attending", None),
    1025067230347661412: ("Athena Training", None),
    663134181089607727: ("Not attending", None),
    792085274149519420: ("Pathfinders", None),
    1025067188102643853: ("Trident", None),
    1091115981788684318: ("Renegade", None),
}

# Updated regex patterns
TIMESTAMP_F_RE = re.compile(r"<t:(\d+):F>")
PING_RE = re.compile(r"^<@!?(\d+)>$")
ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")
MIXED_MENTIONS_RE = re.compile(r"^(<@[!&]?\d+>\s*)+$")

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Discord.py version: {discord.__version__}')
    
    # Check if UI is available
    try:
        test_view = discord.ui.View()
        print("✅ Discord UI components are available!")
    except AttributeError as e:
        print(f"❌ Discord UI components not available: {e}")
    
    await sync_recent_reactions()

def extract_title_and_timestamp(content: str):
    """Extract title and timestamp from message content."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    if not lines:
        return "Sign-Ups", ""
    
    title = None
    
    # Find the first line that isn't just mentions
    for line in lines:
        if MIXED_MENTIONS_RE.match(line) or PING_RE.match(line) or ROLE_MENTION_RE.match(line):
            continue
        title = line
        break
    
    if not title:
        title = "Sign-Ups"
    
    # Extract timestamp
    timestamp_str = ""
    match = TIMESTAMP_F_RE.search(content)
    if match:
        ts = int(match.group(1))
        dt = datetime.utcfromtimestamp(ts)
        timestamp_str = dt.strftime("%A, %d %B %Y %H:%M UTC")
    
    return title, timestamp_str

def emoji_display_and_label(emoji_obj):
    """Get display label for emoji"""
    if hasattr(emoji_obj, "id") and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
        clean_name, color = EMOJI_MAP[emoji_obj.id]
        emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
        return f"{emoji_display} {clean_name}", color
    
    name = str(emoji_obj)
    if name == "⏳":
        return "⏳ Late", None
    if (name == "❌" or name == ":cross~1:" or "cross" in name.lower() or 
        name == "<:cross:663134181089607727>" or ":cross:" in name):
        return "🚫 Not attending", None
    
    if hasattr(emoji_obj, 'name') and hasattr(emoji_obj, 'id') and emoji_obj.id:
        emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
        clean_name = emoji_obj.name.replace('_', ' ').title()
        return f"{emoji_display} {clean_name}", None
    
    return name, None

def build_summary_embed(message_id, title, timestamp_str):
    """Build a rich embed with names listed one per line under each reaction"""
    emoji_data = reaction_signups[message_id]
    
    if not emoji_data:
        embed = discord.Embed(
            title="📋 No sign-ups yet", 
            description="Be the first to react!",
            color=0x808080
        )
        return embed
    
    # Calculate unique attendees
    unique_attendees = set()
    for emoji_key, users in emoji_data.items():
        label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        if "Not attending" not in label and "Late" not in label:
            unique_attendees.update(users)
    
    total_attending = len(unique_attendees)
    
    embed = discord.Embed(
        title=f"📋 {title}",
        description=f"**{total_attending}** total attending",
        color=0x00FF00
    )
    
    if timestamp_str:
        embed.add_field(
            name="⏰ Event Time", 
            value=f"```{timestamp_str}```", 
            inline=False
        )
    
    # Sort reactions
    attending_reactions = []
    other_reactions = []
    
    for emoji_key, users in emoji_data.items():
        if not users:
            continue
            
        label, color = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
        
        if "Not attending" in label or "Late" in label:
            other_reactions.append((emoji_key, users, label))
        else:
            attending_reactions.append((emoji_key, users, label))
    
    # Add attending reactions
    for emoji_key, users, label in attending_reactions:
        count = len(users)
        
        try:
            emoji_obj = discord.PartialEmoji.from_str(emoji_key)
            if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                clean_name = EMOJI_MAP[emoji_obj.id][0]
            else:
                clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
            
            field_name = f"{clean_name} ({count})"
            
            if hasattr(emoji_obj, 'id') and emoji_obj.id:
                emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
            else:
                emoji_display = str(emoji_obj)
                
        except:
            field_name = f"{label} ({count})"
            emoji_display = emoji_key
        
        if users:
            user_list = f"{emoji_display}\n" + "\n".join([user for user in sorted(users)])
        else:
            user_list = f"{emoji_display}\nNone"
        
        if len(user_list) > 1024:
            user_list = user_list[:1020] + "..."
        
        embed.add_field(name=field_name, value=user_list, inline=True)
    
    # Add other reactions
    for emoji_key, users, label in other_reactions:
        if "Not attending" in label:
            count = len(users)
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                else:
                    clean_name = "Not attending"
                
                field_name = f"{clean_name} ({count})"
                
                if hasattr(emoji_obj, 'id') and emoji_obj.id:
                    emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
                else:
                    emoji_display = "🚫"
            except:
                field_name = f"Not attending ({count})"
                emoji_display = "🚫"
            
            user_list = f"{emoji_display}\n{count} not attending"
            
        else:
            count = len(users)
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                elif "Late" in label:
                    clean_name = "Late"
                else:
                    clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
                
                field_name = f"{clean_name} ({count})"
                
                if hasattr(emoji_obj, 'id') and emoji_obj.id:
                    emoji_display = f"<:{emoji_obj.name}:{emoji_obj.id}>"
                else:
                    emoji_display = str(emoji_obj)
            except:
                field_name = f"{label} ({count})"
                emoji_display = emoji_key
            
            if users:
                user_list = f"{emoji_display}\n" + "\n".join([user for user in sorted(users)])
            else:
                user_list = f"{emoji_display}\nNone"
        
        if len(user_list) > 1024:
            user_list = user_list[:1020] + "..."
        
        embed.add_field(name=field_name, value=user_list, inline=True)
    
    embed.set_footer(text=f"Last updated: {datetime.utcnow().strftime('%H:%M UTC')}")
    return embed

def create_summary_view(message_id):
    """Create the button view for summary messages"""
    view = discord.ui.View(timeout=None)  # Persistent view
    
    # Export button
    export_button = discord.ui.Button(
        label="📊 Export Attendance",
        style=discord.ButtonStyle.primary,
        custom_id=f"export_{message_id}"
    )
    
    # Refresh button
    refresh_button = discord.ui.Button(
        label="🔄 Refresh",
        style=discord.ButtonStyle.secondary,
        custom_id=f"refresh_{message_id}"
    )
    
    # Thread button
    thread_button = discord.ui.Button(
        label="🧵 View Logs",
        style=discord.ButtonStyle.secondary,
        custom_id=f"thread_{message_id}"
    )
    
    view.add_item(export_button)
    view.add_item(refresh_button)
    view.add_item(thread_button)
    
    return view

async def sync_recent_reactions(limit=10):
    """Sync reactions from recent messages"""
    print(f"Syncing reactions from last {limit} messages...")
    
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        if not monitor_channel:
            print("Monitor channel not found!")
            return
        
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            print("Log channel not found!")
            return
        
        reaction_signups.clear()
        summary_messages.clear()
        summary_threads.clear()
        
        messages = []
        async for message in monitor_channel.history(limit=limit):
            if message.reactions:
                messages.append(message)
        
        print(f"Found {len(messages)} messages with reactions")
        
        for message in messages:
            print(f"Processing message {message.id}...")
            
            for reaction in message.reactions:
                emoji_str = str(reaction.emoji)
                
                async for user in reaction.users():
                    if not user.bot:
                        reaction_signups[message.id][emoji_str].add(user.name)
        
        print("Reaction sync completed!")
        
        for message in messages:
            if message.id in reaction_signups:
                title, timestamp_str = extract_title_and_timestamp(message.content)
                await post_or_edit_summary(log_channel, message.id, title, timestamp_str)
        
    except Exception as e:
        print(f"Error during reaction sync: {e}")

async def post_or_edit_summary(log_channel, message_id, title, timestamp_str):
    """Post or edit summary message WITH BUTTONS"""
    summary_embed = build_summary_embed(message_id, title, timestamp_str)
    
    # Create buttons
    view = create_summary_view(message_id)
    print(f"Created view with {len(view.children)} buttons for message {message_id}")
    
    if message_id in summary_messages:
        try:
            summary_message = summary_messages[message_id]
            await summary_message.edit(embed=summary_embed, view=view)
            print(f"✅ Updated summary WITH BUTTONS for message {message_id}")
        except discord.NotFound:
            summary_messages.pop(message_id, None)
            summary_message = await log_channel.send(embed=summary_embed, view=view)
            summary_messages[message_id] = summary_message
            print(f"✅ Created new summary WITH BUTTONS for message {message_id}")
    else:
        summary_message = await log_channel.send(embed=summary_embed, view=view)
        summary_messages[message_id] = summary_message
        print(f"✅ Created new summary WITH BUTTONS for message {message_id}")

async def get_or_create_thread(summary_message, title):
    """Get or create thread for summary message"""
    try:
        if summary_message.id in summary_threads:
            thread = summary_threads[summary_message.id]
            await thread.fetch()
            return thread, False
    except (discord.NotFound, AttributeError):
        summary_threads.pop(summary_message.id, None)

    thread = await summary_message.create_thread(
        name=f"Reactions for {title}",
        auto_archive_duration=1440
    )
    summary_threads[summary_message.id] = thread
    return thread, True

def log_line(user, emoji, action):
    """Create log line for thread"""
    time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    if hasattr(emoji, 'id') and emoji.id:
        emoji_display = f"<:{emoji.name}:{emoji.id}>"
    else:
        emoji_display = str(emoji)
    return f"[{time_str}] {user.display_name} {action} reaction {emoji_display}"

# Button interaction handler
@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Handle button clicks"""
    if not interaction.data or interaction.type != discord.InteractionType.component:
        return
    
    custom_id = interaction.data.get('custom_id')
    if not custom_id:
        return
    
    print(f"Button clicked: {custom_id}")
    
    # Handle test buttons
    if custom_id == "test_export":
        await interaction.response.send_message("✅ Test export button works!", ephemeral=True)
        return
    elif custom_id == "test_refresh":
        await interaction.response.send_message("✅ Test refresh button works!", ephemeral=True)
        return
    elif custom_id == "test_button_simple":
        await interaction.response.send_message("✅ Simple button works!", ephemeral=True)
        return
    
    # Parse real button actions
    try:
        action, message_id_str = custom_id.split('_', 1)
        message_id = int(message_id_str)
        print(f"Parsed button: action={action}, message_id={message_id}")
    except (ValueError, AttributeError):
        await interaction.response.send_message("❌ Invalid button action.", ephemeral=True)
        return
    
    # Handle button actions
    if action == "export":
        await handle_export_button(interaction, message_id)
    elif action == "refresh":
        await handle_refresh_button(interaction, message_id)
    elif action == "thread":
        await handle_thread_button(interaction, message_id)
    else:
        await interaction.response.send_message("❌ Unknown button action.", ephemeral=True)

async def handle_export_button(interaction: discord.Interaction, message_id: int):
    """Handle export button click"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        if message_id not in reaction_signups:
            await interaction.followup.send("❌ No reaction data found.", ephemeral=True)
            return
        
        # Quick summary for button export
        emoji_data = reaction_signups[message_id]
        message_author_name = message.author.name
        
        export_text = f"📊 **QUICK EXPORT**\n"
        export_text += f"📋 **Event:** {title}\n"
        export_text += f"📅 **Exported:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        export_text += "=" * 40 + "\n\n"
        
        attending_count = 0
        not_attending_count = 0
        late_count = 0
        
        for emoji_key, users in emoji_data.items():
            if not users:
                continue
            label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
            if "Not attending" in label:
                not_attending_count += len(users)
            elif "Late" in label:
                late_count += len(users)
            else:
                attending_count += len([u for u in users if u != message_author_name])
        
        export_text += f"📈 **SUMMARY**\n"
        export_text += f"✅ Attending: {attending_count}\n"
        export_text += f"⏳ Late: {late_count}\n"
        export_text += f"❌ Not Attending: {not_attending_count}\n"
        export_text += f"👤 Event Creator: {message_author_name} (excluded)\n\n"
        export_text += f"💡 Use `!export_attendance {message_id}` for detailed lists."
        
        await interaction.followup.send(f"```\n{export_text}\n```", ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

async def handle_refresh_button(interaction: discord.Interaction, message_id: int):
    """Handle refresh button click"""
    try:
        await interaction.response.defer()
        
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        await post_or_edit_summary(interaction.channel, message_id, title, timestamp_str)
        await interaction.followup.send("✅ Summary refreshed!", ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

async def handle_thread_button(interaction: discord.Interaction, message_id: int):
    """Handle thread button click"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        if message_id in summary_threads:
            thread = summary_threads[message_id]
            try:
                await thread.fetch()
                await interaction.followup.send(f"🧵 **Thread:** {thread.mention}", ephemeral=True)
            except discord.NotFound:
                await interaction.followup.send("❌ Thread not found.", ephemeral=True)
        else:
            await interaction.followup.send("❌ No thread found. Threads are created when reactions are logged.", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return
    
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    reaction_signups[payload.message_id][emoji_str].add(user.name)

    title, timestamp_str = extract_title_and_timestamp(message.content)
    await post_or_edit_summary(log_channel, payload.message_id, title, timestamp_str)

    # Create thread for logging
    if payload.message_id in summary_messages:
        summary_message = summary_messages[payload.message_id]
        thread, created = await get_or_create_thread(summary_message, title)
        
        if created:
            try:
                await thread.send(f"🧵 **Reaction log for: {title}**\nAll reaction changes will be logged here.")
            except Exception as e:
                print(f"Failed to send initial thread message: {e}")
        
        try:
            await thread.send(log_line(user, payload.emoji, "added"))
        except Exception as e:
            print(f"Failed to send add log in thread: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.channel_id != MONITOR_CHANNEL_ID:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return
    
    try:
        monitor_channel = guild.get_channel(payload.channel_id)
        message = await monitor_channel.fetch_message(payload.message_id)
    except Exception:
        return

    user = guild.get_member(payload.user_id) or await bot.fetch_user(payload.user_id)
    emoji_str = str(payload.emoji)

    if user.name in reaction_signups[payload.message_id][emoji_str]:
        reaction_signups[payload.message_id][emoji_str].remove(user.name)
        if not reaction_signups[payload.message_id][emoji_str]:
            del reaction_signups[payload.message_id][emoji_str]

    title, timestamp_str = extract_title_and_timestamp(message.content)
    await post_or_edit_summary(log_channel, payload.message_id, title, timestamp_str)

    # Log to thread
    if payload.message_id in summary_messages:
        summary_message = summary_messages[payload.message_id]
        thread, created = await get_or_create_thread(summary_message, title)
        
        if created:
            try:
                await thread.send(f"🧵 **Reaction log for: {title}**\nAll reaction changes will be logged here.")
            except Exception as e:
                print(f"Failed to send initial thread message: {e}")
        
        try:
            await thread.send(log_line(user, payload.emoji, "removed"))
        except Exception as e:
            print(f"Failed to send remove log in thread: {e}")

# ===== COMMANDS =====

# Basic test commands
@bot.command(name="ping")
async def ping(ctx):
    """Simple test command"""
    await ctx.send("🏓 Pong! Bot is responding.")

@bot.command(name="version")
async def version_check(ctx):
    """Check discord.py version"""
    try:
        version = discord.__version__
        embed = discord.Embed(title="Version Info", color=0x00FF00)
        embed.add_field(name="Discord.py Version", value=version, inline=False)
        
        # Test UI availability
        try:
            discord.ui.View()
            ui_status = "✅ Available"
        except:
            ui_status = "❌ Not Available"
        
        embed.add_field(name="UI Components", value=ui_status, inline=False)
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Version check error: {e}")

@bot.command(name="button_test")
async def button_test(ctx):
    """Test if buttons work at all"""
    try:
        print("Creating simple button test...")
        
        view = discord.ui.View(timeout=60)
        
        button = discord.ui.Button(
            label="Test Button", 
            style=discord.ButtonStyle.primary,
            custom_id="test_button_simple"
        )
        
        view.add_item(button)
        
        await ctx.send("🔘 **Button Test** - Click the button below:", view=view)
        print("Button test sent!")
        
    except Exception as e:
        print(f"Button test error: {e}")
        await ctx.send(f"❌ Button test failed: {e}")

# Core commands
@bot.command(name="sync_reactions")
async def manual_sync_reactions(ctx, limit: int = 10):
    """Manually sync reactions from recent messages"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    await ctx.send(f"🔄 Syncing reactions from last {limit} messages...")
    await sync_recent_reactions(limit)
    await ctx.send("✅ Reaction sync completed! Check for buttons on summaries.")

@bot.command(name="test_status")
async def test_status(ctx):
    """Show current bot status"""
    embed = discord.Embed(title="🧪 Bot Test Status", color=0x00FFFF)
    
    total_messages = len(reaction_signups)
    total_reactions = sum(len(emojis) for emojis in reaction_signups.values())
    
    embed.add_field(
        name="📊 Data Status",
        value=f"Tracking {total_messages} messages\nWith {total_reactions} different reactions",
        inline=False
    )
    
    embed.add_field(
        name="📋 Summary Status",
        value=f"Active summaries: {len(summary_messages)}\nActive threads: {len(summary_threads)}",
        inline=False
    )
    
    embed.add_field(
        name="🎯 Channel Config",
        value=f"Monitor: <#{MONITOR_CHANNEL_ID}>\nLogs: <#{LOG_CHANNEL_ID}>",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="show_emoji_map")
async def show_emoji_map(ctx):
    """Display the current EMOJI_MAP configuration"""
    embed = discord.Embed(title="🗺️ Current Emoji Map Configuration", color=0x00FFFF)
    
    if not EMOJI_MAP:
        embed.description = "No emojis configured in EMOJI_MAP"
        await ctx.send(embed=embed)
        return
    
    for emoji_id, (clean_name, color) in EMOJI_MAP.items():
        try:
            guild_emoji = discord.utils.get(ctx.guild.emojis, id=emoji_id)
            if guild_emoji:
                emoji_display = str(guild_emoji)
                status = "✅ Found in server"
            else:
                emoji_display = f"<:unknown:{emoji_id}>"
                status = "❌ Not found in server"
        except:
            emoji_display = f"<:unknown:{emoji_id}>"
            status = "❌ Error"
        
        embed.add_field(
            name=f"ID: {emoji_id}",
            value=f"**Emoji:** {emoji_display}\n**Label:** {clean_name}\n**Status:** {status}",
            inline=True
        )
    
    embed.add_field(
        name="Unicode Emojis",
        value="⏳ Late\n🚫 Not attending (❌, :cross:)",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="debug_reactions")
async def debug_reactions(ctx, message_id: int):
    """Debug command to see current reaction data for a message"""
    if message_id in reaction_signups:
        embed = discord.Embed(title=f"Debug: Reaction Data for {message_id}", color=0x00FFFF)
        for emoji_key, users in reaction_signups[message_id].items():
            embed.add_field(
                name=f"Emoji: {emoji_key}",
                value=f"Users: {', '.join(users) if users else 'None'}",
                inline=False
            )
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"No reaction data found for message {message_id}")

@bot.command(name="refresh_summary")
async def refresh_summary(ctx, message_id: int):
    """Manually refresh a summary for a specific message"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        await post_or_edit_summary(ctx.channel, message_id, title, timestamp_str)
        await ctx.send(f"✅ Refreshed summary for: {title} (with buttons!)")
    except Exception as e:
        await ctx.send(f"❌ Error refreshing summary: {e}")

@bot.command(name="export_attendance")
async def export_attendance(ctx, message_id: int):
    """Export attendance list including not attending users"""
    try:
        monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
        message = await monitor_channel.fetch_message(message_id)
        title, timestamp_str = extract_title_and_timestamp(message.content)
        
        if message_id not in reaction_signups:
            await ctx.send("❌ No reaction data found for this message.")
            return
        
        emoji_data = reaction_signups[message_id]
        message_author_name = message.author.name
        
        # Build export text
        export_text = f"📊 **ATTENDANCE EXPORT**\n"
        export_text += f"📋 **Event:** {title}\n"
        if timestamp_str:
            export_text += f"⏰ **Time:** {timestamp_str}\n"
        export_text += f"📅 **Exported:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        export_text += "=" * 50 + "\n\n"
        
        # Track all users and their attendance status
        attending_reactions = []
        not_attending_reactions = []
        late_reactions = []
        
        for emoji_key, users in emoji_data.items():
            if not users:
                continue
                
            label, _ = emoji_display_and_label(discord.PartialEmoji.from_str(emoji_key))
            
            # Get clean emoji name
            try:
                emoji_obj = discord.PartialEmoji.from_str(emoji_key)
                if hasattr(emoji_obj, 'id') and emoji_obj.id and emoji_obj.id in EMOJI_MAP:
                    clean_name = EMOJI_MAP[emoji_obj.id][0]
                elif "Not attending" in label:
                    clean_name = "Not attending"
                elif "Late" in label:
                    clean_name = "Late"
                else:
                    clean_name = emoji_obj.name.replace('_', ' ').title() if hasattr(emoji_obj, 'name') else "Unknown"
            except:
                clean_name = label
            
            if "Not attending" in label:
                not_attending_reactions.append((clean_name, users))
            elif "Late" in label:
                late_reactions.append((clean_name, users))
            else:
                attending_reactions.append((clean_name, users))
        
        # Calculate totals
        unique_attending = set()
        for _, users in attending_reactions:
            unique_attending.update(users)
        
        # Remove message author from attending count
        if message_author_name in unique_attending:
            unique_attending.remove(message_author_name)
        
        total_attending = len(unique_attending)
        total_not_attending = sum(len(users) for _, users in not_attending_reactions)
        total_late = sum(len(users) for _, users in late_reactions)
        
        export_text += f"📈 **SUMMARY**\n"
        export_text += f"✅ Attending: {total_attending}\n"
        export_text += f"⏳ Late: {total_late}\n"
        export_text += f"❌ Not Attending: {total_not_attending}\n"
        export_text += f"👤 Event Creator: {message_author_name} (excluded from attending count)\n\n"
        
        # List attending users
        if attending_reactions:
            export_text += "✅ **ATTENDING**\n"
            for reaction_name, users in attending_reactions:
                # Filter out message author
                filtered_users = [u for u in users if u != message_author_name]
                if filtered_users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(filtered_users))}\n"
            export_text += "\n"
        
        # List late users
        if late_reactions:
            export_text += "⏳ **LATE**\n"
            for reaction_name, users in late_reactions:
                # Filter out message author
                filtered_users = [u for u in users if u != message_author_name]
                if filtered_users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(filtered_users))}\n"
            export_text += "\n"
        
        # List not attending users
        if not_attending_reactions:
            export_text += "❌ **NOT ATTENDING**\n"
            for reaction_name, users in not_attending_reactions:
                # Don't filter message author for not attending
                if users:
                    export_text += f"**{reaction_name}:** {', '.join(sorted(users))}\n"
            export_text += "\n"
        
        # If export is too long, send as file
        if len(export_text) > 1900:
            # Create a text file
            import io
            file_content = export_text
            file_name = f"attendance_{title.replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.txt"
            
            discord_file = discord.File(fp=io.BytesIO(file_content.encode('utf-8')), filename=file_name)
            await ctx.send("📊 **Attendance export (file too large for message):**", file=discord_file)
        else:
            # Send as message
            await ctx.send(f"```\n{export_text}\n```")
            
    except Exception as e:
        await ctx.send(f"❌ Error exporting attendance: {e}")

@bot.command(name="clear_all_logs")
async def clear_all_logs(ctx, confirm: str = None):
    """Delete all messages in the log channel (for testing)"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    if confirm != "CONFIRM":
        await ctx.send("⚠️ **WARNING**: This will delete ALL messages in this channel!\n"
                      "To confirm, use: `!clear_all_logs CONFIRM`")
        return
    
    try:
        await ctx.send("🗑️ Starting to clear all logs...")
        
        # Clear bot's cache first
        summary_messages.clear()
        
        deleted_count = 0
        
        # Delete messages in batches (Discord has limits)
        async for message in ctx.channel.history(limit=None):
            try:
                await message.delete()
                deleted_count += 1
                
                # Add small delay to avoid rate limits
                if deleted_count % 10 == 0:
                    await ctx.send(f"Deleted {deleted_count} messages...", delete_after=3)
                    
            except discord.NotFound:
                # Message already deleted
                pass
            except discord.Forbidden:
                await ctx.send(f"❌ Permission denied deleting message {message.id}")
                break
            except Exception as e:
                print(f"Error deleting message: {e}")
        
        # Send final confirmation (this will be the only message left)
        await ctx.send(f"✅ Cleared {deleted_count} messages from log channel!")
        
    except Exception as e:
        await ctx.send(f"❌ Error clearing logs: {e}")

@bot.command(name="clear_all_threads")
async def clear_all_threads(ctx, confirm: str = None):
    """Delete all threads in the log channel (for testing)"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    if confirm != "CONFIRM":
        await ctx.send("⚠️ **WARNING**: This will delete ALL threads in this channel!\n"
                      "To confirm, use: `!clear_all_threads CONFIRM`")
        return
    
    try:
        await ctx.send("🧵 Starting to clear all threads...")
        
        # Clear bot's cache first
        summary_threads.clear()
        
        deleted_count = 0
        
        # Get all threads (active and archived)
        active_threads = ctx.channel.threads
        
        # Also get archived threads
        archived_threads = []
        async for thread in ctx.channel.archived_threads(limit=None):
            archived_threads.append(thread)
        
        all_threads = active_threads + archived_threads
        
        for thread in all_threads:
            try:
                await thread.delete()
                deleted_count += 1
                print(f"Deleted thread: {thread.name}")
                
            except discord.NotFound:
                # Thread already deleted
                pass
            except discord.Forbidden:
                await ctx.send(f"❌ Permission denied deleting thread {thread.name}")
            except Exception as e:
                print(f"Error deleting thread {thread.name}: {e}")
        
        await ctx.send(f"✅ Cleared {deleted_count} threads from log channel!")
        
    except Exception as e:
        await ctx.send(f"❌ Error clearing threads: {e}")

@bot.command(name="clear_all_data")
async def clear_all_data(ctx, confirm: str = None):
    """Clear all bot data, logs, and threads (nuclear option for testing)"""
    if ctx.channel.id != LOG_CHANNEL_ID:
        await ctx.send("This command can only be used in the log channel.")
        return
    
    if confirm != "NUCLEAR":
        await ctx.send("⚠️ **NUCLEAR WARNING**: This will:\n"
                      "• Delete ALL messages in this channel\n"
                      "• Delete ALL threads in this channel\n"
                      "• Clear ALL bot reaction data\n"
                      "To confirm, use: `!clear_all_data NUCLEAR`")
        return
    
    try:
        await ctx.send("💥 NUCLEAR CLEANUP INITIATED...")
        
        # Clear all bot data
        reaction_signups.clear()
        summary_messages.clear()
        summary_threads.clear()
        
        # Clear threads first
        await clear_all_threads(ctx, "CONFIRM")
        
        # Then clear messages
        await clear_all_logs(ctx, "CONFIRM")
        
        # Final message
        await ctx.send("💥 **NUCLEAR CLEANUP COMPLETE!**\n"
                      "All data, logs, and threads have been cleared.\n"
                      "Ready for fresh testing!")
        
    except Exception as e:
        await ctx.send(f"❌ Error during nuclear cleanup: {e}")

@bot.command(name="add_buttons_to_all")
async def add_buttons_to_all(ctx):
    """Add buttons to all existing summary messages"""
    if not summary_messages:
        await ctx.send("❌ No summary messages found in memory.")
        return
        
    await ctx.send(f"🔄 Adding buttons to {len(summary_messages)} existing summaries...")
    
    updated_count = 0
    for message_id, summary_msg in summary_messages.items():
        try:
            # Get original message details
            monitor_channel = bot.get_channel(MONITOR_CHANNEL_ID)
            original_message = await monitor_channel.fetch_message(message_id)
            title, timestamp_str = extract_title_and_timestamp(original_message.content)
            
            # Build new embed and view with buttons
            summary_embed = build_summary_embed(message_id, title, timestamp_str)
            view = create_summary_view(message_id)
            
            # Update with buttons
            await summary_msg.edit(embed=summary_embed, view=view)
            updated_count += 1
            print(f"✅ Added buttons to summary for message {message_id}")
            
        except Exception as e:
            print(f"Failed to update summary for message {message_id}: {e}")
    
    await ctx.send(f"✅ Successfully added buttons to {updated_count} summaries!")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["BOT_TOKEN"])
