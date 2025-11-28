import os
import asyncio
import traceback
from aiohttp import web
from pyrogram import Client

# ================= CẤU HÌNH =================
API_ID = 30786494               # THAY CỦA BẠN
API_HASH = "1b3896cea49b4aa6a5d4061f71d74897" # THAY CỦA BẠN
BOT_TOKEN = "8578661013:AAHd_0zxURy-3LU20GXa9odpehNrw0qXWiU" # THAY CỦA BẠN
CHANNEL_ID = -1003484849978      # THAY ID KÊNH (-100...)
# ============================================

# [QUAN TRỌNG] ĐIỀN LINK MỜI VÀO ĐÂY ĐỂ FIX LỖI "MẤT TRÍ NHỚ"
# Link dạng: https://t.me/+AbCd... (Lấy trong Manage Channel -> Invite Links)
PRIVATE_LINK = "https://t.me/+xxxxxxxxxxxxxx" 
# ====================================================

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
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Range'
        return response
    except web.HTTPException as ex:
        ex.headers['Access-Control-Allow-Origin'] = '*'
        raise ex

# --- HÀM XỬ LÝ TÊN (CHẾ ĐỘ AN TOÀN - KHÔNG BỎ SÓT) ---
def safe_parse_name(filename):
    # 1. Bỏ đuôi file (.mp4, .mkv)
    base_name = os.path.splitext(filename)[0]
    
    # 2. Thử tách bằng dấu gạch ngang " - " (Nếu có)
    if " - " in base_name:
        try:
            name, ep = base_name.rsplit(" - ", 1)
            return name.strip(), ep.strip()
        except:
            pass # Nếu lỗi thì xuống dưới lấy nguyên tên
            
    # 3. Nếu không tách được -> Lấy nguyên tên file làm tên Phim
    return base_name.strip(), "Xem Ngay"

# --- HÀM KẾT NỐI (BẮT BUỘC ĐỂ KHÔNG BỊ LỖI PEER ID) ---
async def fix_channel_access():
    print("🔄 Đang kết nối kênh bằng Link Mời...")
    try:
        if "t.me/+" in PRIVATE_LINK:
            chat = await app.get_chat(PRIVATE_LINK)
            print(f"✅ Đã kết nối: {chat.title}")
        else:
            print("⚠️ Bạn chưa điền PRIVATE_LINK hoặc Link không đúng dạng t.me/+")
    except Exception as e:
        print(f"❌ Lỗi kết nối kênh: {e}")

# --- QUÉT PHIM ---
async def refresh_catalog():
    global MOVIE_CATALOG
    print("🔄 ĐANG QUÉT TOÀN BỘ FILE (CHẾ ĐỘ LẤY HẾT)...")
    temp = {}
    count = 0
    try:
        # limit=0 là lấy tất cả. Nếu kênh quá nhiều (>2000) có thể chỉnh lại thành 500
        async for msg in app.get_chat_history(CHANNEL_ID, limit=0):
            if msg.video or msg.document:
                count += 1
                fname = msg.video.file_name if msg.video else (msg.document.file_name or msg.caption or "NoName")
                
                # Gọi hàm xử lý tên an toàn
                name, ep = safe_parse_name(fname)
                
                # Thêm vào danh sách (Không lọc gì cả)
                if name not in temp: temp[name] = {}
                temp[name][ep] = msg.id
                
        MOVIE_CATALOG = temp
        print(f"✅ Đã tìm thấy {count} file video -> Gom thành {len(MOVIE_CATALOG)} phim.")
    except Exception as e:
        print(f"❌ LỖI QUÉT: {e}")

# --- API & STREAM ---
async def get_catalog(request):
    if not MOVIE_CATALOG: await refresh_catalog()
    return web.json_response(MOVIE_CATALOG)

async def trigger_refresh(request):
    asyncio.create_task(refresh_catalog())
    return web.Response(text="Đang cập nhật...")

async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        if not msg or (not msg.video and not msg.document):
            return web.Response(status=404, text="Not Found")

        file_size = msg.video.file_size if msg.video else msg.document.file_size
        mime = msg.video.mime_type if msg.video else msg.document.mime_type
        
        range_header = request.headers.get('Range', 0)
        from_bytes, until_bytes = 0, file_size - 1
        if range_header:
            try:
                parts = range_header.replace('bytes=', '').split('-')
                from_bytes = int(parts[0])
                if parts[1]: until_bytes = int(parts[1])
            except: pass
        length = until_bytes - from_bytes + 1
        
        headers = {
            'Content-Type': mime,
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': 'inline',
        }
        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)
        async for chunk in app.stream_media(msg, offset=from_bytes, limit=length):
            await resp.write(chunk)
        return resp
    except: return web.Response(status=500)

# --- STARTUP ---
async def on_startup():
    print("🚀 Khởi động...")
    await app.start()
    await fix_channel_access() # Kết nối lại kênh
    await refresh_catalog()    # Quét phim

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup())
    server = web.Application(middlewares=[cors_middleware])
    server.add_routes([
        web.get('/', lambda r: web.Response(text="Server OK")),
        web.get('/api/catalog', get_catalog),
        web.get('/api/refresh', trigger_refresh),
        web.get('/watch/{message_id}', stream_handler)
    ])
    port = int(os.environ.get("PORT", 8080))
    web.run_app(server, port=port)
