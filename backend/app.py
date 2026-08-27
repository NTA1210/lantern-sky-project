import asyncio
from io import BytesIO
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException,Request,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image,UnidentifiedImageError
from . import config
from .scanner import ScannerService
from .processor import ScanError
scanner=ScannerService()
class Manager:
    def __init__(self):self.connections=set()
    async def connect(self,ws):await ws.accept(); self.connections.add(ws)
    def disconnect(self,ws):self.connections.discard(ws)
    async def broadcast(self,payload):
        dead=[]
        for ws in list(self.connections):
            try:await ws.send_json(payload)
            except Exception:dead.append(ws)
        for ws in dead:self.disconnect(ws)
manager=Manager()
@asynccontextmanager
async def lifespan(app): scanner.start(); yield; scanner.stop()
app=FastAPI(title='Lantern Sky',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=str(config.FRONTEND_DIR)),name='static'); app.mount('/generated',StaticFiles(directory=str(config.GENERATED_DIR)),name='generated')
@app.get('/')
def home():return FileResponse(config.FRONTEND_DIR/'control.html')
@app.get('/control')
def control():return FileResponse(config.FRONTEND_DIR/'control.html')
@app.get('/display')
def display():return FileResponse(config.FRONTEND_DIR/'display.html')
@app.get('/api/status')
def status():
    s=scanner.get_status(); return {'cameraOpen':s.camera_open,'resolution':[s.width,s.height],'fps':s.fps,'markerIds':s.marker_ids,'readyToScan':s.ready_to_scan,'error':s.error}
@app.get('/api/camera/stream')
def stream():return StreamingResponse(scanner.mjpeg_generator(),media_type='multipart/x-mixed-replace; boundary=frame',headers={'Cache-Control':'no-store'})
@app.post('/api/scan')
async def scan():
    try:r=await asyncio.to_thread(scanner.capture_and_process)
    except ScanError as e:raise HTTPException(422,detail=str(e)) from e
    except Exception as e:raise HTTPException(500,detail=f'Scan failed: {e}') from e
    url=f'/generated/lanterns/{r.lantern_path.name}'; await manager.broadcast({'type':'lantern_created','id':r.id,'url':url})
    return {'ok':True,'id':r.id,'lanternUrl':url,'correctedUrl':f'/generated/corrected/{r.corrected_path.name}','markerIds':r.marker_ids,'canonicalSize':list(r.canonical_size)}
@app.post('/api/demo')
async def demo(): await manager.broadcast({'type':'lantern_created','id':'demo','url':'/static/sample_lantern.png','demo':True}); return {'ok':True}
@app.post('/api/background')
async def background(request:Request):
    data=await request.body()
    if not data:raise HTTPException(400,detail='Chưa chọn file ảnh.')
    if len(data)>20*1024*1024:raise HTTPException(413,detail='Ảnh quá lớn. Vui lòng chọn ảnh dưới 20MB.')
    try:
        with Image.open(BytesIO(data)) as img:
            fmt=(img.format or '').lower()
            img.verify()
    except (UnidentifiedImageError,OSError) as e:
        raise HTTPException(400,detail='File này không phải ảnh hợp lệ.') from e
    ext={'jpeg':'jpg','jpg':'jpg','png':'png','webp':'webp'}.get(fmt)
    if ext is None:raise HTTPException(400,detail='Chỉ hỗ trợ JPG, PNG hoặc WEBP.')
    for old in config.FRONTEND_DIR.glob('display_background.*'):
        if old.suffix.lower() in {'.jpg','.jpeg','.png','.webp'}:old.unlink(missing_ok=True)
    path=config.FRONTEND_DIR/f'display_background.{ext}'
    path.write_bytes(data)
    url=f'/static/{path.name}?v={int(path.stat().st_mtime)}'
    await manager.broadcast({'type':'background_changed','url':url})
    return {'ok':True,'url':url}
@app.get('/api/recent')
def recent(limit:int=12):
    limit=max(0,min(limit,config.MAX_RECENT_LANTERNS)); fs=sorted(config.LANTERNS_DIR.glob('*.png'),key=lambda p:p.stat().st_mtime,reverse=True)[:limit]; fs.reverse(); return [{'id':p.stem,'url':f'/generated/lanterns/{p.name}'} for p in fs]
@app.websocket('/ws')
async def ws_endpoint(ws:WebSocket):
    await manager.connect(ws)
    try:
        while True:await ws.receive_text()
    except (WebSocketDisconnect,Exception):manager.disconnect(ws)
