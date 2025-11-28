import os
import traceback
from aiohttp import web
from pyrogram import Client

# ==========================================
# KHU VỰC THAY ĐỔI THÔNG TIN CỦA BẠN
# ==========================================
API_ID = 12345678                # Thay bằng số API_ID của bạn
API_HASH = "dien_api_hash_o_day" # Thay bằng API_HASH của bạn
BOT_TOKEN = "dien_bot_token_o_day" # Thay Bot Token của bạn
CHANNEL_ID = -100xxxxxxxxxx      # Thay ID Kênh (Bắt buộc phải có -100 ở đầu)
# ==========================================

# in_memory=True: Không lưu file session, phù hợp chạy trên Render
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        print(f"--> Yêu cầu xem tin nhắn ID: {message_id}")
        
        # Lấy video từ Kênh
        msg = await app.get_messages(CHANNEL_ID, message_id)
        
        if not msg:
            return web.Response(text="Lỗi: Không tìm thấy tin nhắn (ID sai hoặc Bot chưa load được kênh)", status=404)

        if not msg.video and not msg.document:
            return web.Response(text="Lỗi: Đây không phải là file video", status=404)

        # Lấy thông tin file
        file_size = msg.video.file_size if msg.video else msg.document.file_size
        mime_type = msg.video.mime_type if msg.video else msg.document.mime_type
        
        # Xử lý tua video (Range Header)
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
        print("Lỗi Stream:")
        traceback.print_exc()
        return web.Response(text=f"Lỗi Server: {str(e)}", status=500)

async def health_check(request):
    return web.Response(text="Server Phim đang chạy ngon lành!")

# --- HÀM KHẮC PHỤC LỖI MẤT TRÍ NHỚ ---
async def fix_channel_access():
    print(f"🔄 Đang thử kết nối vào kênh ID: {CHANNEL_ID}...")
    try:
        # Cách 1: Thử lấy thông tin Chat trực tiếp
        chat = await app.get_chat(CHANNEL_ID)
        print(f"✅ Đã kết nối thành công: {chat.title}")
    except Exception as e1:
        print(f"⚠️ Cách 1 thất bại ({e1}). Đang thử Cách 2 (Gửi tin nhắn mồi)...")
        try:
            # Cách 2: Gửi 1 tin nhắn vào kênh để ép Telegram cập nhật Cache
            # Lưu ý: Bot phải là Admin mới gửi được tin vào kênh
            sent_msg = await app.send_message(CHANNEL_ID, "🤖 Server khởi động! Đang đồng bộ dữ liệu...")
            # Xóa ngay cho đỡ rác
            await sent_msg.delete() 
            print("✅ Cách 2 thành công! Đã đồng bộ được kênh.")
        except Exception as e2:
            print(f"❌ THẤT BẠI TOÀN TẬP: {e2}")
            print("👉 Kiểm tra lại: 1. ID Kênh có đúng -100... không? 2. Bot đã được set làm ADMIN chưa?")

# Định tuyến
routes = [
    web.get('/watch/{message_id}', stream_handler),
    web.get('/', health_check)
]

if __name__ == '__main__':
    print("🚀 Đang khởi động Bot...")
    app.start()
    
    # Chạy hàm fix lỗi ngay khi khởi động
    app.loop.run_until_complete(fix_channel_access())
    
    print("🌐 Đang khởi động Web Server...")
    port = int(os.environ.get("PORT", 8080))
    server = web.Application()
    server.add_routes(routes)
    web.run_app(server, port=port)
