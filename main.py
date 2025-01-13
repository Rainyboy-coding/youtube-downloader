from fastapi import FastAPI, Request, BackgroundTasks, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import yt_dlp
import os
import time
from datetime import datetime
import asyncio
import json
import logging
import ssl
import certifi

# 在文件开头添加日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 在 app = FastAPI() 之前添加
ssl._create_default_https_context = ssl._create_unverified_context

app = FastAPI()

# 配置静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 确保下载目录存在
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 存储下载进度的字典
download_progress = {}

def download_video(url: str, video_id: str):
    try:
        def progress_hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = (downloaded / total) * 100
                    download_progress[video_id] = {
                        'progress': progress,
                        'status': 'downloading'
                    }
                    logger.info(f"Download progress: {progress:.2f}%")
            elif d['status'] == 'finished':
                download_progress[video_id]['status'] = 'finished'
                logger.info("Download finished")

        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook],
            'quiet': False,
            'no_warnings': False,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'no_color': True,
            'extract_flat': False,
            'force_generic_extractor': False,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        logger.info(f"Starting download for URL: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # 先尝试获取视频信息
                info = ydl.extract_info(url, download=False)
                if info:
                    logger.info(f"Video info extracted: {info.get('title', 'Unknown')}")
                    # 如果信息获取成功，再进行下载
                    info = ydl.extract_info(url, download=True)
                    logger.info(f"Download completed for: {info.get('title', 'Unknown')}")
                    return info
                else:
                    raise Exception("无法获取视频信息")
            except Exception as e:
                logger.error(f"Download failed: {str(e)}")
                raise

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in download_video: {error_msg}")
        download_progress[video_id] = {
            'progress': 0,
            'status': 'error',
            'error': error_msg
        }
        raise

@app.get("/")
async def read_root(request: Request):
    # 获取已下载的视频列表
    videos = []
    for filename in os.listdir(DOWNLOAD_DIR):
        if filename.endswith(('.mp4', '.webm')):
            file_path = os.path.join(DOWNLOAD_DIR, filename)
            file_stats = os.stat(file_path)
            videos.append({
                'title': filename,
                'path': f'/downloads/{filename}',
                'size': f'{file_stats.st_size / (1024*1024):.2f} MB',
                'date': datetime.fromtimestamp(file_stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "videos": videos
    })

@app.post("/download")
async def download(background_tasks: BackgroundTasks, url: str = Form(...)):
    try:
        logger.info(f"Received download request for URL: {url}")
        video_id = str(time.time())
        download_progress[video_id] = {'progress': 0, 'status': 'starting'}
        
        # 在后台任务中下载视频
        background_tasks.add_task(download_video, url, video_id)
        
        return {"video_id": video_id}
    except Exception as e:
        logger.error(f"Error in download endpoint: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": f"下载失败: {str(e)}"}
        )

@app.get("/progress/{video_id}")
async def get_progress(video_id: str):
    return download_progress.get(video_id, {'progress': 0, 'status': 'unknown'})

# 配置视频文件的静态服务
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8080,
        reload=True
    ) 