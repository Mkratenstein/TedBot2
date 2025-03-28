import os
import asyncio
import logging
from datetime import datetime, timedelta
import sys

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from googleapiclient.discovery import build

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        
        # YouTube API setup
        self.youtube = build('youtube', 'v3', developerKey=os.getenv('YOUTUBE_API_KEY'))
        
        # Tracking variables
        self.last_livestream = None
        self.last_video = None
        self.last_short = None
        
        # Channel IDs
        self.youtube_channel_id = os.getenv('YOUTUBE_CHANNEL_ID')
        self.discord_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))
        
        # Task tracking
        self.active_tasks = set()
        
        # Register commands
        @self.command()
        async def ping(ctx):
            await ctx.send('Pong! Goose Band Tracker is alive!')
            
        @self.command()
        async def status(ctx):
            """Check the status of the bot and its services"""
            status_message = "🟢 Bot Status:\n"
            status_message += f"- Discord: Connected as {self.user.name}\n"
            status_message += f"- YouTube: {'Connected' if self.youtube else 'Disconnected'}\n"
            await ctx.send(status_message)

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
        """Check for new YouTube content"""
        try:
            # Get channel uploads playlist ID
            channel_response = self.youtube.channels().list(
                part='contentDetails',
                id=self.youtube_channel_id
            ).execute()
            
            if not channel_response.get('items'):
                logger.error(f"Could not find YouTube channel with ID: {self.youtube_channel_id}")
                return
                
            uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            logger.info(f"Found uploads playlist ID: {uploads_playlist_id}")
            
            # Get recent videos
            playlist_response = self.youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=5
            ).execute()
            
            if not playlist_response.get('items'):
                logger.warning("No videos found in uploads playlist")
                return
                
            logger.info(f"Found {len(playlist_response['items'])} recent videos")
            
            for item in playlist_response['items']:
                try:
                    video_id = item['snippet']['resourceId']['videoId']
                    published_at = datetime.fromisoformat(item['snippet']['publishedAt'].replace('Z', '+00:00'))
                    
                    # Check if video is recent (within last 24 hours)
                    if published_at > datetime.now(published_at.tzinfo) - timedelta(hours=24):
                        # Check if it's a livestream
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
                        
                        channel = self.get_channel(self.discord_channel_id)
                        
                        if is_livestream and video_id != self.last_livestream:
                            logger.info(f"New livestream detected: {video_id}")
                            await channel.send(f"🔴 Goose is LIVE on YouTube!\n"
                                             f"https://www.youtube.com/watch?v={video_id}")
                            self.last_livestream = video_id
                        elif is_short and video_id != self.last_short:
                            logger.info(f"New short detected: {video_id}")
                            await channel.send(f"🎥 New YouTube Short!\n"
                                             f"https://www.youtube.com/watch?v={video_id}")
                            self.last_short = video_id
                        elif not is_livestream and not is_short and video_id != self.last_video:
                            logger.info(f"New video detected: {video_id}")
                            await channel.send(f"🎥 New YouTube Video!\n"
                                             f"https://www.youtube.com/watch?v={video_id}")
                            self.last_video = video_id
                            
                        break  # Only notify for the most recent video
                except KeyError as e:
                    logger.error(f"Missing required field in video data: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing video: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error checking YouTube updates: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")

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