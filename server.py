import os
import asyncio
import re  # <--- Thư viện xử lý chuỗi thông minh
from aiohttp import web
from pyrogram import Client

# ================= CẤU HÌNH =================
API_ID = 30786494               # THAY CỦA BẠN
API_HASH = "1b3896cea49b4aa6a5d4061f71d74897" # THAY CỦA BẠN
BOT_TOKEN = "8578661013:AAHd_0zxURy-3LU20GXa9odpehNrw0qXWiU" # THAY CỦA BẠN
CHANNEL_ID = -1003484849978      # THAY ID KÊNH (-100...)
# ============================================

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
MOVIE_CATALOG = {} 

# --- MIDDLEWARE CORS (GIỮ NGUYÊN) ---
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

# --- [LOGIC MỚI] XỬ LÝ TÊN THÔNG MINH ---
def smart_parse_name(filename):
    # Bỏ đuôi file
    base_name = os.path.splitext(filename)[0]
    
    # 1. Ưu tiên: Tách bằng dấu gạch ngang " - " (Chuẩn nhất)
    if " - " in base_name:
        name, ep = base_name.rsplit(" - ", 1)
        return name.strip(), ep.strip().replace("Tập", "").replace("Tap", "").replace("Ep", "").strip()

    # 2. Regex: Tìm các từ khóa Tập/Tap/Ep/Part + Số (Ví dụ: "Phim A Tap 1")
    # Pattern giải thích: (Tên phim) (Khoảng cách) (Từ khóa) (Số tập)
    match = re.search(r'(.+?)(?:\s+|_|\.)(?:Tập|Tap|Ep|Episode|Part|E)\s*(\d+)', base_name, re.IGNORECASE)
    if match:
        name = match.group(1).replace(".", " ").strip()
        ep = match.group(2).strip()
        return name, ep

    # 3. Regex: Tìm số ở cuối cùng (Ví dụ: "Phim A 01")
    match_number = re.search(r'(.+?)\s+(\d+)$', base_name)
    if match_number:
        name = match_number.group(1).strip()
        ep = match_number.group(2).strip()
        return name, ep
        
    # 4. Nếu không khớp gì cả -> Coi là phim lẻ
    return base_name.strip(), "Full"

# --- HÀM QUÉT PHIM (UNLIMITED & SMART) ---
async def refresh_catalog():
    global MOVIE_CATALOG
    print("🔄 ĐANG QUÉT TOÀN BỘ KÊNH (UNLIMITED)...")
    temp = {}
    count_msg = 0
    
    try:
        # limit=0 nghĩa là lấy KHÔNG GIỚI HẠN (toàn bộ lịch sử)
        async for msg in app.get_chat_history(CHANNEL_ID, limit=0):
            count_msg += 1
            
            if msg.video or msg.document:
                # Lấy tên file
                fname = msg.video.file_name if msg.video else (msg.document.file_name or msg.caption or "NoName")
                
                # Bỏ qua nếu không có tên file
                if fname == "NoName": continue

                # Dùng hàm xử lý thông minh ở trên
                name, ep = smart_parse_name(fname)
                
                # Gom nhóm
                if name not in temp: temp[name] = {}
                
                # Nếu đã có tập này rồi thì bỏ qua (Tránh trùng lặp)
                if ep not in temp[name]:
                    temp[name][ep] = msg.id
            
            # Log nhẹ mỗi 100 tin nhắn để biết Bot vẫn đang chạy
            if count_msg % 100 == 0:
                print(f"   --> Đã quét {count_msg} tin nhắn...")

        MOVIE_CATALOG = temp
        print(f"🏁 HOÀN TẤT: Quét {count_msg} tin nhắn. Tìm thấy {len(MOVIE_CATALOG)} bộ phim.")
        
    except Exception as e:
        print(f"❌ Lỗi quét phim: {e}")

# --- CÁC HÀM API & STREAM (GIỮ NGUYÊN) ---
async def get_catalog(request):
    if not MOVIE_CATALOG: await refresh_catalog()
    return web.json_response(MOVIE_CATALOG)

async def trigger_refresh(request):
    # Chạy ngầm (background) để không làm đơ web nếu quét lâu
    asyncio.create_task(refresh_catalog()) 
    return web.Response(text="Đang bắt đầu quét toàn bộ kênh! Hãy đợi vài phút rồi F5 trang web.")

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

# --- STARTUP ---
async def on_startup():
    print("🚀 Đang khởi động...")
    await app.start()
    
    # Gửi tin mồi để đảm bảo kết nối
    try:
        m = await app.send_message(CHANNEL_ID, "Scan Started!")
        await m.delete()
    except: pass

    # Quét phim ngay khi mở
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
