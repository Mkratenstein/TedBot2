import os
import asyncio
import logging
from datetime import datetime, timedelta
import sys
from typing import Dict, Optional
from functools import lru_cache
import time

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, max_requests: int, time_window: int):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    async def acquire(self):
        now = time.time()
        # Remove old requests
        self.requests = [req_time for req_time in self.requests if now - req_time < self.time_window]
        
        if len(self.requests) >= self.max_requests:
            # Wait until we can make another request
            sleep_time = self.requests[0] + self.time_window - now
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        self.requests.append(now)

class GooseBandTracker(commands.Bot):
    def __init__(self, intents):
        super().__init__(command_prefix='!', intents=intents)
        
        # Validate required environment variables
        required_vars = [
            'YOUTUBE_API_KEY',
            'DISCORD_TOKEN',
            'YOUTUBE_CHANNEL_ID',
            'DISCORD_CHANNEL_ID'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # YouTube API setup with rate limiting
        self.youtube = build('youtube', 'v3', developerKey=os.getenv('YOUTUBE_API_KEY'))
        self.rate_limiter = RateLimiter(max_requests=100, time_window=60)  # 100 requests per minute
        
        # Validate YouTube channel ID format
        self.youtube_channel_id = os.getenv('YOUTUBE_CHANNEL_ID')
        if not self.youtube_channel_id.startswith('UC'):
            logger.warning(f"Warning: YouTube channel ID '{self.youtube_channel_id}' may be invalid. Channel IDs should start with 'UC'")
        
        # Tracking variables with type hints
        self.last_livestream: Optional[str] = None
        self.last_video: Optional[str] = None
        self.last_short: Optional[str] = None
        self.last_check_time: Optional[datetime] = None
        
        # Channel IDs
        self.discord_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))
        
        # Task tracking
        self.active_tasks = set()
        
        # Error tracking
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3
        
        # Register commands
        @self.command()
        async def ping(ctx):
            await ctx.send('Pong! Goose Youtube Tracker is alive!')
            
        @self.command()
        async def latest(ctx):
            """Get the latest video from the channel"""
            try:
                # Get channel uploads playlist ID (cached)
                uploads_playlist_id = await self.get_uploads_playlist_id()
                
                # Get most recent video with rate limiting
                await self.rate_limiter.acquire()
                playlist_response = self.youtube.playlistItems().list(
                    part='snippet',
                    playlistId=uploads_playlist_id,
                    maxResults=1
                ).execute()
                
                if not playlist_response.get('items'):
                    await ctx.send("No videos found in the channel.")
                    return
                
                # Get video details
                video_id = playlist_response['items'][0]['snippet']['resourceId']['videoId']
                published_at = datetime.fromisoformat(playlist_response['items'][0]['snippet']['publishedAt'].replace('Z', '+00:00'))
                
                # Get additional video details
                await self.rate_limiter.acquire()
                video_response = self.youtube.videos().list(
                    part='snippet,liveStreamingDetails,statistics',
                    id=video_id
                ).execute()
                
                if not video_response.get('items'):
                    await ctx.send("Could not fetch video details.")
                    return
                
                video = video_response['items'][0]
                title = video['snippet']['title']
                description = video['snippet']['description']
                is_livestream = video.get('snippet', {}).get('liveBroadcastContent') == 'live'
                view_count = video.get('statistics', {}).get('viewCount', '0')
                like_count = video.get('statistics', {}).get('likeCount', '0')
                
                # Create embed message
                embed = discord.Embed(
                    title=title,
                    description=f"https://www.youtube.com/watch?v={video_id}",
                    color=discord.Color.red() if is_livestream else discord.Color.blue(),
                    timestamp=published_at
                )
                
                # Add video thumbnail
                embed.set_thumbnail(url=video['snippet']['thumbnails']['high']['url'])
                
                # Add video stats
                embed.add_field(name="Views", value=view_count, inline=True)
                embed.add_field(name="Likes", value=like_count, inline=True)
                
                # Add video type indicator
                video_type = "🔴 LIVE" if is_livestream else "🎥 Video"
                embed.add_field(name="Type", value=video_type, inline=True)
                
                # Add publish date
                embed.set_footer(text=f"Published on {published_at.strftime('%Y-%m-%d %H:%M:%S')}")
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                logger.error(f"Error fetching latest video: {e}")
                await ctx.send("An error occurred while fetching the latest video.")
            
        @self.command()
        async def status(ctx):
            """Check the status of the bot and its services"""
            status_message = "🟢 Bot Status:\n"
            status_message += f"- Discord: Connected as {self.user.name}\n"
            status_message += f"- YouTube: {'Connected' if self.youtube else 'Disconnected'}\n"
            status_message += f"- YouTube Channel ID: {self.youtube_channel_id}\n"
            status_message += f"- Last Check: {self.last_check_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_check_time else 'Never'}\n"
            status_message += f"- Consecutive Errors: {self.consecutive_errors}"
            await ctx.send(status_message)

    @lru_cache(maxsize=1)
    async def get_uploads_playlist_id(self) -> str:
        """Cache the uploads playlist ID to reduce API calls"""
        await self.rate_limiter.acquire()
        channel_response = self.youtube.channels().list(
            part='contentDetails',
            id=self.youtube_channel_id
        ).execute()
        
        if not channel_response.get('items'):
            raise ValueError(f"Could not find YouTube channel with ID: {self.youtube_channel_id}")
            
        return channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

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

    async def on_ready(self):
        logger.info(f'Logged in as {self.user.name}')
        
        # Start background tasks
        self.check_youtube_updates.start()
        
        # Add tasks to active tasks set
        self.active_tasks.add(self.check_youtube_updates)

    async def close(self):
        """Gracefully shut down the bot and cancel all tasks"""
        logger.info("Shutting down bot...")
        
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

    def cog_unload(self):
        """Cancel all tasks when cog is unloaded"""
        for task in self.active_tasks:
            if task.is_running():
                task.cancel()

    @tasks.loop(minutes=15)
    async def check_youtube_updates(self):
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
                    
                    # Skip if video is too old
                    if published_at < datetime.now(published_at.tzinfo) - timedelta(hours=24):
                        continue
                        
                    # Get video details with rate limiting
                    await self.rate_limiter.acquire()
                    video_response = self.youtube.videos().list(
                        part='snippet,liveStreamingDetails',
                        id=video_id
                    ).execute()
                    
                    if not video_response.get('items'):
                        continue
                        
                    video = video_response['items'][0]
                    is_livestream = video.get('snippet', {}).get('liveBroadcastContent') == 'live'
                    is_short = video.get('snippet', {}).get('title', '').lower().startswith('#shorts')
                    
                    channel = self.get_channel(self.discord_channel_id)
                    
                    # Send notifications for new content
                    if is_livestream and video_id != self.last_livestream:
                        await channel.send(f"🔴 Goose is LIVE on YouTube!\nhttps://www.youtube.com/watch?v={video_id}")
                        self.last_livestream = video_id
                    elif is_short and video_id != self.last_short:
                        await channel.send(f"🎥 New YouTube Short!\nhttps://www.youtube.com/watch?v={video_id}")
                        self.last_short = video_id
                    elif not is_livestream and not is_short and video_id != self.last_video:
                        await channel.send(f"🎥 New YouTube Video!\nhttps://www.youtube.com/watch?v={video_id}")
                        self.last_video = video_id
                        
                    break  # Only notify for the most recent video
                    
                except Exception as e:
                    if not await self.handle_api_error(e):
                        return
                    continue
                    
            # Update last check time
            self.last_check_time = datetime.now()
            
        except Exception as e:
            if not await self.handle_api_error(e):
                return

    @check_youtube_updates.before_loop
    async def before_check_youtube_updates(self):
        """Wait for bot to be ready before starting YouTube check loop"""
        await self.wait_until_ready()

def main():
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