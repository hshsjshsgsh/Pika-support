import discord
from discord.ext import commands, tasks
import os
import random
import asyncio
import json
from datetime import datetime, timedelta
from keep_alive import keep_alive
import re
import time

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# JSON Database functions
def init_db():
    """Initialize JSON database files"""
    db_files = {
        'warnings.json': [],
        'user_levels.json': {},
        'guild_config.json': {},
        'level_roles.json': {},
        'automod_warnings.json': {},
        'user_accounts.json': {},
        'tickets.json': []
    }
    
    for filename, default_data in db_files.items():
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                json.dump(default_data, f)

def load_json(filename):
    """Load data from JSON file"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if filename != 'warnings.json' and filename != 'tickets.json' else []

def save_json(filename, data):
    """Save data to JSON file"""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

# Helper functions
def parse_time(time_str):
    """Parse time string like '1h', '30m', '2d' into timedelta"""
    if not time_str:
        return None
    
    match = re.match(r'(\d+)([mhdmo]+)', time_str.lower())
    if not match:
        return None
    
    amount, unit = match.groups()
    amount = int(amount)
    
    if unit == 'm':
        return timedelta(minutes=amount)
    elif unit == 'h':
        return timedelta(hours=amount)
    elif unit == 'd':
        return timedelta(days=amount)
    elif unit == 'mo':
        return timedelta(days=amount * 30)  # Approximate
    
    return None

async def is_staff(ctx):
    """Check if user is staff (has manage messages permission or has staff role)"""
    if ctx.author.guild_permissions.manage_messages:
        return True
    
    # Check if user has any staff roles
    guild_config = load_json('guild_config.json')
    config = guild_config.get(str(ctx.guild.id), {})
    staff_roles = config.get('staff_roles', '')
    
    if staff_roles:
        staff_role_ids = staff_roles.split(',')
        user_role_ids = [str(role.id) for role in ctx.author.roles]
        return any(role_id in staff_role_ids for role_id in user_role_ids)
    
    return False

# Bad words list (basic example - you can expand this)
BAD_WORDS = ['badword1', 'badword2', 'spam', 'test_bad']

# Automod functions
async def check_spam(message):
    """Check if message is spam (5 same consecutive messages in 5 seconds)"""
    if not message.guild:
        return False
    
    channel = message.channel
    count = 0
    now = datetime.now()
    last_content = None
    
    async for msg in channel.history(limit=6):
        if msg.author == message.author:
            # Check if message is within 5 seconds and has same content
            msg_time = msg.created_at.replace(tzinfo=None)
            time_diff = (now - msg_time).total_seconds()
            
            if time_diff <= 5:
                if last_content is None:
                    last_content = msg.content
                    count = 1
                elif msg.content == last_content:
                    count += 1
                else:
                    break
            else:
                break
        else:
            break
    
    return count >= 5

async def check_emoji_spam(message):
    """Check if user sends 5 consecutive emoji messages in 5 seconds"""
    if not message.guild:
        return False
    
    channel = message.channel
    count = 0
    now = datetime.now()
    emoji_pattern = r'<:[^:]+:\d+>|[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]'
    
    async for msg in channel.history(limit=6):
        if msg.author == message.author:
            msg_time = msg.created_at.replace(tzinfo=None)
            time_diff = (now - msg_time).total_seconds()
            
            if time_diff <= 5:
                emojis = re.findall(emoji_pattern, msg.content)
                if len(emojis) > 5:  # Message has more than 5 emojis
                    count += 1
                else:
                    break
            else:
                break
        else:
            break
    
    return count >= 5

async def check_bad_words(content):
    """Check if message contains 3 or more bad words"""
    content_lower = content.lower()
    bad_word_count = 0
    
    for bad_word in BAD_WORDS:
        # Check if bad word is at start, end, or standalone
        words = content_lower.split()
        for word in words:
            if word.startswith(bad_word) or word.endswith(bad_word) or word == bad_word:
                bad_word_count += 1
                break
    
    return bad_word_count >= 3

async def check_links(content):
    """Check if message contains links"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return bool(re.search(url_pattern, content))

# Bot events
@bot.event
async def on_ready():
    print(f'{bot.user} has logged in!')
    init_db()
    if not level_check.is_running():
        level_check.start()

@bot.event
async def on_member_join(member):
    """Handle new member joins for welcomer system"""
    guild_id = str(member.guild.id)
    
    guild_config = load_json('guild_config.json')
    config = guild_config.get(guild_id, {})
    
    if config.get('welcomer_enabled') and config.get('welcomer_channel'):
        channel = bot.get_channel(config['welcomer_channel'])
        if channel:
            welcome_message = f"Welcome! <@{member.id}> Thanks for joining my server you are **GOAT** <:w_trkis:1400194042234667120> <:GOAT:1400194575125188811>"
            await channel.send(welcome_message)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Process leveling
    await process_leveling(message)
    
    # Process automod
    await process_automod(message)
    
    await bot.process_commands(message)

async def process_leveling(message):
    """Process user leveling system"""
    if not message.guild:
        return
    
    user_id = str(message.author.id)
    guild_id = str(message.guild.id)
    
    user_levels = load_json('user_levels.json')
    key = f"{guild_id}_{user_id}"
    
    now = datetime.now().isoformat()
    
    if key in user_levels:
        user_data = user_levels[key]
        last_message = datetime.fromisoformat(user_data.get('last_message', now))
        
        # Only give XP if 60 seconds have passed since last message
        if (datetime.now() - last_message).total_seconds() >= 60:
            user_data['xp'] = user_data.get('xp', 0) + 15
            new_level = user_data['xp'] // 100
            old_level = user_data.get('level', 0)
            user_data['level'] = new_level
            user_data['last_message'] = now
            
            # Check if leveled up
            if new_level > old_level:
                await handle_level_up(message, new_level)
    else:
        user_levels[key] = {
            'xp': 15,
            'level': 0,
            'last_message': now
        }
    
    save_json('user_levels.json', user_levels)

async def handle_level_up(message, new_level):
    """Handle level up notification and role assignment"""
    guild_id = str(message.guild.id)
    user_id = message.author.id
    
    guild_config = load_json('guild_config.json')
    config = guild_config.get(guild_id, {})
    
    # Send level up message
    if config.get('leveling_channel'):
        channel = bot.get_channel(config['leveling_channel'])
        if channel:
            await channel.send(
                f"**Thanks For Showing Your Activity <@{user_id}>! You just Stumbled Up To Level **{new_level}**. Keep GOING!!!!!** <:abilities:1402690411759407185>"
            )
    
    # Check for level roles
    level_roles = load_json('level_roles.json')
    guild_roles = level_roles.get(guild_id, {})
    
    if str(new_level) in guild_roles:
        for role_id in guild_roles[str(new_level)]:
            role = message.guild.get_role(int(role_id))
            if role:
                try:
                    await message.author.add_roles(role)
                except:
                    pass

async def process_automod(message):
    """Process automod checks"""
    if not message.guild or message.author.guild_permissions.manage_messages:
        return
    
    guild_id = str(message.guild.id)
    guild_config = load_json('guild_config.json')
    config = guild_config.get(guild_id, {})
    
    if not config.get('automod_enabled'):
        return
    
    spam_channels = config.get('spam_channels', '').split(',')
    link_channels = config.get('link_channels', '').split(',')
    
    violations = []
    
    # Check spam (if not in spam channel)
    if str(message.channel.id) not in spam_channels:
        if await check_spam(message):
            violations.append("spam")
    
    # Check emoji spam
    if await check_emoji_spam(message):
        violations.append("emoji spam")
    
    # Check bad words
    if await check_bad_words(message.content):
        violations.append("inappropriate language")
    
    # Check links (if not in link channel)
    if str(message.channel.id) not in link_channels:
        if await check_links(message.content):
            violations.append("unauthorized links")
    
    if violations:
        await handle_automod_violation(message, violations, config.get('automod_log_channel'))

async def handle_automod_violation(message, violations, log_channel_id):
    """Handle automod violations"""
    user_id = str(message.author.id)
    guild_id = str(message.guild.id)
    
    automod_warnings = load_json('automod_warnings.json')
    key = f"{guild_id}_{user_id}"
    
    warning_count = automod_warnings.get(key, 0) + 1
    automod_warnings[key] = warning_count
    save_json('automod_warnings.json', automod_warnings)
    
    # Delete the violating message
    try:
        await message.delete()
    except:
        pass
    
    # Send DM warning
    try:
        violation_text = ", ".join(violations)
        await message.author.send(
            f"Warning! Your message in **{message.guild.name}** was removed for: {violation_text}. "
            f"This is warning {warning_count}/3. At 3 warnings, you will be temporarily muted."
        )
    except:
        pass
    
    # Log the violation
    if log_channel_id:
        log_channel = bot.get_channel(log_channel_id)
        if log_channel:
            embed = discord.Embed(
                title="Automod Violation",
                color=0xff0000,
                timestamp=datetime.now()
            )
            embed.add_field(name="User", value=f"{message.author.mention}", inline=True)
            embed.add_field(name="Channel", value=f"{message.channel.mention}", inline=True)
            embed.add_field(name="Violations", value=", ".join(violations), inline=True)
            embed.add_field(name="Warning Count", value=f"{warning_count}/3", inline=True)
            await log_channel.send(embed=embed)
    
    # Auto-timeout at 3 warnings
    if warning_count >= 3:
        try:
            # Use Discord's built-in timeout (not custom implementation)
            timeout_until = datetime.now() + timedelta(minutes=10)
            await message.author.edit(timed_out_until=timeout_until, reason="Automod: 3 violations reached")
            
            # Reset warning count
            automod_warnings[key] = 0
            save_json('automod_warnings.json', automod_warnings)
            
            try:
                await message.author.send(
                    f"You have been automatically timed out for 10 minutes in **{message.guild.name}** "
                    "for reaching 3 automod violations."
                )
            except:
                pass
        except:
            # Fallback to old timeout method if edit doesn't work
            try:
                timeout_until = datetime.now() + timedelta(minutes=10)
                await message.author.timeout(timeout_until, reason="Automod: 3 violations reached")
            except:
                pass

# Moderation Commands
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    """Warn a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    warnings = load_json('warnings.json')
    warning = {
        'user_id': member.id,
        'guild_id': ctx.guild.id,
        'reason': reason,
        'timestamp': datetime.now().isoformat()
    }
    warnings.append(warning)
    save_json('warnings.json', warnings)
    
    embed = discord.Embed(
        title="User Warned",
        color=0xffaa00,
        timestamp=datetime.now()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=True)
    embed.add_field(name="Warned by", value=ctx.author.mention, inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def warn_hs(ctx, member: discord.Member):
    """View user's warning history"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    warnings = load_json('warnings.json')
    user_warnings = [w for w in warnings if w['user_id'] == member.id and w['guild_id'] == ctx.guild.id]
    
    if not user_warnings:
        await ctx.send(f"{member.mention} has no warnings.")
        return
    
    embed = discord.Embed(
        title=f"Warning History for {member.display_name}",
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    for i, warning in enumerate(user_warnings[-10:], 1):  # Show last 10 warnings
        embed.add_field(
            name=f"Warning {i}",
            value=f"**Reason:** {warning['reason']}\n**Date:** {warning['timestamp']}",
            inline=False
        )
    
    embed.set_footer(text=f"Total warnings: {len(user_warnings)}")
    await ctx.send(embed=embed)

@bot.command()
async def warn_rmv(ctx, member: discord.Member, number: int):
    """Remove a specific number of warnings from a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    warnings = load_json('warnings.json')
    user_warnings = [w for w in warnings if w['user_id'] == member.id and w['guild_id'] == ctx.guild.id]
    
    if not user_warnings:
        await ctx.send(f"{member.mention} has no warnings to remove.")
        return
    
    # Remove the specified number of most recent warnings
    removed_count = min(number, len(user_warnings))
    user_warnings = user_warnings[:-removed_count]
    
    # Rebuild warnings list without the removed ones
    new_warnings = [w for w in warnings if not (w['user_id'] == member.id and w['guild_id'] == ctx.guild.id)]
    new_warnings.extend(user_warnings)
    save_json('warnings.json', new_warnings)
    
    await ctx.send(f"Removed {removed_count} warning(s) from {member.mention}.")

@bot.command()
async def mute(ctx, member: discord.Member, time_str: str = None, *, reason="No reason provided"):
    """Mute a user for a specified time (1m to 7d)"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    if not time_str:
        await ctx.send("Please provide a time duration (e.g., 30m, 2h, 1d).")
        return
    
    duration = parse_time(time_str)
    if not duration:
        await ctx.send("Invalid time format. Use m (minutes), h (hours), d (days).")
        return
    
    # Check if duration is within limits (1m to 7d)
    min_duration = timedelta(minutes=1)
    max_duration = timedelta(days=7)
    
    if duration < min_duration or duration > max_duration:
        await ctx.send("Mute duration must be between 1 minute and 7 days.")
        return
    
    try:
        timeout_until = datetime.now() + duration
        await member.timeout(timeout_until, reason=f"Muted by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Muted",
            color=0xff0000,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Duration", value=time_str, inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Muted by", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to timeout this user.")
    except Exception as e:
        await ctx.send(f"Error muting user: {str(e)}")

@bot.command()
async def unmute(ctx, member: discord.Member):
    """Unmute a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.timeout(None, reason=f"Unmuted by {ctx.author.name}")
        await ctx.send(f"{member.mention} has been unmuted.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to remove timeout from this user.")
    except Exception as e:
        await ctx.send(f"Error unmuting user: {str(e)}")

@bot.command()
async def ban(ctx, member: discord.Member, time_str: str = None, *, reason="No reason provided"):
    """Ban a user (temporarily if time is specified)"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.ban(reason=f"Banned by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Banned",
            color=0x000000,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=str(member), inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Banned by", value=ctx.author.mention, inline=True)
        
        if time_str:
            duration = parse_time(time_str)
            if duration:
                embed.add_field(name="Duration", value=time_str, inline=True)
                asyncio.create_task(schedule_unban(ctx.guild, member, duration))
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to ban this user.")
    except Exception as e:
        await ctx.send(f"Error banning user: {str(e)}")

async def schedule_unban(guild, member, duration):
    """Schedule automatic unban"""
    await asyncio.sleep(duration.total_seconds())
    try:
        await guild.unban(member, reason="Temporary ban expired")
    except:
        pass

@bot.command()
async def unban(ctx, *, member_name):
    """Unban a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    banned_users = [entry async for entry in ctx.guild.bans()]
    
    for ban_entry in banned_users:
        user = ban_entry.user
        if user.name.lower() == member_name.lower() or str(user) == member_name:
            try:
                await ctx.guild.unban(user, reason=f"Unbanned by {ctx.author.name}")
                await ctx.send(f"{user} has been unbanned.")
                return
            except Exception as e:
                await ctx.send(f"Error unbanning user: {str(e)}")
                return
    
    await ctx.send(f"User '{member_name}' not found in ban list.")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    """Kick a user"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        await member.kick(reason=f"Kicked by {ctx.author.name}: {reason}")
        
        embed = discord.Embed(
            title="User Kicked",
            color=0xffa500,
            timestamp=datetime.now()
        )
        embed.add_field(name="User", value=str(member), inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Kicked by", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to kick this user.")
    except Exception as e:
        await ctx.send(f"Error kicking user: {str(e)}")

# Configuration Commands
@bot.command()
async def welcomer_enable(ctx, channel: discord.TextChannel):
    """Enable welcomer system for the server"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['welcomer_enabled'] = True
    guild_config[guild_id]['welcomer_channel'] = channel.id
    save_json('guild_config.json', guild_config)
    
    await ctx.send(f"Welcomer system has been enabled! Welcome messages will be sent to {channel.mention}.")

@bot.command()
async def automod_enable(ctx):
    """Enable automod for the server"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['automod_enabled'] = True
    save_json('guild_config.json', guild_config)
    
    await ctx.send("Automod has been enabled for this server.")

@bot.command()
async def automod_log(ctx, channel: discord.TextChannel):
    """Set the automod log channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['automod_log_channel'] = channel.id
    save_json('guild_config.json', guild_config)
    
    await ctx.send(f"Automod log channel set to {channel.mention}.")

@bot.command()
async def spam(ctx, *channels: discord.TextChannel):
    """Set channels where spam is allowed"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel_ids = ','.join(str(ch.id) for ch in channels)
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['spam_channels'] = channel_ids
    save_json('guild_config.json', guild_config)
    
    channel_mentions = ', '.join(ch.mention for ch in channels)
    await ctx.send(f"Spam is now allowed in: {channel_mentions}")

@bot.command()
async def link(ctx, *channels: discord.TextChannel):
    """Set channels where links are allowed"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel_ids = ','.join(str(ch.id) for ch in channels)
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['link_channels'] = channel_ids
    save_json('guild_config.json', guild_config)
    
    channel_mentions = ', '.join(ch.mention for ch in channels)
    await ctx.send(f"Links are now allowed in: {channel_mentions}")

# Leveling Commands
@bot.command()
async def leveling_channel(ctx, channel: discord.TextChannel):
    """Set the leveling announcement channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['leveling_channel'] = channel.id
    save_json('guild_config.json', guild_config)
    
    await ctx.send(f"Leveling announcements will be sent to {channel.mention}.")

@bot.command()
async def levelrole(ctx, action_or_role, role_or_level=None, level=None):
    """Add or remove level roles"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    level_roles = load_json('level_roles.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in level_roles:
        level_roles[guild_id] = {}
    
    if action_or_role.lower() == 'elim':
        # Remove role: !levelrole elim @role
        if not role_or_level:
            await ctx.send("Please specify a role to remove.")
            return
        
        try:
            role = await commands.RoleConverter().convert(ctx, role_or_level)
        except:
            await ctx.send("Invalid role specified.")
            return
        
        # Remove role from all levels
        for level_num in level_roles[guild_id]:
            if str(role.id) in level_roles[guild_id][level_num]:
                level_roles[guild_id][level_num].remove(str(role.id))
        
        save_json('level_roles.json', level_roles)
        await ctx.send(f"Removed {role.mention} from level rewards.")
    
    else:
        # Add role: !levelrole @role 10
        try:
            role = await commands.RoleConverter().convert(ctx, action_or_role)
            target_level = int(role_or_level) if role_or_level else 0
        except:
            await ctx.send("Usage: `!levelrole @role <level>` or `!levelrole elim @role`")
            return
        
        if str(target_level) not in level_roles[guild_id]:
            level_roles[guild_id][str(target_level)] = []
        
        if str(role.id) not in level_roles[guild_id][str(target_level)]:
            level_roles[guild_id][str(target_level)].append(str(role.id))
        
        save_json('level_roles.json', level_roles)
        await ctx.send(f"Added {role.mention} as reward for reaching level {target_level}.")

@bot.command()
async def level(ctx, member: discord.Member = None):
    """Check a user's level"""
    if member is None:
        member = ctx.author
    
    user_levels = load_json('user_levels.json')
    key = f"{ctx.guild.id}_{member.id}"
    
    if key not in user_levels:
        await ctx.send(f"{member.mention} is not in the leveling system yet.")
        return
    
    user_data = user_levels[key]
    xp = user_data.get('xp', 0)
    level = user_data.get('level', 0)
    xp_for_next = (level + 1) * 100
    xp_needed = xp_for_next - xp
    
    embed = discord.Embed(
        title=f"Level Info for {member.display_name}",
        color=0x00ff00
    )
    embed.add_field(name="Current Level", value=level, inline=True)
    embed.add_field(name="Total XP", value=xp, inline=True)
    embed.add_field(name="XP to Next Level", value=xp_needed, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command()
async def lock(ctx, *, args=None):
    """Lock a channel, optionally allowing specific roles"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel = ctx.channel
    
    try:
        # Get the @everyone role
        everyone_role = ctx.guild.default_role
        
        # Get current @everyone permissions to preserve visibility
        current_overwrite = channel.overwrites_for(everyone_role)
        
        # Only modify send_messages, keep other permissions as they are
        await channel.set_permissions(
            everyone_role, 
            send_messages=False,
            read_messages=current_overwrite.read_messages  # Preserve current visibility
        )
        
        # Check for any role mentions in the message
        mentioned_roles = ctx.message.role_mentions
        
        # If specific roles are mentioned, allow them to send messages
        if mentioned_roles:
            for role in mentioned_roles:
                role_overwrite = channel.overwrites_for(role)
                await channel.set_permissions(
                    role, 
                    send_messages=True,
                    read_messages=role_overwrite.read_messages  # Preserve current visibility
                )
            
            role_mentions = ', '.join(role.mention for role in mentioned_roles)
            await ctx.send(f"🔒 Channel locked! Only {role_mentions} can send messages.")
        else:
            await ctx.send("🔒 Channel locked for everyone!")
            
    except discord.Forbidden:
        await ctx.send("I don't have permission to modify channel permissions.")
    except Exception as e:
        await ctx.send(f"Error locking channel: {str(e)}")

@bot.command()
async def unlock(ctx):
    """Unlock a channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    channel = ctx.channel
    
    try:
        # Get all current overwrites
        current_overwrites = channel.overwrites.copy()
        
        # Only reset send_messages permission, preserve everything else
        for target, overwrite in current_overwrites.items():
            # Create new overwrite that preserves all settings except send_messages
            new_overwrite = discord.PermissionOverwrite.from_pair(
                overwrite.pair()[0], overwrite.pair()[1]
            )
            new_overwrite.send_messages = None  # Reset to default (inherit)
            
            # Only update if there are still meaningful permissions set
            if new_overwrite.is_empty():
                # If the overwrite becomes empty, remove it entirely
                await channel.set_permissions(target, overwrite=None)
            else:
                # Keep the overwrite but with send_messages reset
                await channel.set_permissions(target, overwrite=new_overwrite)
        
        await ctx.send("🔓 Channel unlocked!")
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to modify channel permissions.")
    except Exception as e:
        await ctx.send(f"Error unlocking channel: {str(e)}")

# Account linking system
class IGNModal(discord.ui.Modal, title='Link Your Account'):
    def __init__(self):
        super().__init__()
    
    ign = discord.ui.TextInput(
        label='What is your In-game-name?',
        placeholder='Enter your Stumble Guys username...',
        required=True,
        max_length=50
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        user_accounts = load_json('user_accounts.json')
        key = f"{interaction.guild.id}_{interaction.user.id}"
        
        user_accounts[key] = {
            'ign': self.ign.value,
            'linked_at': datetime.now().isoformat()
        }
        save_json('user_accounts.json', user_accounts)
        
        # Try to give verified role
        guild_config = load_json('guild_config.json')
        config = guild_config.get(str(interaction.guild.id), {})
        verified_role_id = config.get('verified_role')
        
        role_text = ""
        if verified_role_id:
            verified_role = interaction.guild.get_role(int(verified_role_id))
            if verified_role:
                try:
                    await interaction.user.add_roles(verified_role, reason="Account linked")
                    role_text = f"\n🎉 You've been given the {verified_role.mention} role!"
                except:
                    pass
        
        embed = discord.Embed(
            title="✅ Account Successfully Linked!",
            description=f"Your in-game name has been set to: **{self.ign.value}**{role_text}\n\nYou can now access all linked account features!",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AccountLinkView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🔗 Link Account', style=discord.ButtonStyle.primary)
    async def link_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IGNModal())

# Ticket system
class TicketView(discord.ui.View):
    def __init__(self, ticket_types):
        super().__init__(timeout=None)
        self.ticket_types = ticket_types
        
        # Add buttons for each ticket type (Discord allows up to 25 buttons per view)
        for i, ticket_type in enumerate(ticket_types):
            # Parse emoji and label from ticket_type
            parts = ticket_type.strip().split(' ', 1)
            emoji = None
            label = ticket_type.strip()
            
            # Check if first part is an emoji
            if len(parts) >= 2:
                potential_emoji = parts[0]
                # Check for custom emoji (including animated): <:name:id> or <a:name:id>
                if potential_emoji.startswith('<:') or potential_emoji.startswith('<a:'):
                    emoji = potential_emoji
                    label = ' '.join(parts[1:])
                # Check for unicode emoji (length 1-4 for various unicode emojis)
                elif len(potential_emoji) <= 4:
                    try:
                        # Try to use it as emoji - Discord will validate
                        emoji = potential_emoji
                        label = ' '.join(parts[1:])
                    except:
                        # If it fails, treat whole thing as label
                        emoji = None
                        label = ticket_type.strip()
            
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                emoji=emoji,
                row=i // 5  # Discord allows 5 buttons per row, multiple rows supported
            )
            button.callback = self.create_ticket_callback(label)
            self.add_item(button)
    
    def create_ticket_callback(self, ticket_type):
        async def callback(interaction: discord.Interaction):
            await self.create_ticket(interaction, ticket_type)
        return callback
    
    async def create_ticket(self, interaction: discord.Interaction, ticket_type):
        guild = interaction.guild
        user = interaction.user
        
        # Check if user already has an open ticket
        tickets = load_json('tickets.json')
        user_tickets = [t for t in tickets if t['user_id'] == user.id and t['guild_id'] == guild.id and not t.get('closed', False)]
        
        if user_tickets:
            channel = guild.get_channel(user_tickets[0]['channel_id'])
            if channel:
                await interaction.response.send_message(
                    f"You already have an open ticket: {channel.mention}",
                    ephemeral=True
                )
                return
        
        # Create ticket channel
        channel_name = f"{ticket_type.lower()}-{user.name}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Add staff roles to overwrites
        guild_config = load_json('guild_config.json')
        config = guild_config.get(str(guild.id), {})
        staff_roles = config.get('staff_roles', '')
        
        if staff_roles:
            staff_role_ids = staff_roles.split(',')
            for role_id in staff_role_ids:
                role = guild.get_role(int(role_id))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        try:
            ticket_channel = await guild.create_text_channel(
                channel_name,
                overwrites=overwrites
            )
            
            # Save ticket to database
            ticket = {
                'user_id': user.id,
                'guild_id': guild.id,
                'channel_id': ticket_channel.id,
                'ticket_type': ticket_type,
                'created_at': datetime.now().isoformat(),
                'closed': False
            }
            tickets.append(ticket)
            save_json('tickets.json', tickets)
            
            # Send welcome message in ticket
            embed = discord.Embed(
                title=f"{ticket_type} Ticket",
                description=f"Thank you for opening a ticket, {user.mention}! A staff member will be with you shortly.",
                color=0x0099ff
            )
            await ticket_channel.send(embed=embed)
            
            await interaction.response.send_message(
                f"Ticket created! {ticket_channel.mention}",
                ephemeral=True
            )
            
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to create channels.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error creating ticket: {str(e)}",
                ephemeral=True
            )

@bot.command()
async def acc(ctx):
    """Display account linking panel"""
    embed = discord.Embed(
        title="🔗 Account Linking System",
        description="**Link your Stumble Guys account to unlock exclusive features!**\n\n🎮 **Benefits of linking:**\n• Get the verified player role\n• Access to exclusive channels\n• Show off your in-game name\n• Participate in events and giveaways\n• Track your progress and stats\n\n📝 **How to link:**\n1. Click the '🔗 Link Account' button below\n2. Enter your exact Stumble Guys username\n3. Confirm your details\n4. Enjoy your new perks!\n\n✅ **Your information is safe** - We only store your in-game name for verification purposes.",
        color=0x0099ff
    )
    
    view = AccountLinkView()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def IGN(ctx, member: discord.Member = None):
    """Show user's in-game name"""
    if member is None:
        member = ctx.author
    
    user_accounts = load_json('user_accounts.json')
    key = f"{ctx.guild.id}_{member.id}"
    
    if key not in user_accounts:
        await ctx.send(f"{member.mention} hasn't linked their account yet.")
        return
    
    account_data = user_accounts[key]
    ign = account_data['ign']
    linked_at = account_data['linked_at']
    
    embed = discord.Embed(
        title=f"{member.display_name}'s Account",
        color=0x00ff00
    )
    embed.add_field(name="In-Game Name", value=ign, inline=True)
    embed.add_field(name="Linked", value=linked_at, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command()
async def ticket(ctx, *, ticket_types):
    """Create a ticket panel with multiple options"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    # Parse ticket types separated by commas
    types = [t.strip() for t in ticket_types.split(',')]
    
    if len(types) > 25:  # Discord has a limit of 25 buttons per view
        await ctx.send("You can only have up to 25 ticket types.")
        return
    
    embed = discord.Embed(
        title="🎫 Support Tickets System",
        description="**Need assistance?** Click the appropriate button below to create a support ticket!\n\n📋 **How it works:**\n• Click a button that matches your issue\n• A private channel will be created for you\n• Our staff team will assist you promptly\n• Only you and staff can see your ticket\n\n⚠️ **Please note:** You can only have one open ticket at a time.\n\n💡 **Tip:** Be as detailed as possible when describing your issue to help us assist you faster!",
        color=0x0099ff
    )
    
    view = TicketView(types)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def spu(ctx, *roles: discord.Role):
    """Set staff roles that can use ALL commands and moderation features"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You need administrator permission to use this command.")
        return
    
    if not roles:
        await ctx.send("Please mention at least one role.")
        return
    
    role_ids = ','.join(str(role.id) for role in roles)
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['staff_roles'] = role_ids
    save_json('guild_config.json', guild_config)
    
    role_mentions = ', '.join(role.mention for role in roles)
    await ctx.send(f"Staff roles updated! These roles can now use ALL bot commands: {role_mentions}")

@bot.command()
async def verified_role(ctx, role: discord.Role):
    """Set the role to give users when they link their account"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You need administrator permission to use this command.")
        return
    
    guild_config = load_json('guild_config.json')
    guild_id = str(ctx.guild.id)
    
    if guild_id not in guild_config:
        guild_config[guild_id] = {}
    
    guild_config[guild_id]['verified_role'] = role.id
    save_json('guild_config.json', guild_config)
    
    await ctx.send(f"Verified role set to {role.mention}! Users will receive this role when they link their account.")

@bot.command()
async def delete_ticket(ctx):
    """Delete the current ticket channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    # Check if current channel is a ticket
    tickets = load_json('tickets.json')
    ticket = None
    for t in tickets:
        if t['channel_id'] == ctx.channel.id and not t.get('closed', False):
            ticket = t
            break
    
    if not ticket:
        await ctx.send("This is not a ticket channel.")
        return
    
    # Mark ticket as closed
    ticket['closed'] = True
    ticket['closed_at'] = datetime.now().isoformat()
    save_json('tickets.json', tickets)
    
    await ctx.send("This ticket will be deleted in 5 seconds...")
    await asyncio.sleep(5)
    
    try:
        await ctx.channel.delete(reason=f"Ticket closed by {ctx.author.name}")
    except:
        pass

@bot.command()
async def embed(ctx, *, text):
    """Create an embed with the specified text"""
    embed = discord.Embed(
        description=text,
        color=0x0099ff
    )
    await ctx.send(embed=embed)

@bot.command()
async def delete(ctx, number: int):
    """Delete specified number of messages from the channel"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    if number < 1 or number > 100:
        await ctx.send("Number must be between 1 and 100.")
        return
    
    try:
        deleted = await ctx.channel.purge(limit=number + 1)  # +1 to include the command message
        await ctx.send(f"Deleted {len(deleted) - 1} messages.", delete_after=5)
    except discord.Forbidden:
        await ctx.send("I don't have permission to delete messages in this channel.")
    except Exception as e:
        await ctx.send(f"Error deleting messages: {str(e)}")

class RegionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='EU', emoji='🇪🇺', style=discord.ButtonStyle.primary)
    async def eu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_region_selection(interaction, 'EU')
    
    @discord.ui.button(label='NA/US', emoji='🇺🇸', style=discord.ButtonStyle.primary)
    async def us_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_region_selection(interaction, 'US')
    
    @discord.ui.button(label='ASIA', emoji='🌏', style=discord.ButtonStyle.primary)
    async def asia_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_region_selection(interaction, 'ASIA')
    
    @discord.ui.button(label='INW', emoji='🏃', style=discord.ButtonStyle.primary)
    async def inw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_region_selection(interaction, 'INW')
    
    async def handle_region_selection(self, interaction: discord.Interaction, region):
        guild = interaction.guild
        member = interaction.user
        
        region_roles = ['EU', 'US', 'ASIA', 'INW']
        
        # Remove all other region roles
        for role_name in region_roles:
            role = discord.utils.get(guild.roles, name=role_name)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason=f"Region changed to {region}")
                except:
                    pass
        
        # Add the new region role
        new_role = discord.utils.get(guild.roles, name=region)
        if not new_role:
            # Create the role if it doesn't exist
            try:
                new_role = await guild.create_role(name=region, reason="Region role for Stumble Guys")
            except:
                await interaction.response.send_message(
                    f"Failed to create {region} role. Please contact an administrator.",
                    ephemeral=True
                )
                return
        
        try:
            await member.add_roles(new_role, reason=f"Selected {region} region")
            await interaction.response.send_message(
                f"🎮 **Region Updated!** You've been assigned the **{region}** role for Stumble Guys! Get ready to stumble with players from your region! 🏃‍♂️💨",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to assign roles.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error assigning role: {str(e)}",
                ephemeral=True
            )

@bot.command()
async def server_panel(ctx):
    """Create a server region selection panel for Stumble Guys"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    embed = discord.Embed(
        title="🌍 Stumble Guys Region Selection",
        description="**Select your preferred region for Stumble Guys!** 🎮\n\n🏃‍♂️ **Choose your region to:**\n• Get matched with the right role\n• Connect with regional players\n• Join region-specific events\n• Get the best gameplay experience\n\n📍 **Available Regions:**\n🇪🇺 **EU** - Europe\n🇺🇸 **NA/US** - North America\n🌏 **ASIA** - Asia Pacific\n🏃 **INW** - India & West Asia\n\n⚠️ **Note:** You can only have one region role at a time. Selecting a new region will remove your previous one!",
        color=0xff6b35
    )
    embed.set_footer(text="🎯 Choose wisely and start stumbling!")
    
    view = RegionView()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def role_add(ctx, *, role_name):
    """Create a new role in the server"""
    if not await is_staff(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    try:
        new_role = await ctx.guild.create_role(name=role_name, reason=f"Role created by {ctx.author.name}")
        await ctx.send(f"Successfully created role: {new_role.mention}")
    except discord.Forbidden:
        await ctx.send("I don't have permission to create roles.")
    except Exception as e:
        await ctx.send(f"Error creating role: {str(e)}")

@bot.command()
async def commands(ctx):
    """Show all available commands for staff and owners"""
    if not await is_staff(ctx) and not ctx.author.guild_permissions.administrator:
        await ctx.send("You don't have permission to view the command list.")
        return
    
    embed = discord.Embed(
        title="🔧 Bot Commands",
        description="Complete list of available commands",
        color=0x0099ff
    )
    
    # Moderation Commands
    moderation_cmds = [
        "`!warn @user [reason]` - Issue warning to user",
        "`!warn_hs @user` - View user's warning history", 
        "`!warn_rmv @user <number>` - Remove number of warnings",
        "`!mute @user <time> [reason]` - Mute user (1m-7d)",
        "`!unmute @user` - Remove mute from user",
        "`!ban @user [time] [reason]` - Ban user (temp if time given)",
        "`!unban <username>` - Unban user",
        "`!kick @user [reason]` - Kick user from server",
        "`!delete_ticket` - Delete current ticket channel",
        "`!delete <number>` - Delete number of messages (1-100)"
    ]
    
    # Automod Commands
    automod_cmds = [
        "`!automod_enable` - Enable automatic moderation",
        "`!automod_log #channel` - Set automod log channel"
    ]
    
    # Channel Management
    channel_cmds = [
        "`!spam #channel...` - Set spam-allowed channels",
        "`!link #channel...` - Set link-allowed channels", 
        "`!lock [@role...]` - Lock channel (allow roles if given)",
        "`!unlock` - Unlock channel"
    ]
    
    # Leveling System
    leveling_cmds = [
        "`!leveling_channel #channel` - Set level announcement channel",
        "`!levelrole @role <level>` - Add role reward for level",
        "`!levelrole elim @role` - Remove role from rewards",
        "`!level [@user]` - Check user's level and XP"
    ]
    
    # Account & Tickets
    account_cmds = [
        "`!acc` - Show account linking panel",
        "`!IGN [@user]` - Show user's in-game name",
        "`!ticket types,with,emojis` - Create ticket panel",
        "`!welcomer_enable #channel` - Enable welcomer system",
        "`!server_panel` - Create region selection panel"
    ]
    
    # Utility Commands
    utility_cmds = [
        "`!embed <text>` - Create an embed with text",
        "`!role_add <rolename>` - Create a new role"
    ]
    
    # Admin Only
    admin_cmds = [
        "`!spu @role...` - Set staff roles (Admin only)",
        "`!verified_role @role` - Set role for account linking",
        "`!commands` - Show this command list"
    ]
    
    embed.add_field(name="⚖️ Moderation", value="\n".join(moderation_cmds), inline=False)
    embed.add_field(name="🤖 Automod", value="\n".join(automod_cmds), inline=False)
    embed.add_field(name="🔒 Channel Management", value="\n".join(channel_cmds), inline=False)
    embed.add_field(name="📈 Leveling System", value="\n".join(leveling_cmds), inline=False)
    embed.add_field(name="🎫 Accounts & Tickets", value="\n".join(account_cmds), inline=False)
    embed.add_field(name="🛠️ Utility", value="\n".join(utility_cmds), inline=False)
    
    if ctx.author.guild_permissions.administrator:
        embed.add_field(name="👑 Administrator Only", value="\n".join(admin_cmds), inline=False)
    
    embed.set_footer(text="All commands require staff permissions unless noted otherwise")
    
    await ctx.send(embed=embed)

# Background task to check level roles
@tasks.loop(minutes=5)
async def level_check():
    """Periodically check and assign level roles"""
    user_levels = load_json('user_levels.json')
    level_roles = load_json('level_roles.json')
    
    for key, user_data in user_levels.items():
        guild_id, user_id = key.split('_')
        user_level = user_data.get('level', 0)
        
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        
        member = guild.get_member(int(user_id))
        if not member:
            continue
        
        # Check if user should have any level roles
        guild_roles = level_roles.get(guild_id, {})
        for level_num, role_ids in guild_roles.items():
            if user_level >= int(level_num):
                for role_id in role_ids:
                    role = guild.get_role(int(role_id))
                    if role and role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Level role assignment")
                        except:
                            pass

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send("User not found.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing required argument: {error.param}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument provided.")
    else:
        print(f"Unhandled error: {error}")

# Run the bot
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        print("Please set the TOKEN environment variable")
    else:
        bot.run(TOKEN)
