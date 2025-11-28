import os
import asyncio
import traceback
from aiohttp import web
from pyrogram import Client

# ================= CẤU HÌNH =================
API_ID = 30786494               # THAY CỦA BẠN
API_HASH = "1b3896cea49b4aa6a5d4061f71d74897" # THAY CỦA BẠN
BOT_TOKEN = "8578661013:AAHd_0zxURy-3LU20GXa9odpehNrw0qXWiU" # THAY CỦA BẠN
CHANNEL_ID = "hazufilm"      # THAY ID KÊNH (-100...)
# ============================================
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

# --- QUÉT PHIM (CHẾ ĐỘ PUBLIC - SIÊU ỔN ĐỊNH) ---
async def refresh_catalog():
    global MOVIE_CATALOG
    print(f"🔄 Đang quét kênh Public: @{CHANNEL_ID}...")
    temp = {}
    count = 0
    try:
        # Kênh Public đọc cực nhanh và không bao giờ lỗi ID
        async for msg in app.get_chat_history(CHANNEL_ID, limit=100):
            if msg.video or msg.document:
                count += 1
                # Lấy tên file
                fname = msg.video.file_name if msg.video else (msg.document.file_name or msg.caption or "NoName")
                
                # Logic xử lý tên đơn giản: Lấy hết
                base_name = os.path.splitext(fname)[0]
                if " - " in base_name:
                    try:
                        name, ep = base_name.rsplit(" - ", 1)
                        name = name.strip()
                        ep = ep.strip()
                    except:
                        name, ep = base_name, "Full"
                else:
                    name, ep = base_name, "Full"
                
                if name not in temp: temp[name] = {}
                temp[name][ep] = msg.id
                
        MOVIE_CATALOG = temp
        print(f"✅ HOÀN TẤT: Tìm thấy {count} file -> {len(MOVIE_CATALOG)} phim.")
    except Exception as e:
        print(f"❌ LỖI: {e}")

# --- API HANDLERS ---
async def get_catalog(request):
    if not MOVIE_CATALOG: await refresh_catalog()
    return web.json_response(MOVIE_CATALOG)

async def trigger_refresh(request):
    await refresh_catalog()
    return web.Response(text="Đang cập nhật...")

async def stream_handler(request):
    try:
        # Lấy ID tin nhắn
        msg_id = int(request.match_info['id'])
        
        # Lấy tin nhắn từ kênh Public
        msg = await app.get_messages(CHANNEL_ID, msg_id)
        
        if not msg: return web.Response(status=404, text="Not Found")

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
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Content-Disposition': 'inline',
            'Accept-Ranges': 'bytes'
        }
        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)
        async for chunk in app.stream_media(msg, offset=from_bytes, limit=length):
            await resp.write(chunk)
        return resp
    except: return web.Response(status=500)

# --- STARTUP ---
async def on_startup():
    print("🚀 Server Public đang khởi động...")
    await app.start()
    await refresh_catalog()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup())
    
    server = web.Application(middlewares=[cors_middleware])
    server.add_routes([
        web.get('/', lambda r: web.Response(text="Server Public OK")),
        web.get('/api/catalog', get_catalog),
        web.get('/api/refresh', trigger_refresh),
        web.get('/watch/{id}', stream_handler)
    ])
    
    port = int(os.environ.get("PORT", 8080))
    web.run_app(server, port=port)
