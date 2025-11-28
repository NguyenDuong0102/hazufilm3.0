import os
import re
import asyncio
from aiohttp import web
from pyrogram import Client
import traceback

# --- CẤU HÌNH ---
API_ID = 30786494              
API_HASH = "1b3896cea49b4aa6a5d4061f71d74897"     
BOT_TOKEN = "8578661013:AAHd_0zxURy-3LU20GXa9odpehNrw0qXWiU"   # THAY CỦA BẠN
CHANNEL_ID = -1003484849978     # THAY ID KÊNH CỦA BẠN
# ----------------

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# Bộ nhớ đệm chứa danh sách phim
# Cấu trúc: { "Tên Phim": { "1": msg_id, "2": msg_id } }
MOVIE_CATALOG = {}

# --- HÀM 1: QUÉT VÀ CẬP NHẬT PHIM TỪ TELEGRAM ---
async def refresh_catalog():
    global MOVIE_CATALOG
    print("🔄 Đang quét kênh Telegram để tìm phim mới...")
    temp_catalog = {}
    
    # Quét lịch sử kênh (Lấy 1000 tin nhắn gần nhất)
    async for msg in app.get_chat_history(CHANNEL_ID, limit=1000):
        if msg.video or msg.document:
            # Ưu tiên lấy tên file gốc
            file_name = msg.video.file_name if msg.video else msg.document.file_name
            if not file_name: 
                # Nếu không có tên file, lấy caption hoặc bỏ qua
                file_name = msg.caption if msg.caption else "Unknown"

            # Xử lý tên file: "Naruto - Tập 1.mp4" -> Tên: Naruto, Tập: 1
            # Quy tắc regex: Tách bằng dấu gạch ngang (-)
            try:
                # Bỏ đuôi file (.mp4, .mkv)
                clean_name = os.path.splitext(file_name)[0]
                
                if " - " in clean_name:
                    name_part, ep_part = clean_name.rsplit(" - ", 1)
                    movie_name = name_part.strip()
                    episode = ep_part.strip().replace("Tap", "").replace("Tập", "").strip()
                else:
                    movie_name = clean_name
                    episode = "Full"

                if movie_name not in temp_catalog:
                    temp_catalog[movie_name] = {}
                
                # Lưu ID tin nhắn ứng với tập
                temp_catalog[movie_name][episode] = msg.id
                
            except Exception as e:
                print(f"Bỏ qua file {file_name}: Lỗi định dạng")

    MOVIE_CATALOG = temp_catalog
    print(f"✅ Đã cập nhật: {len(MOVIE_CATALOG)} bộ phim.")

# --- API: TRẢ DANH SÁCH PHIM CHO WEB ---
async def get_catalog_api(request):
    # Nếu chưa có dữ liệu thì quét lần đầu
    if not MOVIE_CATALOG:
        await refresh_catalog()
    
    headers = {'Access-Control-Allow-Origin': '*'}
    return web.json_response(MOVIE_CATALOG, headers=headers)

# --- API: BẤM NÚT ĐỂ UPDATE PHIM MỚI ---
async def trigger_refresh(request):
    await refresh_catalog()
    return web.Response(text="Đã cập nhật xong!", headers={'Access-Control-Allow-Origin': '*'})

# --- HÀM STREAM (GIỮ NGUYÊN NHƯ CŨ) ---
async def stream_handler(request):
    try:
        # Lấy ID từ URL
        message_id = int(request.match_info['message_id'])
        print(f"--> Đang yêu cầu lấy tin nhắn ID: {message_id}") # Log kiểm tra
        
        # Lấy tin nhắn từ Kênh
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        # Kiểm tra xem có tìm thấy tin nhắn không
        if msg is None or msg.empty:
            print(f"❌ LỖI: Không tìm thấy tin nhắn ID {message_id} trong kênh {CHANNEL_ID}")
            return web.Response(text="Lỗi: Không tìm thấy tin nhắn này trong kênh (Sai ID hoặc Bot chưa vào kênh)", status=404)

        # Kiểm tra xem tin nhắn có phải video/tài liệu không
        if not msg.video and not msg.document:
            print(f"❌ LỖI: Tin nhắn ID {message_id} tìm thấy nhưng KHÔNG PHẢI VIDEO (Nó là text hoặc ảnh)")
            return web.Response(text="Lỗi: Tin nhắn này không phải là Video", status=404)

        # Lấy thông tin file
        file_size = msg.video.file_size if msg.video else msg.document.file_size
        mime_type = msg.video.mime_type if msg.video else msg.document.mime_type
        
        # Xử lý tua (Range)
        range_header = request.headers.get('Range', 0)
        from_bytes, until_bytes = 0, file_size - 1
        
        if range_header:
            try:
                range_str = range_header.replace('bytes=', '')
                parts = range_str.split('-')
                from_bytes = int(parts[0])
                if parts[1]: until_bytes = int(parts[1])
            except: pass

        content_length = until_bytes - from_bytes + 1
        
        headers = {
            'Content-Type': mime_type,
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {from_bytes}-{until_bytes}/{file_size}',
            'Content-Length': str(content_length),
            'Content-Disposition': 'inline',
            'Access-Control-Allow-Origin': '*' 
        }

        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)

        async for chunk in app.stream_media(msg, offset=from_bytes, limit=content_length):
            await resp.write(chunk)
            
        return resp

    except Exception as e:
        # IN LỖI CHI TIẾT RA MÀN HÌNH ĐEN
        print("================ CÓ LỖI XẢY RA ================")
        traceback.print_exc() 
        print("===============================================")
        return web.Response(text=f"Lỗi Server: {str(e)}", status=500)
    
async def health_check(request): return web.Response(text="Server OK")

app_routes = [
    web.get('/', health_check),
    web.get('/api/catalog', get_catalog_api),      # API lấy danh sách phim
    web.get('/api/refresh', trigger_refresh),      # API làm mới danh sách
    web.get('/watch/{message_id}', stream_handler) # API xem phim
]

# ... (Phần trên giữ nguyên) ...

# ... (Phần trên giữ nguyên) ...

# Hàm này giúp Bot "học thuộc lòng" danh sách nhóm khi mới ngủ dậy
async def force_connect_channel():
    print("🔄 Đang quét danh sách các nhóm Bot đang tham gia...")
    found = False
    # Lấy danh sách tất cả các nhóm/kênh mà Bot đang ở trong đó
    async for dialog in app.get_dialogs():
        if dialog.chat.id == CHANNEL_ID:
            found = True
            print(f"✅ Đã tìm thấy Kênh mục tiêu: {dialog.chat.title} (ID: {dialog.chat.id})")
            # Khi tìm thấy, Pyrogram sẽ tự động lưu Access Hash vào bộ nhớ
            break
    
    if not found:
        print(f"⚠️ CẢNH BÁO: Bot đã quét hết danh bạ nhưng KHÔNG THẤY kênh {CHANNEL_ID}!")
        print("👉 Hãy kiểm tra: 1. Bot đã vào kênh chưa? 2. ID trong code có đúng 100% không?")

if __name__ == '__main__':
    print("🚀 Đang khởi động Bot...")
    app.start()
    
    # --- CHẠY THỦ THUẬT QUÉT DANH BẠ ---
    # Dùng loop của client để chạy hàm async
    app.loop.run_until_complete(force_connect_channel())
    # -----------------------------------
    
    print("🌐 Đang khởi động Web Server...")
    port = int(os.environ.get("PORT", 8080))
    
    server = web.Application()
    server.add_routes(routes)
    web.run_app(server, port=port)
