import os
import asyncio
import logging
from datetime import datetime, timedelta
import sys
from typing import Dict, Optional
from functools import lru_cache
import time
import random

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

class AsyncCache:
    def __init__(self, maxsize=128):
        self.maxsize = maxsize
        self.cache = {}
        self.times = {}

    def get(self, key):
        if key in self.cache:
            return self.cache[key]
        return None

    def set(self, key, value):
        if len(self.cache) >= self.maxsize:
            # Remove oldest item
            oldest_key = min(self.times.items(), key=lambda x: x[1])[0]
            del self.cache[oldest_key]
            del self.times[oldest_key]
        
        self.cache[key] = value
        self.times[key] = time.time()

    def clear(self):
        self.cache.clear()
        self.times.clear()

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
        async def random(ctx):
            """Get a random video from the channel"""
            try:
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
                    await ctx.send("No videos found in the channel.")
                    return
                
                # Select a random video from the larger pool
                random_item = random.choice(playlist_response['items'])
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
                    await ctx.send("Could not fetch video details. The video might be private or deleted.")
                    return
                
                video = video_response['items'][0]
                title = video['snippet']['title']
                is_livestream = video.get('snippet', {}).get('liveBroadcastContent') == 'live'
                view_count = video.get('statistics', {}).get('viewCount', '0')
                like_count = video.get('statistics', {}).get('likeCount', '0')
                
                # Create embed message
                embed = discord.Embed(
                    title="🎲 Random Video",
                    description=f"Here's a random video from the channel (selected from {len(playlist_response['items'])} videos):",
                    color=discord.Color.green()
                )
                
                # Add video details
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
                
                await ctx.send(embed=video_embed)
                
            except HttpError as e:
                error_message = f"YouTube API error: {e.resp.status} - {e.content}"
                logger.error(error_message)
                await ctx.send(f"An error occurred while accessing YouTube API: {e.resp.status}")
            except ValueError as e:
                error_message = f"Invalid data received: {str(e)}"
                logger.error(error_message)
                await ctx.send("Received invalid data from YouTube. Please try again later.")
            except Exception as e:
                error_message = f"Unexpected error in random command: {str(e)}"
                logger.error(error_message)
                await ctx.send("An unexpected error occurred. Please check the bot logs for details.")
            
        @self.command()
        async def latest(ctx):
            """Get the latest 5 videos from the channel"""
            try:
                # Get channel uploads playlist ID (cached)
                uploads_playlist_id = await self.get_uploads_playlist_id()
                
                # Get most recent videos with rate limiting
                await self.rate_limiter.acquire()
                playlist_response = self.youtube.playlistItems().list(
                    part='snippet',
                    playlistId=uploads_playlist_id,
                    maxResults=50  # Get more videos to ensure we have enough after filtering
                ).execute()
                
                if not playlist_response.get('items'):
                    logger.warning("No videos found in uploads playlist")
                    await ctx.send("No videos found in the channel.")
                    return
                
                # Sort videos by publication date (newest first)
                videos = []
                for item in playlist_response['items']:
                    try:
                        video_id = item['snippet']['resourceId']['videoId']
                        published_at = datetime.fromisoformat(item['snippet']['publishedAt'].replace('Z', '+00:00'))
                        
                        # Get additional video details
                        await self.rate_limiter.acquire()
                        video_response = self.youtube.videos().list(
                            part='snippet,liveStreamingDetails,statistics',
                            id=video_id
                        ).execute()
                        
                        if not video_response.get('items'):
                            continue
                        
                        video = video_response['items'][0]
                        videos.append({
                            'id': video_id,
                            'published_at': published_at,
                            'title': video['snippet']['title'],
                            'is_livestream': video.get('snippet', {}).get('liveBroadcastContent') == 'live',
                            'view_count': video.get('statistics', {}).get('viewCount', '0'),
                            'like_count': video.get('statistics', {}).get('likeCount', '0'),
                            'thumbnail_url': video['snippet']['thumbnails']['high']['url']
                        })
                        
                    except Exception as e:
                        logger.error(f"Error processing video: {str(e)}")
                        continue
                
                # Sort videos by publication date (newest first)
                videos.sort(key=lambda x: x['published_at'], reverse=True)
                
                # Take only the 5 most recent videos
                videos = videos[:5]
                
                # Create main embed
                main_embed = discord.Embed(
                    title="🎥 Latest Videos",
                    description="Here are the 5 most recent videos from the channel:",
                    color=discord.Color.blue()
                )
                
                # Send each video embed
                for video in videos:
                    video_embed = discord.Embed(
                        title=video['title'],
                        description=f"https://www.youtube.com/watch?v={video['id']}",
                        color=discord.Color.red() if video['is_livestream'] else discord.Color.blue(),
                        timestamp=video['published_at']
                    )
                    
                    # Add video thumbnail
                    video_embed.set_thumbnail(url=video['thumbnail_url'])
                    
                    # Add video stats
                    video_embed.add_field(name="Views", value=video['view_count'], inline=True)
                    video_embed.add_field(name="Likes", value=video['like_count'], inline=True)
                    
                    # Add video type indicator
                    video_type = "🔴 LIVE" if video['is_livestream'] else "🎥 Video"
                    video_embed.add_field(name="Type", value=video_type, inline=True)
                    
                    # Add publish date
                    video_embed.set_footer(text=f"Published on {video['published_at'].strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    await ctx.send(embed=video_embed)
                
                # Send summary message
                await ctx.send("That's all the recent videos! 🎉")
                
            except HttpError as e:
                error_message = f"YouTube API error: {e.resp.status} - {e.content}"
                logger.error(error_message)
                await ctx.send(f"An error occurred while accessing YouTube API: {e.resp.status}")
            except ValueError as e:
                error_message = f"Invalid data received: {str(e)}"
                logger.error(error_message)
                await ctx.send("Received invalid data from YouTube. Please try again later.")
            except Exception as e:
                error_message = f"Unexpected error in latest command: {str(e)}"
                logger.error(error_message)
                await ctx.send("An unexpected error occurred. Please check the bot logs for details.")
            
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

        # Add this line after the other initializations
        self.playlist_cache = AsyncCache(maxsize=1)

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