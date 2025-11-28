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

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
MOVIE_CATALOG = {} # Bộ nhớ chứa danh sách phim

# --- HÀM 1: CẤU HÌNH CORS (CHO PHÉP WEB TRUY CẬP) ---
def cors_headers():
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Range',
    }

# --- HÀM 2: QUÉT PHIM TỪ KÊNH ---
async def refresh_catalog():
    global MOVIE_CATALOG
    print("🔄 Đang quét phim mới...")
    temp = {}
    try:
        # Quét 200 tin nhắn gần nhất
        async for msg in app.get_chat_history(CHANNEL_ID, limit=200):
            if msg.video or msg.document:
                # Lấy tên file
                fname = msg.video.file_name if msg.video else (msg.document.file_name or msg.caption or "NoName")
                
                # Logic tách tên: "Phim A - Tập 1.mp4"
                try:
                    clean_name = os.path.splitext(fname)[0] # Bỏ đuôi .mp4
                    if " - " in clean_name:
                        name, ep = clean_name.rsplit(" - ", 1)
                        name = name.strip()
                        ep = ep.strip().replace("Tap", "").replace("Tập", "").strip()
                    else:
                        name = clean_name
                        ep = "Full"
                    
                    if name not in temp: temp[name] = {}
                    temp[name][ep] = msg.id
                except: pass
        MOVIE_CATALOG = temp
        print(f"✅ Đã cập nhật {len(MOVIE_CATALOG)} phim.")
    except Exception as e:
        print(f"❌ Lỗi quét phim: {e}")

# --- API: LẤY DANH SÁCH PHIM ---
async def get_catalog(request):
    if not MOVIE_CATALOG: await refresh_catalog()
    return web.json_response(MOVIE_CATALOG, headers=cors_headers())

# --- API: UPDATE THỦ CÔNG ---
async def trigger_refresh(request):
    await refresh_catalog()
    return web.Response(text="Updated", headers=cors_headers())

# --- API: STREAM VIDEO ---
async def stream_handler(request):
    try:
        # Xử lý Preflight Request (Cho phép trình duyệt hỏi đường)
        if request.method == 'OPTIONS':
            return web.Response(headers=cors_headers())

        message_id = int(request.match_info['message_id'])
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg or (not msg.video and not msg.document):
            return web.Response(status=404, text="Not Found", headers=cors_headers())

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
        headers = cors_headers()
        headers.update({
            'Content-Type': mime,
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': 'inline',
        })

        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)
        async for chunk in app.stream_media(msg, offset=from_bytes, limit=length):
            await resp.write(chunk)
        return resp
    except:
        return web.Response(status=500, headers=cors_headers())

# --- FIX LỖI MẤT TRÍ NHỚ & KHỞI ĐỘNG ---
async def on_startup():
    print("🚀 Đang khởi động...")
    try:
        await app.start()
        # Gửi tin nhắn mồi để Telegram đồng bộ kênh
        m = await app.send_message(CHANNEL_ID, "Server Online!")
        await m.delete()
        print("✅ Bot đã kết nối Kênh thành công!")
        # Quét phim ngay khi mở
        await refresh_catalog()
    except Exception as e:
        print(f"❌ LỖI KHỞI ĐỘNG: {e}")

if __name__ == '__main__':
    # Chạy quy trình khởi động
    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup())
    
    # Chạy Web Server
    app_routes = [
        web.get('/', lambda r: web.Response(text="Server OK", headers=cors_headers())),
        web.get('/api/catalog', get_catalog),
        web.get('/api/refresh', trigger_refresh),
        web.get('/watch/{message_id}', stream_handler),
        web.options('/watch/{message_id}', stream_handler) # Quan trọng cho CORS
    ]
    
    port = int(os.environ.get("PORT", 8080))
    server = web.Application()
    server.add_routes(app_routes)
    web.run_app(server, port=port)

