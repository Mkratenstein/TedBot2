# Goose Band YouTube and Instagram Discord Tracker

## Overview
This Discord bot tracks the Goose the Band YouTube and Instagram channels, sending notifications when:
- YouTube channel goes live
- New YouTube video or short is uploaded
- Instagram account goes live
- New Instagram post is created
- New Instagram story is posted

## Prerequisites
- Python 3.8+
- Discord Bot Token
- YouTube Data API v3 Key
- Instagram Account for Bot

## Setup
1. Clone the repository
2. Create a virtual environment
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and fill in your details

### Required Environment Variables
- `DISCORD_TOKEN`: Your Discord bot token
- `DISCORD_CHANNEL_ID`: The Discord channel where notifications will be sent
- `YOUTUBE_CHANNEL_ID`: The YouTube channel ID to track
- `YOUTUBE_API_KEY`: Your YouTube Data API v3 key
- `INSTAGRAM_USERNAME`: Bot's Instagram username
- `INSTAGRAM_PASSWORD`: Bot's Instagram password

## Deployment Considerations
- Use a dedicated Instagram account for the bot
- Enable two-factor authentication
- Be aware of Instagram's rate limits and potential account restrictions

## Features
- YouTube live stream detection
- YouTube video and short tracking
- Instagram live stream detection
- Instagram post tracking
- Instagram story tracking
- 15-minute update interval
- Comprehensive logging

## Contributing
Pull requests are welcome. For major changes, please open an issue first.
