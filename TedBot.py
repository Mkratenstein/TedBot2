import os
import asyncio
import logging
from datetime import datetime, timedelta

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
        
        # YouTube API setup
        self.youtube = build('youtube', 'v3', developerKey=os.getenv('YOUTUBE_API_KEY'))
        
        # Tracking variables
        self.last_livestream = None
        self.last_video = None
        self.last_short = None
        
        # Channel IDs
        self.youtube_channel_id = os.getenv('YOUTUBE_CHANNEL_ID')
        self.discord_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))

    async def on_ready(self):
        logger.info(f'Logged in as {self.user.name}')
        self.check_youtube_updates.start()

    def cog_unload(self):
        self.check_youtube_updates.cancel()

    @tasks.loop(minutes=15)
    async def check_youtube_updates(self):
        try:
            await self.check_livestreams()
            await self.check_videos()
            await self.check_shorts()
        except Exception as e:
            logger.error(f"Error checking YouTube updates: {e}")

    async def check_livestreams(self):
        try:
            request = self.youtube.search().list(
                part='snippet',
                channelId=self.youtube_channel_id,
                type='video',
                eventType='live',
                maxResults=1
            )
            response = request.execute()
            
            if response['items']:
                livestream = response['items'][0]
                livestream_id = livestream['id']['videoId']
                livestream_title = livestream['snippet']['title']
                
                if livestream_id != self.last_livestream:
                    channel = self.get_channel(self.discord_channel_id)
                    await channel.send(f"🎸 LIVE NOW: {livestream_title}\n"
                                       f"https://www.youtube.com/watch?v={livestream_id}")
                    self.last_livestream = livestream_id
        except Exception as e:
            logger.error(f"Error checking livestreams: {e}")

    async def check_videos(self):
        try:
            request = self.youtube.search().list(
                part='snippet',
                channelId=self.youtube_channel_id,
                type='video',
                order='date',
                maxResults=1
            )
            response = request.execute()
            
            if response['items']:
                video = response['items'][0]
                video_id = video['id']['videoId']
                video_title = video['snippet']['title']
                published_at = datetime.fromisoformat(video['snippet']['publishedAt'].replace('Z', '+00:00'))
                
                if video_id != self.last_video and published_at > datetime.now(published_at.tzinfo) - timedelta(hours=24):
                    channel = self.get_channel(self.discord_channel_id)
                    await channel.send(f"🎵 New Video: {video_title}\n"
                                       f"https://www.youtube.com/watch?v={video_id}")
                    self.last_video = video_id
        except Exception as e:
            logger.error(f"Error checking videos: {e}")

    async def check_shorts(self):
        try:
            request = self.youtube.search().list(
                part='snippet',
                channelId=self.youtube_channel_id,
                type='video',
                videoCategoryId='shorts',
                order='date',
                maxResults=1
            )
            response = request.execute()
            
            if response['items']:
                short = response['items'][0]
                short_id = short['id']['videoId']
                short_title = short['snippet']['title']
                published_at = datetime.fromisoformat(short['snippet']['publishedAt'].replace('Z', '+00:00'))
                
                if short_id != self.last_short and published_at > datetime.now(published_at.tzinfo) - timedelta(hours=24):
                    channel = self.get_channel(self.discord_channel_id)
                    await channel.send(f"📱 New Short: {short_title}\n"
                                       f"https://www.youtube.com/shorts/{short_id}")
                    self.last_short = short_id
        except Exception as e:
            logger.error(f"Error checking shorts: {e}")

def main():
    intents = discord.Intents.default()
    intents.message_content = True
    
    bot = GooseBandTracker(intents)
    
    @bot.command()
    async def ping(ctx):
        await ctx.send('Pong! Goose Band Tracker is alive!')

    bot.run(os.getenv('DISCORD_TOKEN'))

if __name__ == '__main__':
    main()