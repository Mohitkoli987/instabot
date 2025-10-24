import os
import json
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

# Google Drive API Scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Files
TOKEN_FILE = 'token.pickle'
CREDENTIALS_FILE = 'client_secret.json'  # Changed from credentials.json
GDRIVE_FILENAME = 'instagram_downloads.json'
GDRIVE_FOLDER_NAME = 'InstagramVideos'  # Folder for video storage

class GoogleDriveManager:
    """Manage Google Drive operations for tracking downloaded links and storing videos"""
    
    def __init__(self):
        self.service = None
        self.file_id = None  # Metadata JSON file ID
        self.folder_id = None  # Video folder ID
        
    def authenticate(self):
        """Authenticate with Google Drive"""
        creds = None
        
        # Load token if exists
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        
        # If no valid credentials, login
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_FILE):
                    print("\n" + "="*70)
                    print("❌ GOOGLE DRIVE SETUP REQUIRED")
                    print("="*70)
                    print("\nTo use Google Drive integration:")
                    print("\n1. Go to: https://console.cloud.google.com/")
                    print("2. Create a new project (or select existing)")
                    print("3. Enable 'Google Drive API'")
                    print("4. Create OAuth 2.0 credentials:")
                    print("   - Application type: Desktop app")
                    print("   - Download the JSON file")
                    print("5. Rename it to 'credentials.json'")
                    print("6. Place it in this folder")
                    print("\n7. Restart the app")
                    print("="*70 + "\n")
                    return False
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save credentials
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('drive', 'v3', credentials=creds)
        print("✅ Google Drive authenticated successfully!")
        return True
    
    def find_or_create_folder(self):
        """Find or create the video storage folder in Google Drive"""
        try:
            # Search for existing folder
            results = self.service.files().list(
                q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                spaces='drive',
                fields='files(id, name)'
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                self.folder_id = files[0]['id']
                print(f"✅ Found existing folder: {GDRIVE_FOLDER_NAME} (ID: {self.folder_id})")
            else:
                # Create new folder
                file_metadata = {
                    'name': GDRIVE_FOLDER_NAME,
                    'mimeType': 'application/vnd.google-apps.folder'
                }
                folder = self.service.files().create(
                    body=file_metadata,
                    fields='id'
                ).execute()
                self.folder_id = folder.get('id')
                print(f"✅ Created new folder: {GDRIVE_FOLDER_NAME} (ID: {self.folder_id})")
            
            return True
        except Exception as e:
            print(f"❌ Error creating folder: {e}")
            return False
    
    def find_file(self):
        """Find the JSON file in Google Drive"""
        try:
            results = self.service.files().list(
                q=f"name='{GDRIVE_FILENAME}' and trashed=false",
                spaces='drive',
                fields='files(id, name)'
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                self.file_id = files[0]['id']
                print(f"✅ Found existing metadata file: {GDRIVE_FILENAME} (ID: {self.file_id})")
                return True
            else:
                print(f"⚠️  Metadata file not found, will create new one")
                return False
        except Exception as e:
            print(f"❌ Error finding file: {e}")
            return False
    
    def download_file(self):
        """Download JSON file from Google Drive"""
        try:
            if not self.file_id:
                if not self.find_file():
                    # File doesn't exist, return empty data
                    return {"links": [], "count": 0}
            
            request = self.service.files().get_media(fileId=self.file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            fh.seek(0)
            data = json.loads(fh.read().decode('utf-8'))
            print(f"✅ Downloaded file from Google Drive ({data['count']} links)")
            return data
            
        except Exception as e:
            print(f"❌ Error downloading file: {e}")
            return {"links": [], "count": 0}
    
    def upload_file(self, data):
        """Upload/Update JSON file to Google Drive"""
        try:
            # Convert data to JSON
            json_data = json.dumps(data, indent=2)
            
            # Create temporary file
            temp_file = 'temp_downloads.json'
            with open(temp_file, 'w') as f:
                f.write(json_data)
            
            file_metadata = {'name': GDRIVE_FILENAME}
            media = MediaFileUpload(temp_file, mimetype='application/json', resumable=True)
            
            if self.file_id:
                # Update existing file
                self.service.files().update(
                    fileId=self.file_id,
                    media_body=media
                ).execute()
                print(f"✅ Updated file on Google Drive ({data['count']} links)")
            else:
                # Create new file
                file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
                self.file_id = file.get('id')
                print(f"✅ Created new file on Google Drive (ID: {self.file_id})")
            
            # Clean up temp file
            os.remove(temp_file)
            return True
            
        except Exception as e:
            print(f"❌ Error uploading file: {e}")
            return False
    
    def get_downloaded_links(self):
        """Get list of downloaded links from Google Drive"""
        if not self.service:
            if not self.authenticate():
                return {"links": [], "count": 0}
        
        return self.download_file()
    
    def add_downloaded_link(self, url, filename):
        """Add a new downloaded link to Google Drive"""
        if not self.service:
            if not self.authenticate():
                return False
        
        # Get current data
        data = self.download_file()
        
        # Add new link
        from datetime import datetime
        data["links"].append({
            "url": url,
            "filename": filename,
            "downloaded_at": datetime.now().isoformat()
        })
        data["count"] = len(data["links"])
        
        # Upload updated data
        return self.upload_file(data)
    
    def is_already_downloaded(self, url):
        """Check if URL was already downloaded"""
        if not self.service:
            if not self.authenticate():
                return False
        
        data = self.download_file()
        return any(item["url"] == url for item in data["links"])
    
    def upload_video(self, local_path, filename):
        """Upload video to Google Drive folder"""
        try:
            if not self.service:
                if not self.authenticate():
                    return None
            
            if not self.folder_id:
                self.find_or_create_folder()
            
            file_metadata = {
                'name': filename,
                'parents': [self.folder_id]
            }
            
            media = MediaFileUpload(local_path, resumable=True)
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
            
            file_id = file.get('id')
            file_name = file.get('name')
            web_link = file.get('webViewLink')
            
            print(f"✅ Uploaded video to Google Drive: {file_name} (ID: {file_id})")
            return file_id
            
        except Exception as e:
            print(f"❌ Error uploading video to Google Drive: {e}")
            return None
    
    def download_video(self, file_id, output_path):
        """Download video from Google Drive"""
        try:
            if not self.service:
                if not self.authenticate():
                    return False
            
            request = self.service.files().get_media(fileId=file_id)
            fh = io.FileIO(output_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    print(f"📥 Download progress: {int(status.progress() * 100)}%")
            
            print(f"✅ Downloaded video from Google Drive to: {output_path}")
            return True
            
        except Exception as e:
            print(f"❌ Error downloading video from Google Drive: {e}")
            return False
    
    def delete_video(self, file_id):
        """Delete video from Google Drive (after YouTube upload)"""
        try:
            if not self.service:
                if not self.authenticate():
                    return False
            
            self.service.files().delete(fileId=file_id).execute()
            print(f"✅ Deleted video from Google Drive (ID: {file_id})")
            return True
            
        except Exception as e:
            print(f"❌ Error deleting video from Google Drive: {e}")
            return False


# Global instance
gdrive_manager = GoogleDriveManager()


def setup_google_drive():
    """Setup Google Drive authentication"""
    print("\n" + "="*70)
    print("🔧 Setting up Google Drive Integration")
    print("="*70)
    
    if gdrive_manager.authenticate():
        gdrive_manager.find_file()
        gdrive_manager.find_or_create_folder()  # Create video folder
        data = gdrive_manager.get_downloaded_links()
        print(f"\n✅ Google Drive ready! Currently tracking {data['count']} downloads")
        print("="*70 + "\n")
        return True
    else:
        print("\n⚠️  Google Drive setup incomplete. Using local storage instead.")
        print("="*70 + "\n")
        return False
