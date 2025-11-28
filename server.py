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

# --- [QUAN TRỌNG] ĐIỀN LINK MỜI VÀO ĐÂY ---
# Link có dạng: https://t.me/+AbCdEfGhIjK...
PRIVATE_LINK = "https://t.me/+xxxxxxxxxxxxxx" 
# ====================================================

# Khởi tạo Bot
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

# --- HÀM KẾT NỐI KÊNH (BÍ KÍP CHỮA MẤT TRÍ NHỚ) ---
async def fix_channel_access():
    print("🔄 Đang dùng Link Mời để tìm kênh...")
    try:
        # Bot sẽ dùng Link Mời để "nhìn thấy" kênh -> Tự động lưu Access Hash
        chat = await app.get_chat(PRIVATE_LINK)
        print(f"✅ KẾT NỐI THÀNH CÔNG: {chat.title}")
        print(f"ℹ️ ID Kênh thực tế: {chat.id}")
        
        # Nếu ID trong code khác ID thực tế, cảnh báo ngay
        if chat.id != CHANNEL_ID:
            print(f"⚠️ CẢNH BÁO: CHANNEL_ID bạn điền ({CHANNEL_ID}) khác với ID thực tế ({chat.id}). Hãy sửa lại code!")
    except Exception as e:
        print(f"❌ Vẫn lỗi kết nối: {e}")
        print("👉 Kiểm tra lại: PRIVATE_LINK đã đúng chưa? Bot đã vào kênh chưa?")

# --- QUÉT PHIM ---
async def refresh_catalog():
    global MOVIE_CATALOG
    print("🔄 Đang quét phim...")
    temp = {}
    try:
        # Lúc này Bot đã có Access Hash từ hàm fix_channel_access, nên lệnh này sẽ chạy ngon
        async for msg in app.get_chat_history(CHANNEL_ID, limit=200):
            if msg.video or msg.document:
                fname = msg.video.file_name if msg.video else (msg.document.file_name or msg.caption or "NoName")
                try:
                    clean_name = os.path.splitext(fname)[0]
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
        print(f"❌ Lỗi quét phim (Sau khi kết nối): {e}")

# --- API HANDLERS ---
async def get_catalog(request):
    if not MOVIE_CATALOG: await refresh_catalog()
    return web.json_response(MOVIE_CATALOG)

async def trigger_refresh(request):
    await refresh_catalog()
    return web.Response(text="Updated")

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
    except Exception as e:
        return web.Response(status=500, text="Server Error")

# --- MAIN ---
async def on_startup():
    print("🚀 Đang khởi động...")
    await app.start()
    await fix_channel_access() # Chạy hàm kết nối bằng Link
    await refresh_catalog()

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
