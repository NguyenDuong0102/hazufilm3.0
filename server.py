import os
import asyncio
import traceback
from aiohttp import web
from pyrogram import Client

# ================= CẤU HÌNH =================
# Ưu tiên lấy từ biến môi trường (cho Render), nếu không có thì dùng giá trị mặc định
API_ID = int(os.environ.get("API_ID", 30786494))
API_HASH = os.environ.get("API_HASH", "1b3896cea49b4aa6a5d4061f71d74897")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8578661013:AAHd_0zxURy-3LU20GXa9odpehNrw0qXWiU")

# Cố gắng lấy ID kênh từ biến môi trường
CHANNEL_ID_ENV = os.environ.get("CHANNEL_ID", "-1001234567890") 
try:
    # Nếu là số (ví dụ -100...), chuyển sang int
    CHANNEL_ID = int(CHANNEL_ID_ENV)
except ValueError:
    # Nếu là chữ (username), giữ nguyên string
    CHANNEL_ID = CHANNEL_ID_ENV
# ============================================

# Khởi tạo Client (Chưa start vội)
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
MOVIE_CATALOG = {} 

# --- MIDDLEWARE CORS ---
@web.middleware
async def cors_middleware(request, handler):
    if request.method == 'OPTIONS':
        return web.Response(headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Range',
        })
    try:
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except web.HTTPException as ex:
        ex.headers['Access-Control-Allow-Origin'] = '*'
        raise ex

# --- QUÉT PHIM (BACKGROUND TASK) ---
async def refresh_catalog():
    global MOVIE_CATALOG
    print(f"🔄 Đang chạy ngầm: Quét phim từ kênh {CHANNEL_ID}...")
    
    temp = {}
    count_video = 0
    
    try:
        # Kiểm tra kết nối kênh
        try:
            chat = await app.get_chat(CHANNEL_ID)
            print(f"✅ Kết nối kênh thành công: {chat.title}")
        except Exception as e:
            print(f"⚠️ Không thể truy cập kênh {CHANNEL_ID}. Lỗi: {e}")
            print("👉 Hãy kiểm tra: 1. Bot đã vào kênh chưa? 2. Bot có quyền Admin không? 3. ID kênh đúng chưa?")
            return

        # Quét tin nhắn
        async for msg in app.get_chat_history(chat.id, limit=500):
            media = msg.video or msg.document
            if media:
                file_name = getattr(media, "file_name", None) or msg.caption or f"Video_{msg.id}.mp4"
                # Lấy dòng đầu tiên của caption/tên file
                file_name = file_name.split('\n')[0].strip()

                if not any(file_name.lower().endswith(ext) for ext in ['.mp4', '.mkv', '.avi']):
                    if not msg.video: continue 

                count_video += 1
                base_name = os.path.splitext(file_name)[0]
                
                if " - " in base_name:
                    try:
                        parts = base_name.rsplit(" - ", 1)
                        title, episode = parts[0].strip(), parts[1].strip()
                    except:
                        title, episode = base_name, "Full"
                else:
                    title, episode = base_name, "Full"

                if title not in temp: temp[title] = {}
                temp[title][episode] = {
                    "msg_id": msg.id,
                    "size": media.file_size,
                    "mime": media.mime_type or "video/mp4"
                }
        
        MOVIE_CATALOG = temp
        print(f"✅ QUÉT XONG! Tổng video: {count_video}")
        
    except Exception as e:
        print(f"❌ Lỗi trong quá trình quét: {e}")
        traceback.print_exc()

# --- QUẢN LÝ KHỞI ĐỘNG (QUAN TRỌNG) ---
async def start_background_tasks(app_runner):
    """
    Hàm này chạy song song khi web server khởi động.
    Nó giúp Web Server online NGAY LẬP TỨC (tránh lỗi 404/Timeout trên Render)
    sau đó mới từ từ đăng nhập Bot và quét phim.
    """
    print("🚀 Web Server đã Online! Đang khởi động Bot ngầm...")
    try:
        await app.start()
        print("🤖 Bot đã đăng nhập!")
        # Chạy quét phim dưới nền, không chặn web
        asyncio.create_task(refresh_catalog())
    except Exception as e:
        print(f"🔥 LỖI KHỞI ĐỘNG BOT: {e}")
        print("Web vẫn chạy nhưng sẽ không có dữ liệu phim.")

async def cleanup_background_tasks(app_runner):
    print("🛑 Đang dừng Bot...")
    try:
        await app.stop()
    except: pass

# --- API HANDLERS ---
async def index_handler(request):
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return web.Response(text=f.read(), content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="<h1>Lỗi: Không tìm thấy file index.html trên Server</h1>", status=404, content_type='text/html')

async def get_catalog(request):
    # Trả về danh sách phim. Nếu chưa quét xong thì trả về rỗng {} chứ không lỗi.
    return web.json_response(MOVIE_CATALOG)

async def trigger_refresh(request):
    asyncio.create_task(refresh_catalog())
    return web.Response(text="Đã gửi lệnh quét phim.")

async def stream_handler(request):
    try:
        msg_id = int(request.match_info['id'])
        # Ép kiểu ID kênh về int nếu cần thiết
        try: chat_id = int(CHANNEL_ID)
        except: chat_id = CHANNEL_ID

        msg = await app.get_messages(chat_id, msg_id)
        if not msg or (not msg.video and not msg.document):
            return web.Response(status=404, text="Video Not Found")

        media = msg.video or msg.document
        file_size = media.file_size
        
        range_header = request.headers.get('Range', None)
        from_bytes, until_bytes = 0, file_size - 1
        if range_header:
            try:
                parts = range_header.replace('bytes=', '').split('-')
                from_bytes = int(parts[0])
                if len(parts) > 1 and parts[1]: until_bytes = int(parts[1])
            except: pass
        
        length = until_bytes - from_bytes + 1
        headers = {
            'Content-Type': media.mime_type or "video/mp4",
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': f'inline; filename="video_{msg_id}.mp4"'
        }
        
        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)
        
        try:
            async for chunk in app.stream_media(msg, offset=from_bytes, limit=length):
                await resp.write(chunk)
        except: pass
        return resp
    except Exception as e:
        print(f"Stream Error: {e}")
        return web.Response(status=500, text="Internal Error")

# --- MAIN ENTRY ---
if __name__ == '__main__':
    try:
        import uvloop
        uvloop.install()
    except: pass

    # Cấu hình Web Server
    server = web.Application(middlewares=[cors_middleware])
    
    # Định nghĩa Route
    server.add_routes([
        web.get('/', index_handler),
        web.get('/api/catalog', get_catalog),
        web.get('/api/refresh', trigger_refresh),
        web.get('/watch/{id}', stream_handler)
    ])
    
    # Đăng ký sự kiện chạy Bot khi Web start
    server.on_startup.append(start_background_tasks)
    server.on_cleanup.append(cleanup_background_tasks)
    
    # Chạy App
    port = int(os.environ.get("PORT", 8080))
    print(f"🌍 Starting Web Server on port {port}...")
    web.run_app(server, port=port)
