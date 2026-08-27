import cv2, numpy as np, platform, threading, time
from dataclasses import dataclass
from . import config
from .processor import LanternProcessor,ScanError
@dataclass
class ScannerStatus:
    camera_open:bool; width:int; height:int; fps:float; marker_ids:list[int]; ready_to_scan:bool; error:str|None
class ScannerService:
    def __init__(self):
        self.processor=LanternProcessor(); self.cap=None; self.thread=None; self.running=False; self.lock=threading.Lock(); self.frame=None; self.preview=None; self.detected={}; self.error=None; self.w=0; self.h=0; self.fps=0
    def _candidates(self):
        s=platform.system(); return ([cv2.CAP_AVFOUNDATION,None] if s=='Darwin' else [cv2.CAP_DSHOW,None] if s=='Windows' else [cv2.CAP_V4L2,None] if s=='Linux' else [None])
    def _open(self):
        for b in self._candidates():
            c=cv2.VideoCapture(config.CAMERA_INDEX) if b is None else cv2.VideoCapture(config.CAMERA_INDEX,b)
            if not c.isOpened(): c.release(); continue
            c.set(cv2.CAP_PROP_FRAME_WIDTH,config.CAMERA_WIDTH); c.set(cv2.CAP_PROP_FRAME_HEIGHT,config.CAMERA_HEIGHT); c.set(cv2.CAP_PROP_FPS,config.CAMERA_FPS)
            for _ in range(6): c.read(); time.sleep(.02)
            return c
        return None
    def start(self):
        if self.running:return
        self.cap=self._open()
        if self.cap is None: self.error='Không mở được camera. Kiểm tra quyền Camera hoặc LANTERN_CAMERA_INDEX.'; return
        self.w=int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0); self.h=int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0); self.fps=float(self.cap.get(cv2.CAP_PROP_FPS) or 0)
        self.running=True; self.thread=threading.Thread(target=self._loop,daemon=True); self.thread.start()
    def stop(self):
        self.running=False
        if self.thread and self.thread.is_alive(): self.thread.join(timeout=1.5)
        if self.cap is not None:self.cap.release()
    def _loop(self):
        while self.running:
            ok,frame=self.cap.read()
            if not ok or frame is None:self.error='Camera không trả frame.'; time.sleep(.1); continue
            try:
                det=self.processor.detect(frame); prev=self._decorate(frame.copy(),det); okj,j=cv2.imencode('.jpg',prev,[cv2.IMWRITE_JPEG_QUALITY,config.JPEG_PREVIEW_QUALITY])
                with self.lock:self.frame=frame; self.detected=det; self.preview=j.tobytes() if okj else None; self.error=None
            except Exception as e:self.error=f'Camera processing error: {e}'
    def _decorate(self,frame,det):
        ready=set(config.REQUIRED_MARKER_IDS).issubset(det); color=(80,220,100) if ready else (40,170,255)
        for mid,pts in det.items():
            poly=np.round(pts).astype(np.int32).reshape((-1,1,2)); cv2.polylines(frame,[poly],True,color,3,cv2.LINE_AA); x,y=np.round(pts[0]).astype(int); cv2.putText(frame,f'ID {mid}',(x,max(30,y-10)),cv2.FONT_HERSHEY_SIMPLEX,.8,color,2,cv2.LINE_AA)
        txt='READY - press Scan' if ready else f'Markers: {sorted(det)} / [0,1,2,3]'; cv2.putText(frame,txt,(30,50),cv2.FONT_HERSHEY_SIMPLEX,1,color,2,cv2.LINE_AA); return frame
    def get_status(self):
        with self.lock: ids=sorted(self.detected)
        return ScannerStatus(self.cap is not None and self.cap.isOpened(),self.w,self.h,self.fps,ids,set(config.REQUIRED_MARKER_IDS).issubset(ids),self.error)
    def capture_and_process(self):
        with self.lock:
            if self.frame is None: raise ScanError('Chưa có frame từ camera.')
            f=self.frame.copy()
        return self.processor.process(f)
    def mjpeg_generator(self):
        while True:
            with self.lock:p=self.preview
            if p: yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+p+b'\r\n'
            time.sleep(1/24)
