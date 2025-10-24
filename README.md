# 🎥 Instagram to YouTube Uploader

Automatically download Instagram Reels and upload them to YouTube with proper credits and duplicate detection.

## ✨ Features

- ✅ Download Instagram Reels/Posts
- ✅ Auto-upload to YouTube with credits
- ✅ Duplicate detection (won't re-upload)
- ✅ Google Drive cloud storage
- ✅ Single Page App (smooth UX)
- ✅ No page reloads

## 🚀 Quick Deploy (FREE)

### Option 1: Render (Recommended)
1. Push to GitHub
2. Go to [render.com](https://render.com)
3. Create "Web Service" from your GitHub repo
4. Done! Auto-deploys

### Option 2: Railway
1. Go to [railway.app](https://railway.app)
2. "New Project" → Deploy from GitHub
3. Done!

**See DEPLOY.txt for detailed instructions**

## 📦 Local Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python app.py

# Visit
http://localhost:5001
```

## 📁 Project Structure

```
├── app.py              # Backend (Flask)
├── templates/
│   └── home.html      # Frontend (Single Page App)
├── static/css/
│   └── style.css      # Styling
├── google_drive.py    # Cloud storage
├── requirements.txt   # Dependencies
├── Procfile          # Deployment config
└── runtime.txt       # Python version
```

## 🔧 Configuration

1. **YouTube API**: Add your `client_secret.json`
2. **Instagram Login**: Update credentials in `app.py`
3. **Google Drive** (optional): Add `credentials.json`

## 📝 Tech Stack

- **Backend**: Flask (Python)
- **Download**: yt-dlp
- **Upload**: YouTube Data API v3
- **Storage**: Google Drive API
- **Frontend**: HTML + Vanilla JS

## ⚠️ Important Notes

- Free hosting platforms have temporary storage
- Use Google Drive for persistent file tracking
- YouTube API requires OAuth setup

## 🎯 Ready to Deploy!

All files are configured for deployment. Just push to GitHub and deploy to Render/Railway!

See **DEPLOY.txt** for step-by-step instructions.
