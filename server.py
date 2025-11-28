import os
import asyncio
from aiohttp import web
from pyrogram import Client, enums

# ================= CẤU HÌNH =================
API_ID = 30786494                # API ID CỦA BẠN
API_HASH = "1b3896cea49b4aa6a5d4061f71d74897" # API HASH CỦA BẠN
BOT_TOKEN = "8578661013:AAHd_0zxURy-3LU20GXa9odpehNrw0qXWiU" # TOKEN CỦA BẠN

# --- QUAN TRỌNG: CẤU HÌNH KÊNH PRIVATE ---
# Thay "hazufilm" bằng ID số của kênh Private (Bắt buộc có -100 ở đầu)
# Ví dụ: CHANNEL_ID = -1001234567890
CHANNEL_ID = -1003484849978
# ============================================

# Khởi tạo Client
app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)
MOVIE_CATALOG = {} 

# --- MIDDLEWARE CORS (Để web khác gọi vào không bị chặn) ---
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

# --- QUÉT PHIM TỪ KÊNH ---
async def refresh_catalog():
    global MOVIE_CATALOG
    # Chuyển ID sang int để đảm bảo Pyrogram hiểu đúng ID kênh Private
    try:
        target_chat_id = int(CHANNEL_ID)
    except ValueError:
        target_chat_id = CHANNEL_ID # Fallback nếu user nhập string username

    print(f"\n🔄 BẮT ĐẦU QUÉT KÊNH ID: {target_chat_id}...")
    
    temp = {}
    count_video = 0
    count_total = 0
    
    try:
        # Lấy thông tin chat để kiểm tra quyền truy cập
        chat = await app.get_chat(target_chat_id)
        print(f"✅ Đã kết nối tới kênh: {chat.title} (ID: {chat.id})")

        # limit=0 nghĩa là lấy TẤT CẢ (cẩn thận nếu kênh có hàng nghìn tin nhắn thì set 500-1000 thôi)
        async for msg in app.get_chat_history(chat.id, limit=500):
            count_total += 1
            
            # Chỉ xử lý tin nhắn có Video hoặc Document (định dạng video file)
            media = msg.video or msg.document
            if media:
                # Logic lấy tên file an toàn hơn
                file_name = getattr(media, "file_name", None)
                
                # Nếu không có tên file, dùng Caption. Nếu không có Caption, dùng ID tin nhắn
                if not file_name:
                    caption = msg.caption or ""
                    # Lấy dòng đầu tiên của caption làm tên
                    file_name = caption.split('\n')[0].strip() if caption else f"Video_{msg.id}.mp4"

                # Lọc chỉ lấy file đuôi video phổ biến
                if not any(file_name.lower().endswith(ext) for ext in ['.mp4', '.mkv', '.avi']):
                    # Nếu file document mà không có đuôi, bỏ qua hoặc xử lý tùy ý
                    if not msg.video: continue 

                count_video += 1
                
                # Xử lý tên hiển thị (Bỏ đuôi file)
                base_name = os.path.splitext(file_name)[0]
                
                # Giả lập cấu trúc: Tên Phim - Tập
                # Ví dụ: "Naruto - Tập 1.mp4" -> Phim: Naruto, Tập: Tập 1
                if " - " in base_name:
                    parts = base_name.rsplit(" - ", 1)
                    title = parts[0].strip()
                    episode = parts[1].strip()
                else:
                    title = base_name
                    episode = "Full"

                if title not in temp: temp[title] = {}
                
                # Lưu thông tin: ID tin nhắn, File Size, Poster (nếu có thumbnail)
                temp[title][episode] = {
                    "msg_id": msg.id,
                    "size": media.file_size,
                    "mime": media.mime_type
                }
                
                print(f"   --> Tìm thấy: {title} [{episode}] (ID: {msg.id})")
        
        MOVIE_CATALOG = temp
        print(f"\n✅ QUÉT XONG! Tổng tin nhắn: {count_total} | Tổng video: {count_video}")
        print(f"🎥 Danh sách phim: {list(MOVIE_CATALOG.keys())}")
        
    except Exception as e:
        print(f"\n❌ LỖI NGHIÊM TRỌNG KHI QUÉT: {e}")
        print("💡 Gợi ý: Kiểm tra xem Bot đã được thêm vào kênh Private và set làm Admin chưa?")
        import traceback
        traceback.print_exc()

# --- API HANDLERS ---
async def get_catalog(request):
    if not MOVIE_CATALOG:
        await refresh_catalog()
    return web.json_response(MOVIE_CATALOG)

async def trigger_refresh(request):
    # Chạy background task để không treo web
    asyncio.create_task(refresh_catalog())
    return web.Response(text="Đã kích hoạt lệnh làm mới danh sách phim.")

async def stream_handler(request):
    try:
        msg_id = int(request.match_info['id'])
        print(f"📺 Request Stream MSG ID: {msg_id}")
        
        # Đảm bảo target_chat_id đúng kiểu dữ liệu
        try:
            target_chat_id = int(CHANNEL_ID)
        except:
            target_chat_id = CHANNEL_ID

        # Lấy tin nhắn
        msg = await app.get_messages(target_chat_id, msg_id)
        
        if not msg or (not msg.video and not msg.document):
            return web.Response(status=404, text="Video Not Found on Telegram")

        media = msg.video or msg.document
        file_size = media.file_size
        mime = media.mime_type or "video/mp4"
        
        # Xử lý Range Header (Tua video)
        range_header = request.headers.get('Range', None)
        from_bytes = 0
        until_bytes = file_size - 1
        
        if range_header:
            try:
                parts = range_header.replace('bytes=', '').split('-')
                from_bytes = int(parts[0])
                if len(parts) > 1 and parts[1]:
                    until_bytes = int(parts[1])
            except:
                pass
        
        length = until_bytes - from_bytes + 1
        
        headers = {
            'Content-Type': mime,
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(length),
            'Accept-Ranges': 'bytes',
            'Content-Disposition': f'inline; filename="video_{msg_id}.mp4"'
        }
        
        status_code = 206 if range_header else 200
        response = web.StreamResponse(status=status_code, headers=headers)
        await response.prepare(request)
        
        # Pyrogram Streaming
        try:
            # chunk_size nhỏ giúp tua mượt hơn
            async for chunk in app.stream_media(msg, offset=from_bytes, limit=length):
                await response.write(chunk)
        except Exception as e:
            # Client ngắt kết nối khi đang xem là bình thường
            pass
            
        return response

    except Exception as e:
        print(f"❌ Stream Error: {e}")
        return web.Response(status=500, text="Internal Server Error")

# --- STARTUP ---
async def on_startup():
    print("🚀 Server đang khởi động...")
    await app.start()
    print("🤖 Bot đã đăng nhập thành công!")
    # Tự động quét khi mở server
    await refresh_catalog()

if __name__ == '__main__':
    # Fix lỗi loop trên Windows nếu có
    try:
        import uvloop
        uvloop.install()
    except:
        pass

    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup())
    
    server = web.Application(middlewares=[cors_middleware])
    server.add_routes([
        web.get('/', lambda r: web.Response(text=f"Server đang chạy. Đã load {len(MOVIE_CATALOG)} phim.")),
        web.get('/api/catalog', get_catalog),
        web.get('/api/refresh', trigger_refresh),
        web.get('/watch/{id}', stream_handler)
    ])
    
    # Render thường cấp port qua biến môi trường
    port = int(os.environ.get("PORT", 8080))
    print(f"🌍 Web server running on port {port}")
    web.run_app(server, port=port)
