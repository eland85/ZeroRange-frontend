# secure_drive_server.py
# Secure backend that hides API keys from the browser

import os
import json
import time
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Store API key securely on server (not in client code!)
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', 'YOUR_API_KEY_HERE')
CACHE_DURATION = 30  # Cache results for 30 seconds

# Cache to avoid hitting API limits
cache = {
    'data': None,
    'timestamp': 0,
    'folder_id': None
}

def get_drive_files(folder_id):
    """Securely fetch files from Google Drive"""
    
    # Check cache first
    current_time = time.time()
    if (cache['data'] and 
        cache['folder_id'] == folder_id and 
        current_time - cache['timestamp'] < CACHE_DURATION):
        print(f"📦 Returning cached data ({len(cache['data'])} files)")
        return cache['data']
    
    try:
        # Make secure API call from server
        url = f"https://www.googleapis.com/drive/v3/files"
        params = {
            'q': f"'{folder_id}' in parents",
            'key': GOOGLE_API_KEY,
            'fields': 'files(id,name,mimeType,modifiedTime)',
            'pageSize': 1000  # Get up to 1000 files
        }
        
        print(f"🔍 Fetching files from Google Drive folder: {folder_id}")
        print(f"🔗 API URL: {url}")
        print(f"📋 Query parameters: {params}")
        
        response = requests.get(url, params=params, timeout=10)
        print(f"📡 Response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ API Response: {response.text}")
            
        response.raise_for_status()
        
        data = response.json()
        files = data.get('files', [])
        print(f"📁 Total files found: {len(files)}")
        
        # Show all files found
        for file in files:
            print(f"  📄 {file['name']} ({file.get('mimeType', 'unknown')})")
        
        # Filter for images only
        image_files = []
        for file in files:
            if file.get('mimeType', '').startswith('image/'):
                # Extract number from filename
                import re
                match = re.search(r'(\d+)', file['name'])
                if match:
                    index = int(match.group(1))
                    image_files.append({
                        'id': file['id'],
                        'name': file['name'],
                        'index': index,
                        'url': f"https://drive.google.com/uc?id={file['id']}&export=download",
                        'proxy_url': f"/api/proxy-image/{file['id']}",  # Add proxy URL
                        'modified': file.get('modifiedTime', '')
                    })
                    print(f"  ✅ Image matched: {file['name']} → index {index} → ID: {file['id']}")
                else:
                    print(f"  ⚠️ Image skipped (no number): {file['name']}")
            else:
                print(f"  ⏭️ Non-image skipped: {file['name']}")
        
        # Sort by index
        image_files.sort(key=lambda x: x['index'])
        
        # Update cache
        cache['data'] = image_files
        cache['timestamp'] = current_time
        cache['folder_id'] = folder_id
        
        print(f"✅ Found {len(image_files)} matching images")
        return image_files
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API Error: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"❌ Response details: {e.response.text}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None

@app.route('/api/discover/<folder_id>')
def discover_images(folder_id):
    """Discover images in Google Drive folder"""
    
    if not folder_id:
        return jsonify({'error': 'No folder ID provided'}), 400
    
    files = get_drive_files(folder_id)
    
    if files is None:
        return jsonify({'error': 'Failed to fetch files from Google Drive'}), 500
    
    # Convert to index mapping for frontend
    image_mapping = {}
    for file in files:
        image_mapping[file['index']] = {
            'id': file['id'],
            'name': file['name'],
            'url': file['url'],
            'proxy_url': file['proxy_url'],
            'modified': file['modified']
        }
    
    return jsonify({
        'success': True,
        'images': image_mapping,
        'total_found': len(files),
        'folder_id': folder_id,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/proxy-image/<file_id>')
def proxy_image(file_id):
    """Proxy Google Drive images to avoid CORS issues"""
    try:
        print(f"🖼️ Proxying image: {file_id}")
        
        # Get image from Google Drive
        drive_url = f"https://drive.google.com/uc?id={file_id}&export=download"
        print(f"🔗 Fetching from: {drive_url}")
        
        response = requests.get(drive_url, timeout=30)
        print(f"📡 Drive response: {response.status_code}")
        
        response.raise_for_status()
        
        # Return image with proper headers
        return Response(
            response.content,
            mimetype=response.headers.get('content-type', 'image/jpeg'),
            headers={
                'Cache-Control': 'public, max-age=3600',
                'Access-Control-Allow-Origin': '*'
            }
        )
        
    except Exception as e:
        print(f"❌ Proxy image error for {file_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sheets/<sheet_id>')
def get_sheets_data(sheet_id):
    """Proxy Google Sheets data (supports multiple URL formats)"""
    
    # Multiple URL formats to try for published sheets
    url_formats = [
        f"https://docs.google.com/spreadsheets/d/e/{sheet_id}/pub?output=csv",  # Published format
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0",  # Export format
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/pub?output=csv",  # Alternative published format
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"  # Query format
    ]
    
    for i, sheets_url in enumerate(url_formats):
        try:
            print(f"🔗 Trying format {i+1}: {sheets_url}")
            response = requests.get(sheets_url, timeout=10)
            
            # Check if we got HTML instead of CSV (common issue)
            content_type = response.headers.get('content-type', '').lower()
            if 'text/html' in content_type:
                print(f"❌ Format {i+1}: Got HTML instead of CSV")
                continue
                
            response.raise_for_status()
            
            # Get the text with proper encoding
            csv_text = response.text.strip()
            
            # Try to fix encoding issues
            try:
                # If the response has UTF-8 content but wrong encoding
                if response.encoding != 'utf-8':
                    csv_text = response.content.decode('utf-8')
                    print(f"🔤 Fixed encoding from {response.encoding} to UTF-8")
            except Exception as e:
                print(f"⚠️ Encoding fix failed: {e}")
            
            # Basic validation - CSV should have commas or be plain text
            if csv_text and (',' in csv_text or '\n' in csv_text):
                print(f"✅ Format {i+1}: Successfully got CSV data ({len(csv_text)} chars)")
                
                return jsonify({
                    'success': True,
                    'csv_data': csv_text,
                    'url_used': sheets_url,
                    'timestamp': datetime.now().isoformat()
                })
            else:
                print(f"❌ Format {i+1}: Response doesn't look like CSV")
                
        except Exception as e:
            print(f"❌ Format {i+1}: {str(e)}")
            continue
    
    return jsonify({
        'success': False,
        'error': 'All URL formats failed. Make sure sheet is published to web as CSV',
        'tried_formats': len(url_formats)
    }), 500

@app.route('/api/status')
def get_status():
    """Check server status"""
    return jsonify({
        'status': 'running',
        'api_configured': bool(GOOGLE_API_KEY and GOOGLE_API_KEY != "YOUR_API_KEY_HERE"),
        'cache_entries': len([k for k, v in cache.items() if v]),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/')
def index():
    """Simple status page"""
    return f"""
    <html>
    <head><title>Secure Exhibition Backend</title></head>
    <body style="font-family: Arial; max-width: 600px; margin: 50px auto; padding: 20px;">
        <h1>🔒 Secure Exhibition Backend</h1>
        <p><strong>Status:</strong> Running</p>
        <p><strong>API Key:</strong> {'✅ Configured' if GOOGLE_API_KEY != 'YOUR_API_KEY_HERE' else '❌ Not configured'}</p>
        <p><strong>Server Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h3>Available Endpoints:</h3>
        <ul>
            <li><code>/api/discover/FOLDER_ID</code> - Discover images in folder</li>
            <li><code>/api/sheets/SHEET_ID</code> - Get Google Sheets data</li>
            <li><code>/api/proxy-image/FILE_ID</code> - Proxy Google Drive images</li>
            <li><code>/api/status</code> - Server status</li>
        </ul>
        
        <h3>Setup Instructions:</h3>
        <ol>
            <li>Edit this file and replace YOUR_API_KEY_HERE with your real Google API key</li>
            <li>Run: <code>python secure_drive_server.py</code></li>
            <li>Your HTML will connect to <code>http://localhost:5000</code></li>
            <li>API key stays secure on server - never sent to browser!</li>
        </ol>
    </body>
    </html>
    """

if __name__ == '__main__':
    print("🔒 Starting Secure Exhibition Backend...")
    print("📋 Setup Instructions:")
    print("1. Edit this file: Replace 'YOUR_API_KEY_HERE' with your real Google API key")
    print("2. Install dependencies: pip install flask flask-cors requests")
    print("3. Your API key will be secure on the server")
    print("4. Frontend connects to http://localhost:5000/api/...")
    print("\n🚀 Server starting on http://localhost:5000")
    
    app.run(host='0.0.0.0', port=5000, debug=False)