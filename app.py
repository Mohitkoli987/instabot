import os
import json
import subprocess
import requests
import re
from flask import Flask, render_template, request, send_from_directory, jsonify
from datetime import datetime

# Try to import Google Drive, fallback to local storage
try:
    from google_drive import gdrive_manager, setup_google_drive
    USE_GDRIVE = True
    print("✅ Google Drive module loaded")
except ImportError:
    USE_GDRIVE = False
    print("⚠️  Google Drive module not available, using local storage")

# YouTube integration
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
YOUTUBE_CLIENT_SECRETS = "client_secret.json"
YOUTUBE_TOKEN_FILE = "youtube_token.pickle"
youtube_service = None

# ------------------- CONFIG -------------------
UPLOAD_FOLDER = "downloads"
LINKS_FILE = "downloaded_links.json"
INSTAGRAM_USERNAME = os.environ.get('INSTAGRAM_USERNAME', 'hikon_31')  # Get from env or use default
INSTAGRAM_PASSWORD = os.environ.get('INSTAGRAM_PASSWORD', 'kolikoli')  # Get from env or use default
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------- FLASK APP -------------------
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ------------------- LINK TRACKING -------------------

def load_downloaded_links():
    """Load previously downloaded links from Google Drive or local JSON file"""
    if USE_GDRIVE:
        try:
            return gdrive_manager.get_downloaded_links()
        except Exception as e:
            print(f"⚠️  Google Drive error: {e}, falling back to local storage")
    
    # Fallback to local JSON
    if os.path.exists(LINKS_FILE):
        try:
            with open(LINKS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"links": [], "count": 0}
    return {"links": [], "count": 0}

def save_downloaded_link(url, filename, youtube_url=None, gdrive_file_id=None):
    """Save downloaded link metadata to Google Drive or local file"""
    if USE_GDRIVE:
        try:
            # Get current data
            data = load_downloaded_links()
            
            # Add new link with YouTube URL and Google Drive file ID
            from datetime import datetime
            data["links"].append({
                "url": url,
                "filename": filename,
                "youtube_url": youtube_url,
                "gdrive_file_id": gdrive_file_id,
                "downloaded_at": datetime.now().isoformat()
            })
            data["count"] = len(data["links"])
            
            # Upload to Google Drive
            success = gdrive_manager.upload_file(data)
            if success:
                print(f"☁️  Metadata saved to Google Drive: {url}")
                return
            else:
                print("⚠️  Google Drive save failed, using local storage")
        except Exception as e:
            print(f"⚠️  Google Drive error: {e}, using local storage")
    
    # Fallback to local JSON
    data = load_downloaded_links()
    data["links"].append({
        "url": url,
        "filename": filename,
        "youtube_url": youtube_url,
        "gdrive_file_id": gdrive_file_id,
        "downloaded_at": datetime.now().isoformat()
    })
    data["count"] = len(data["links"])
    
    with open(LINKS_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"💾 Metadata saved to local file: {url}")

def is_already_downloaded(url):
    """Check if URL was already downloaded (checks Google Drive or local file)"""
    if USE_GDRIVE:
        try:
            return gdrive_manager.is_already_downloaded(url)
        except Exception as e:
            print(f"⚠️  Google Drive check error: {e}, checking local storage")
    
    # Fallback to local check
    data = load_downloaded_links()
    return any(item["url"] == url for item in data["links"])

def get_youtube_url_if_uploaded(url):
    """Check if URL was already uploaded to YouTube and return the YouTube URL"""
    data = load_downloaded_links()
    for item in data["links"]:
        if item["url"] == url:
            return item.get("youtube_url")
    return None

# ------------------- YOUTUBE INTEGRATION -------------------

def authenticate_youtube():
    """Authenticate with YouTube API"""
    global youtube_service
    
    if youtube_service:
        return youtube_service
    
    creds = None
    
    # Load token if exists
    if os.path.exists(YOUTUBE_TOKEN_FILE):
        with open(YOUTUBE_TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(YOUTUBE_CLIENT_SECRETS):
                print("⚠️  YouTube API credentials not found (client_secret.json)")
                return None
            
            flow = InstalledAppFlow.from_client_secrets_file(
                YOUTUBE_CLIENT_SECRETS, YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save credentials
        with open(YOUTUBE_TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
    
    youtube_service = build('youtube', 'v3', credentials=creds)
    print("✅ YouTube authenticated successfully!")
    return youtube_service

def upload_to_youtube(video_path, title, description, tags=None, privacy="public"):
    """Upload video to YouTube"""
    service = authenticate_youtube()
    
    if not service:
        return None, "YouTube authentication failed"
    
    try:
        body = {
            "snippet": {
                "title": title[:100],  # YouTube title limit
                "description": description[:5000],  # YouTube description limit
                "tags": tags or [],
                "categoryId": "22"  # People & Blogs
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False
            }
        }
        
        # Use resumable upload
        media = MediaFileUpload(
            video_path,
            chunksize=1024*1024,  # 1MB chunks
            resumable=True,
            mimetype="video/*"
        )
        
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"📤 Upload progress: {int(status.progress() * 100)}%")
        
        video_id = response.get("id")
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        
        print(f"✅ Video uploaded to YouTube: {youtube_url}")
        return video_id, youtube_url
        
    except Exception as e:
        print(f"❌ YouTube upload error: {e}")
        return None, str(e)

# ------------------- INSTAGRAM METADATA SCRAPING -------------------

def get_instagram_metadata(post_url):
    """Fetch username and description from Instagram post/reel URL using yt-dlp"""
    try:
        # Use yt-dlp to extract metadata (much more reliable)
        cmd = [
            'yt-dlp',
            '--dump-json',
            '--no-playlist',
            '--quiet',
            '--no-warnings',
            '--username', INSTAGRAM_USERNAME,
            '--password', INSTAGRAM_PASSWORD,
            post_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout:
            metadata = json.loads(result.stdout)
            
            # Extract username
            username = metadata.get('uploader') or metadata.get('channel') or metadata.get('uploader_id')
            
            # Extract description
            description = metadata.get('description') or metadata.get('title')
            
            # Clean up description if it's too long
            if description and len(description) > 500:
                description = description[:500] + '...'
            
            return username, description
        
        # Fallback to web scraping if yt-dlp fails
        return scrape_instagram_metadata(post_url)
        
    except Exception as e:
        print(f"⚠️ Error fetching metadata with yt-dlp: {e}")
        # Fallback to web scraping
        return scrape_instagram_metadata(post_url)

def scrape_instagram_metadata(post_url):
    """Fallback method: Scrape metadata from Instagram HTML"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        response = requests.get(post_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None, None
        
        html = response.text
        
        # Try to find JSON-LD data
        username = None
        description = None
        
        # Extract from meta tags
        og_description = re.search(r'<meta property="og:description" content="([^"]+)"', html)
        if og_description:
            description = og_description.group(1)
            # Parse username from description (format: "XXX Likes, XXX Comments - @username on Instagram: ...")
            username_match = re.search(r'@([a-zA-Z0-9._]+)', description)
            if username_match:
                username = username_match.group(1)
            
            # Extract caption after "Instagram:"
            if ' on Instagram: ' in description:
                description = description.split(' on Instagram: ', 1)[1].strip('"')
        
        # Alternative: Extract from JSON in HTML
        json_match = re.search(r'window\._sharedData = ({.+?});</script>', html)
        if json_match:
            try:
                shared_data = json.loads(json_match.group(1))
                # Navigate through Instagram's data structure
                entry_data = shared_data.get('entry_data', {})
                post_page = entry_data.get('PostPage', [{}])[0]
                media = post_page.get('graphql', {}).get('shortcode_media', {})
                
                if not username:
                    username = media.get('owner', {}).get('username')
                
                if not description:
                    edges = media.get('edge_media_to_caption', {}).get('edges', [])
                    if edges:
                        description = edges[0].get('node', {}).get('text')
            except:
                pass
        
        return username, description
        
    except Exception as e:
        print(f"⚠️ Error scraping metadata: {e}")
        return None, None

# ------------------- VIDEO DOWNLOAD -------------------

def download_video_ytdlp(post_url):
    """Download Instagram video using yt-dlp and upload to Google Drive"""
    try:
        output_template = os.path.join(UPLOAD_FOLDER, '%(id)s.%(ext)s')
        
        cmd = [
            'yt-dlp',
            '-f', 'best',
            '-o', output_template,
            '--no-playlist',
            '--quiet',
            '--no-warnings',
            '--username', INSTAGRAM_USERNAME,
            '--password', INSTAGRAM_PASSWORD,
            post_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            files = [f for f in os.listdir(UPLOAD_FOLDER) 
                    if f.endswith(('.mp4', '.jpg', '.png'))]
            
            if files:
                latest_file = max(files, 
                    key=lambda x: os.path.getctime(os.path.join(UPLOAD_FOLDER, x)))
                
                # Upload to Google Drive if enabled
                gdrive_file_id = None
                if USE_GDRIVE:
                    try:
                        local_path = os.path.join(UPLOAD_FOLDER, latest_file)
                        gdrive_file_id = gdrive_manager.upload_video(local_path, latest_file)
                        if gdrive_file_id:
                            print(f"☁️ Video uploaded to Google Drive: {latest_file}")
                            # Delete local file after upload
                            os.remove(local_path)
                            print(f"🗑️ Local file deleted: {latest_file}")
                    except Exception as e:
                        print(f"⚠️ Google Drive upload error: {e}")
                
                return latest_file, True, "Success", gdrive_file_id
        
        return None, False, result.stderr or "Download failed", None
        
    except subprocess.TimeoutExpired:
        return None, False, "Download timeout", None
    except Exception as e:
        return None, False, str(e), None

# ------------------- ROUTES -------------------

@app.route(f"/{UPLOAD_FOLDER}/<filename>")
def download_file(filename):
    """Serve downloaded files"""
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/manual", methods=["GET", "POST"])
def manual():
    """Manual URL download page"""
    if request.method == "POST":
        urls_text = request.form.get('urls', '').strip()
        
        if not urls_text:
            return render_template('error.html',
                title="Error",
                heading="❌ Error",
                message="Please provide at least one Instagram URL!")
        
        # Parse URLs
        urls = [url.strip() for url in urls_text.split('\n') if url.strip()]
        
        # Validate Instagram URLs
        valid_urls = []
        for url in urls:
            if 'instagram.com' in url and ('/p/' in url or '/reel/' in url):
                valid_urls.append(url)
        
        if not valid_urls:
            return render_template('error.html',
                title="Error",
                heading="❌ Invalid URLs",
                message="No valid Instagram URLs found. Make sure URLs contain 'instagram.com/p/' or 'instagram.com/reel/'")
        
        # Check yt-dlp
        try:
            subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
        except:
            return render_template('error.html',
                title="yt-dlp Not Installed",
                heading="⚠️ yt-dlp Not Installed",
                message="Please install yt-dlp first: pip3 install yt-dlp")
        
        # Check for duplicates FIRST
        downloaded = []
        skipped = []
        failed = []
        
        for url in valid_urls:
            # Fetch metadata (username and description)
            print(f"\n🔍 Fetching metadata for: {url}")
            username, description = get_instagram_metadata(url)
            
            if username:
                print(f"👤 Username: @{username}")
            if description:
                print(f"📝 Description: {description[:100]}..." if len(description) > 100 else f"📝 Description: {description}")
            
            # Check if already downloaded
            if is_already_downloaded(url):
                print(f"⏭️ Skipping (already downloaded): {url}")
                skipped.append({
                    'url': url,
                    'reason': 'Already downloaded',
                    'username': username or 'Unknown',
                    'description': description or 'No description available'
                })
                continue
            
            print(f"\n📥 Downloading: {url}")
            filename, success, message, gdrive_file_id = download_video_ytdlp(url)
            
            if success:
                save_downloaded_link(url, filename, gdrive_file_id=gdrive_file_id)
                downloaded.append({
                    'url': url,
                    'filename': filename,
                    'shortcode': url.split('/')[-2] if '/' in url else 'unknown',
                    'username': username or 'Unknown',
                    'description': description or 'No description available'
                })
                print(f"✅ Downloaded: {filename}")
            else:
                failed.append({
                    'url': url,
                    'error': message,
                    'username': username or 'Unknown',
                    'description': description or 'No description available'
                })
                print(f"❌ Failed: {message}")
        
        return render_template('results.html',
            hashtag="Manual URLs",
            downloaded=downloaded,
            skipped=skipped,
            failed=failed)
    
    # Show manual input form
    return render_template('manual.html')

@app.route("/check-url", methods=["POST"])
def check_url():
    """Check if URL is already downloaded and fetch metadata (AJAX endpoint)"""
    url = request.json.get('url', '').strip()
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    is_duplicate = is_already_downloaded(url)
    
    # Fetch metadata
    username, description = get_instagram_metadata(url)
    
    return jsonify({
        'url': url,
        'is_duplicate': is_duplicate,
        'message': 'Already downloaded' if is_duplicate else 'New URL',
        'username': username,
        'description': description
    })

@app.route("/stats")
def stats():
    """Show download statistics - now uses home.html"""
    data = load_downloaded_links()
    return render_template('home.html', total_downloads=data['count'], data=data)

@app.route("/", methods=["GET", "POST"])
def index():
    """Home page - Single page application"""
    data = load_downloaded_links()
    return render_template('home.html', total_downloads=data['count'], data=data)

@app.route("/instagram-to-youtube", methods=["GET", "POST"])
def instagram_to_youtube():
    """Download from Instagram, upload to YouTube, and delete from Google Drive"""
    if request.method == "POST":
        url = request.form.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'No URL provided'}), 400
        
        # Validate Instagram URL
        if 'instagram.com' not in url or ('/p/' not in url and '/reel/' not in url):
            return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400
        
        try:
            # Check if already uploaded to YouTube
            existing_youtube_url = get_youtube_url_if_uploaded(url)
            if existing_youtube_url:
                print(f"⏭️  Already uploaded to YouTube: {url}")
                return jsonify({
                    'step': 'duplicate',
                    'success': True,
                    'message': 'This video is already uploaded to YouTube!',
                    'instagram_url': url,
                    'youtube_url': existing_youtube_url,
                    'duplicate': True
                })
            
            # Step 1: Fetch metadata
            print(f"\n🔍 Fetching metadata for: {url}")
            username, description = get_instagram_metadata(url)
            
            if not username:
                username = "Unknown"
            if not description:
                description = "Amazing content from Instagram"
            
            # Step 2: Download video from Instagram and upload to Google Drive
            print(f"\n📥 Downloading from Instagram...")
            filename, success, message, gdrive_file_id = download_video_ytdlp(url)
            
            if not success:
                return jsonify({
                    'step': 'download',
                    'success': False,
                    'error': f'Download failed: {message}'
                }), 500
            
            # If using Google Drive, download video from GDrive for YouTube upload
            if USE_GDRIVE and gdrive_file_id:
                video_path = os.path.join(UPLOAD_FOLDER, filename)
                print(f"\n☁️ Downloading from Google Drive for YouTube upload...")
                gdrive_success = gdrive_manager.download_video(gdrive_file_id, video_path)
                if not gdrive_success:
                    return jsonify({
                        'step': 'gdrive_download',
                        'success': False,
                        'error': 'Failed to download video from Google Drive'
                    }), 500
            else:
                video_path = os.path.join(UPLOAD_FOLDER, filename)
            
            # Step 3: Upload to YouTube
            print(f"\n📤 Uploading to YouTube...")
            
            # Prepare YouTube metadata
            youtube_title = description[:100] if description else f"Instagram Reel by @{username}"
            youtube_description = f"""{description}

---
Credit: @{username} on Instagram
Original: {url}

#Instagram #Reels #Viral #Trending
"""
            
            youtube_tags = [
                "Instagram",
                "Reels",
                "Viral",
                "Trending",
                username,
                "shorts"
            ]
            
            video_id, youtube_url_result = upload_to_youtube(
                video_path=video_path,
                title=youtube_title,
                description=youtube_description,
                tags=youtube_tags,
                privacy="public"
            )
            
            if video_id:
                # Delete video from Google Drive after successful YouTube upload
                if USE_GDRIVE and gdrive_file_id:
                    print(f"\n🗑️ Deleting video from Google Drive...")
                    gdrive_manager.delete_video(gdrive_file_id)
                    # Also delete local temp file
                    if os.path.exists(video_path):
                        os.remove(video_path)
                        print(f"🗑️ Local temp file deleted: {filename}")
                
                # Save metadata to tracking with YouTube URL (gdrive_file_id=None since we deleted it)
                save_downloaded_link(url, filename, youtube_url_result, gdrive_file_id=None)
                print(f"✅ Uploaded to YouTube: {youtube_url_result}")
                return jsonify({
                    'step': 'complete',
                    'success': True,
                    'message': 'Video downloaded, uploaded to YouTube, and cleaned up!',
                    'instagram_url': url,
                    'youtube_url': youtube_url_result,
                    'filename': filename,
                    'username': username,
                    'description': description
                })
            else:
                return jsonify({
                    'step': 'upload',
                    'success': False,
                    'error': f'YouTube upload failed: {youtube_url_result}'
                }), 500
        
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    # GET request - show form
    return render_template('instagram_to_youtube.html')

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🎥 Instagram Auto Downloader - Hashtag Search (No Login)")
    print("="*70)
    
    # Setup Google Drive if available
    if USE_GDRIVE:
        print("\n🌟 Attempting Google Drive setup...")
        gdrive_success = setup_google_drive()
        if not gdrive_success:
            print("⚠️  Continuing with local storage")
    else:
        print("\n💾 Using local JSON storage (Google Drive not configured)")
    
    # Setup YouTube
    print("\n📺 Attempting YouTube setup...")
    try:
        if os.path.exists(YOUTUBE_CLIENT_SECRETS):
            authenticate_youtube()
            print("✅ YouTube integration ready!")
        else:
            print("⚠️  YouTube client_secret.json not found")
    except Exception as e:
        print(f"⚠️  YouTube setup error: {e}")
    
    # Check yt-dlp
    try:
        subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
        print("✅ yt-dlp is installed and ready!")
    except:
        print("⚠️  yt-dlp is NOT installed!")
        print("\nInstall it with: pip3 install yt-dlp\n")
    
    # Show stats
    data = load_downloaded_links()
    storage_type = "Google Drive" if USE_GDRIVE else "Local JSON"
    print(f"\n📊 Storage: {storage_type}")
    print(f"📊 Total downloads tracked: {data['count']}")
    
    port = int(os.environ.get('PORT', 5001))
    print(f"\n🌐 Starting server on http://0.0.0.0:{port}")
    print("="*70 + "\n")
    
    # Use host 0.0.0.0 for deployment, debug=False for production
    app.run(host='0.0.0.0', port=port, debug=False)
