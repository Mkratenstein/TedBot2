import os
import asyncio
import logging
from datetime import datetime, timedelta
import sys
from typing import Dict, Optional, List, Any
from functools import lru_cache
import time
import random as random_module
import json

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, max_requests: int, time_window: int):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: List[float] = []

    async def acquire(self) -> None:
        now = time.time()
        # Remove old requests
        self.requests = [req_time for req_time in self.requests if now - req_time < self.time_window]
        
        if len(self.requests) >= self.max_requests:
            # Wait until we can make another request
            sleep_time = self.requests[0] + self.time_window - now
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        self.requests.append(now)

class AsyncCache:
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self.cache: Dict[str, Any] = {}
        self.times: Dict[str, float] = {}

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            return self.cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        if len(self.cache) >= self.maxsize:
            # Remove oldest item
            oldest_key = min(self.times.items(), key=lambda x: x[1])[0]
            del self.cache[oldest_key]
            del self.times[oldest_key]
        
        self.cache[key] = value
        self.times[key] = time.time()

    def clear(self) -> None:
        self.cache.clear()
        self.times.clear()

class GooseBandTracker(commands.Bot):
    def __init__(self, intents: discord.Intents):
        super().__init__(command_prefix='!', intents=intents)
        
        # Validate required environment variables
        self._validate_env_vars()
        
        # YouTube API setup with rate limiting
        self.youtube = build('youtube', 'v3', developerKey=os.getenv('YOUTUBE_API_KEY'))
        self.rate_limiter = RateLimiter(max_requests=100, time_window=60)  # 100 requests per minute
        
        # Initialize tracking variables
        self._init_tracking_vars()
        
        # Initialize caches
        self.playlist_cache = AsyncCache(maxsize=1)
        
        # Register commands
        self._register_commands()

    async def setup_hook(self) -> None:
        """Set up the bot's slash commands"""
        # Sync commands with Discord
        await self.tree.sync()

    def _validate_env_vars(self) -> None:
        """Validate required environment variables"""
        required_vars = [
            'YOUTUBE_API_KEY',
            'DISCORD_TOKEN',
            'YOUTUBE_CHANNEL_ID',
            'DISCORD_CHANNEL_ID',
            'DISCORD_RANDOM_CHANNEL_ID'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # Validate YouTube channel ID format
        self.youtube_channel_id = os.getenv('YOUTUBE_CHANNEL_ID')
        if not self.youtube_channel_id.startswith('UC'):
            logger.warning(f"Warning: YouTube channel ID '{self.youtube_channel_id}' may be invalid. Channel IDs should start with 'UC'")
        
        # Set Discord channel IDs
        self.discord_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))  # For notifications
        self.discord_random_channel_id = int(os.getenv('DISCORD_RANDOM_CHANNEL_ID'))  # For random command

    def _init_tracking_vars(self) -> None:
        """Initialize tracking variables"""
        # Create data directory if it doesn't exist
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        self.tracking_file = os.path.join(self.data_dir, 'tracking_vars.json')
        
        logger.info(f"Using tracking file: {self.tracking_file}")
        
        try:
            # Try to load tracking variables from file
            if os.path.exists(self.tracking_file):
                with open(self.tracking_file, 'r') as f:
                    data = json.load(f)
                    self.last_livestream = data.get('last_livestream')
                    self.last_video = data.get('last_video')
                    self.last_short = data.get('last_short')
                    self.last_check_time = datetime.fromisoformat(data['last_check_time']) if data.get('last_check_time') else None
                    logger.info("Loaded tracking variables from file")
            else:
                self.last_livestream = None
                self.last_video = None
                self.last_short = None
                self.last_check_time = None
                logger.info("No tracking variables file found, starting fresh")
        except Exception as e:
            logger.error(f"Error loading tracking variables: {e}")
            self.last_livestream = None
            self.last_video = None
            self.last_short = None
            self.last_check_time = None
        
        self.active_tasks: set = set()
        self.consecutive_errors: int = 0
        self.max_consecutive_errors: int = 3

    def _save_tracking_vars(self) -> None:
        """Save tracking variables to file"""
        try:
            data = {
                'last_livestream': self.last_livestream,
                'last_video': self.last_video,
                'last_short': self.last_short,
                'last_check_time': self.last_check_time.isoformat() if self.last_check_time else None
            }
            with open(self.tracking_file, 'w') as f:
                json.dump(data, f)
            logger.info(f"Saved tracking variables to: {self.tracking_file}")
        except Exception as e:
            logger.error(f"Error saving tracking variables: {e}")
            logger.error(f"Attempted to save to: {self.tracking_file}")

    def _register_commands(self) -> None:
        """Register bot commands"""
        @self.command()
        async def ping(ctx: commands.Context) -> None:
            await ctx.send('Pong! Goose Youtube Tracker is alive!')
            
        @self.tree.command(name="randomyoutube", description="Get a random video from the channel")
        async def random_youtube(interaction: discord.Interaction) -> None:
            """Get a random video from the channel"""
            try:
                # Check if command is used in the correct channel
                if interaction.channel_id != self.discord_random_channel_id:
                    await interaction.response.send_message(f"This command can only be used in <#{self.discord_random_channel_id}>", ephemeral=True)
                    return

                # Defer the response since this might take a while
                await interaction.response.defer()
                
                # Get channel uploads playlist ID (cached)
                uploads_playlist_id = await self.get_uploads_playlist_id()
                
                # Get videos with rate limiting
                await self.rate_limiter.acquire()
                playlist_response = self.youtube.playlistItems().list(
                    part='snippet',
                    playlistId=uploads_playlist_id,
                    maxResults=100  # Get up to 100 videos for better randomization
                ).execute()
                
                if not playlist_response.get('items'):
                    logger.warning("No videos found in uploads playlist")
                    await interaction.followup.send("No videos found in the channel.")
                    return
                
                # Filter out the excluded video
                excluded_video_id = "QqnjgnHFH70"
                items = [item for item in playlist_response['items'] 
                        if item['snippet']['resourceId']['videoId'] != excluded_video_id]
                
                if not items:
                    logger.warning("No videos found after filtering excluded video")
                    await interaction.followup.send("No videos found in the channel.")
                    return
                
                # Select a random video from the filtered pool
                random_index = random_module.randint(0, len(items) - 1)
                random_item = items[random_index]
                video_id = random_item['snippet']['resourceId']['videoId']
                published_at = datetime.fromisoformat(random_item['snippet']['publishedAt'].replace('Z', '+00:00'))
                
                # Get additional video details
                await self.rate_limiter.acquire()
                video_response = self.youtube.videos().list(
                    part='snippet,liveStreamingDetails,statistics',
                    id=video_id
                ).execute()
                
                if not video_response.get('items'):
                    logger.error(f"No video details found for video ID: {video_id}")
                    await interaction.followup.send("Could not fetch video details. The video might be private or deleted.")
                    return
                
                video = video_response['items'][0]
                title = video['snippet']['title']
                is_livestream = video.get('snippet', {}).get('liveBroadcastContent') == 'live'
                view_count = video.get('statistics', {}).get('viewCount', '0')
                like_count = video.get('statistics', {}).get('likeCount', '0')
                
                # Create embed message
                video_embed = discord.Embed(
                    title=title,
                    description=f"https://www.youtube.com/watch?v={video_id}",
                    color=discord.Color.red() if is_livestream else discord.Color.blue(),
                    timestamp=published_at
                )
                
                # Add video thumbnail
                video_embed.set_thumbnail(url=video['snippet']['thumbnails']['high']['url'])
                
                # Add video stats
                video_embed.add_field(name="Views", value=view_count, inline=True)
                video_embed.add_field(name="Likes", value=like_count, inline=True)
                
                # Add video type indicator
                video_type = "🔴 LIVE" if is_livestream else "🎥 Video"
                video_embed.add_field(name="Type", value=video_type, inline=True)
                
                # Add publish date
                video_embed.set_footer(text=f"Published on {published_at.strftime('%Y-%m-%d %H:%M:%S')}")
                
                await interaction.followup.send(embed=video_embed)
                
            except HttpError as e:
                error_message = f"YouTube API error: {e.resp.status} - {e.content}"
                logger.error(error_message)
                await interaction.followup.send(f"An error occurred while accessing YouTube API: {e.resp.status}")
            except ValueError as e:
                error_message = f"Invalid data received: {str(e)}"
                logger.error(error_message)
                await interaction.followup.send("Received invalid data from YouTube. Please try again later.")
            except Exception as e:
                error_type = type(e).__name__
                error_message = f"Unexpected error in random command: {error_type} - {str(e)}"
                logger.error(error_message)
                await interaction.followup.send(f"An unexpected error occurred: {error_type}. Please check the bot logs for details.")
            
        @self.command()
        async def status(ctx: commands.Context) -> None:
            """Check the status of the bot and its services"""
            status_message = "🟢 Bot Status:\n"
            status_message += f"- Discord: Connected as {self.user.name}\n"
            status_message += f"- YouTube: {'Connected' if self.youtube else 'Disconnected'}\n"
            status_message += f"- YouTube Channel ID: {self.youtube_channel_id}\n"
            status_message += f"- Last Check: {self.last_check_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_check_time else 'Never'}\n"
            status_message += f"- Consecutive Errors: {self.consecutive_errors}"
            await ctx.send(status_message)

    async def get_uploads_playlist_id(self) -> str:
        """Cache the uploads playlist ID to reduce API calls"""
        # Check cache first
        cached_id = self.playlist_cache.get('uploads_id')
        if cached_id:
            return cached_id

        await self.rate_limiter.acquire()
        channel_response = self.youtube.channels().list(
            part='contentDetails',
            id=self.youtube_channel_id
        ).execute()
        
        if not channel_response.get('items'):
            raise ValueError(f"Could not find YouTube channel with ID: {self.youtube_channel_id}")
        
        playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        self.playlist_cache.set('uploads_id', playlist_id)
        return playlist_id

    async def handle_api_error(self, error: Exception) -> bool:
        """Handle API errors and implement backoff strategy"""
        if isinstance(error, HttpError):
            if error.resp.status in [429, 500, 503]:  # Rate limit or server errors
                self.consecutive_errors += 1
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.error("Too many consecutive errors, stopping YouTube checks")
                    self.check_youtube_updates.stop()
                    return False
                # Exponential backoff
                await asyncio.sleep(2 ** self.consecutive_errors)
            else:
                logger.error(f"YouTube API error: {error}")
        else:
            logger.error(f"Unexpected error: {error}")
        return True

    async def on_ready(self) -> None:
        """Called when the bot is ready and connected to Discord"""
        logger.info(f'Logged in as {self.user.name}')
        
        # Start background tasks
        self.check_youtube_updates.start()
        
        # Add tasks to active tasks set
        self.active_tasks.add(self.check_youtube_updates)

    async def close(self) -> None:
        """Gracefully shut down the bot and cancel all tasks"""
        logger.info("Shutting down bot...")
        
        # Save tracking variables before shutting down
        self._save_tracking_vars()
        
        # Cancel all active tasks
        for task in self.active_tasks:
            if task.is_running():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Call parent class close method
        await super().close()
        logger.info("Bot shutdown complete")

    def cog_unload(self) -> None:
        """Cancel all tasks when cog is unloaded"""
        for task in self.active_tasks:
            if task.is_running():
                task.cancel()

    @tasks.loop(minutes=15)
    async def check_youtube_updates(self) -> None:
        """Check for new YouTube content with improved error handling and caching"""
        try:
            # Reset error counter on successful check
            self.consecutive_errors = 0
            
            # Get channel uploads playlist ID (cached)
            uploads_playlist_id = await self.get_uploads_playlist_id()
            
            # Get recent videos with rate limiting
            await self.rate_limiter.acquire()
            playlist_response = self.youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=5
            ).execute()
            
            if not playlist_response.get('items'):
                logger.warning("No videos found in uploads playlist")
                return
                
            # Process videos
            for item in playlist_response['items']:
                try:
                    video_id = item['snippet']['resourceId']['videoId']
                    published_at = datetime.fromisoformat(item['snippet']['publishedAt'].replace('Z', '+00:00'))
                    
                    logger.info(f"Processing video: {video_id} published at {published_at}")
                    
                    # Skip if video is too old
                    if published_at < datetime.now(published_at.tzinfo) - timedelta(hours=24):
                        logger.info(f"Skipping video {video_id} - too old")
                        continue
                        
                    # Get video details with rate limiting
                    await self.rate_limiter.acquire()
                    video_response = self.youtube.videos().list(
                        part='snippet,liveStreamingDetails',
                        id=video_id
                    ).execute()
                    
                    if not video_response.get('items'):
                        logger.warning(f"No video details found for video ID: {video_id}")
                        continue
                        
                    video = video_response['items'][0]
                    is_livestream = video.get('snippet', {}).get('liveBroadcastContent') == 'live'
                    is_short = video.get('snippet', {}).get('title', '').lower().startswith('#shorts')
                    
                    logger.info(f"Video {video_id} - Livestream: {is_livestream}, Short: {is_short}")
                    logger.info(f"Last video ID: {self.last_video}, Last short ID: {self.last_short}, Last livestream ID: {self.last_livestream}")
                    
                    channel = self.get_channel(self.discord_channel_id)
                    
                    if not channel:
                        logger.error(f"Could not find Discord channel with ID: {self.discord_channel_id}")
                        return
                        
                    # Log channel permissions
                    bot_member = channel.guild.get_member(self.user.id)
                    if bot_member:
                        logger.info(f"Bot permissions in channel {channel.name}:")
                        logger.info(f"- Send Messages: {channel.permissions_for(bot_member).send_messages}")
                        logger.info(f"- Embed Links: {channel.permissions_for(bot_member).embed_links}")
                        logger.info(f"- Read Messages: {channel.permissions_for(bot_member).read_messages}")
                    else:
                        logger.error(f"Could not find bot member in guild {channel.guild.name}")
                    
                    # Send notifications for new content
                    if is_livestream and video_id != self.last_livestream:
                        logger.info(f"Sending livestream notification for video {video_id}")
                        try:
                            logger.info(f"Attempting to send message to channel {channel.id} in guild {channel.guild.id}")
                            message = await channel.send(f"🔴 Goose is LIVE on YouTube!\nhttps://www.youtube.com/watch?v={video_id}")
                            logger.info(f"Successfully sent message with ID: {message.id}")
                            self.last_livestream = video_id
                            self._save_tracking_vars()  # Save after successful notification
                        except discord.Forbidden as e:
                            logger.error(f"Forbidden error sending livestream notification: {e}")
                            logger.error(f"Channel ID: {channel.id}, Guild ID: {channel.guild.id}")
                            logger.error(f"Bot ID: {self.user.id}")
                            logger.error(f"HTTP Status: {e.status}")
                            logger.error(f"Error Code: {e.code}")
                        except discord.HTTPException as e:
                            logger.error(f"HTTP error sending livestream notification: {e}")
                            logger.error(f"Status: {e.status}")
                            logger.error(f"Response: {e.response}")
                        except Exception as e:
                            logger.error(f"Error sending livestream notification: {str(e)}")
                            logger.error(f"Error type: {type(e).__name__}")
                    elif is_short and video_id != self.last_short:
                        logger.info(f"Sending short notification for video {video_id}")
                        try:
                            logger.info(f"Attempting to send message to channel {channel.id} in guild {channel.guild.id}")
                            message = await channel.send(f"🎥 New YouTube Short!\nhttps://www.youtube.com/watch?v={video_id}")
                            logger.info(f"Successfully sent message with ID: {message.id}")
                            self.last_short = video_id
                            self._save_tracking_vars()  # Save after successful notification
                        except discord.Forbidden as e:
                            logger.error(f"Forbidden error sending short notification: {e}")
                            logger.error(f"Channel ID: {channel.id}, Guild ID: {channel.guild.id}")
                            logger.error(f"Bot ID: {self.user.id}")
                            logger.error(f"HTTP Status: {e.status}")
                            logger.error(f"Error Code: {e.code}")
                        except discord.HTTPException as e:
                            logger.error(f"HTTP error sending short notification: {e}")
                            logger.error(f"Status: {e.status}")
                            logger.error(f"Response: {e.response}")
                        except Exception as e:
                            logger.error(f"Error sending short notification: {str(e)}")
                            logger.error(f"Error type: {type(e).__name__}")
                    elif not is_livestream and not is_short and video_id != self.last_video:
                        logger.info(f"Sending video notification for video {video_id}")
                        try:
                            logger.info(f"Attempting to send message to channel {channel.id} in guild {channel.guild.id}")
                            message = await channel.send(f"🎥 New YouTube Video!\nhttps://www.youtube.com/watch?v={video_id}")
                            logger.info(f"Successfully sent message with ID: {message.id}")
                            self.last_video = video_id
                            self._save_tracking_vars()  # Save after successful notification
                        except discord.Forbidden as e:
                            logger.error(f"Forbidden error sending video notification: {e}")
                            logger.error(f"Channel ID: {channel.id}, Guild ID: {channel.guild.id}")
                            logger.error(f"Bot ID: {self.user.id}")
                            logger.error(f"HTTP Status: {e.status}")
                            logger.error(f"Error Code: {e.code}")
                        except discord.HTTPException as e:
                            logger.error(f"HTTP error sending video notification: {e}")
                            logger.error(f"Status: {e.status}")
                            logger.error(f"Response: {e.response}")
                        except Exception as e:
                            logger.error(f"Error sending video notification: {str(e)}")
                            logger.error(f"Error type: {type(e).__name__}")
                    else:
                        logger.info(f"No notification sent for video {video_id} - already processed")
                        
                    break  # Only notify for the most recent video
                    
                except Exception as e:
                    logger.error(f"Error processing video: {str(e)}")
                    if not await self.handle_api_error(e):
                        return
                    continue
                    
            # Update last check time
            self.last_check_time = datetime.now()
            
        except Exception as e:
            logger.error(f"Error in check_youtube_updates: {str(e)}")
            if not await self.handle_api_error(e):
                return

    @check_youtube_updates.before_loop
    async def before_check_youtube_updates(self) -> None:
        """Wait for bot to be ready before starting YouTube check loop"""
        await self.wait_until_ready()

def main() -> None:
    try:
        intents = discord.Intents.default()
        intents.message_content = True
        
        bot = GooseBandTracker(intents)
        
        # Run the bot with error handling
        bot.run(os.getenv('DISCORD_TOKEN'))
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()