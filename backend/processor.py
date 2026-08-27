from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import cv2, numpy as np
from . import config
from .layout import expected_marker_corners,lantern_roi,create_lantern_mask

class ScanError(RuntimeError): pass
@dataclass
class ProcessResult:
    id:str; original_path:Path; corrected_path:Path; lantern_path:Path; marker_ids:list[int]; canonical_size:tuple[int,int]

class LanternProcessor:
    def __init__(self):
        self.dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        params=cv2.aruco.DetectorParameters(); params.cornerRefinementMethod=cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector=cv2.aruco.ArucoDetector(self.dictionary,params)
    def detect(self,frame):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY); corners,ids,_=self.detector.detectMarkers(gray); found={}
        if ids is not None:
            for c,mid in zip(corners,ids.flatten().tolist()): found[int(mid)]=c.reshape(4,2).astype(np.float32)
        return found
    def rectify(self,frame,detected):
        missing=[m for m in config.REQUIRED_MARKER_IDS if m not in detected]
        if missing: raise ScanError('Không thấy đủ 4 marker. Thiếu: '+','.join(map(str,missing)))
        w,h=config.CANONICAL_WIDTH,config.CANONICAL_HEIGHT; expected=expected_marker_corners(w,h)
        src=[]; dst=[]
        for mid in config.REQUIRED_MARKER_IDS: src+=detected[mid].tolist(); dst+=expected[mid].tolist()
        H,_=cv2.findHomography(np.asarray(src,np.float32),np.asarray(dst,np.float32),cv2.RANSAC,3.0)
        if H is None: raise ScanError('Không tính được perspective transform.')
        return cv2.warpPerspective(frame,H,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT,borderValue=(255,255,255))
    @staticmethod
    def gentle_white_balance(img):
        h,w=img.shape[:2]; patch=img[round(h*.055):round(h*.115),round(w*.34):round(w*.66)]
        if not patch.size: return img
        bright=np.min(patch,axis=2)>150
        if np.count_nonzero(bright)<100: return img
        means=patch[bright].astype(np.float32).mean(axis=0); gains=np.clip(242.0/np.maximum(means,1),.86,1.18)
        return np.clip(img.astype(np.float32)*gains.reshape(1,1,3),0,255).astype(np.uint8)
    @staticmethod
    def extract_lantern(rectified):
        h,w=rectified.shape[:2]; x1,y1,x2,y2=lantern_roi(w,h); crop=rectified[y1:y2,x1:x2].copy(); alpha=create_lantern_mask(crop.shape[1],crop.shape[0],4)
        out=cv2.cvtColor(crop,cv2.COLOR_BGR2BGRA); out[:,:,3]=alpha; out[alpha==0,0:3]=255
        return out
    def process(self,frame):
        det=self.detect(frame); rect=self.gentle_white_balance(self.rectify(frame,det)); lantern=self.extract_lantern(rect)
        scan_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:8]
        op=config.ORIGINAL_DIR/f'{scan_id}.jpg'; cp=config.CORRECTED_DIR/f'{scan_id}.png'; lp=config.LANTERNS_DIR/f'{scan_id}.png'
        cv2.imwrite(str(op),frame,[cv2.IMWRITE_JPEG_QUALITY,config.JPEG_MASTER_QUALITY]); cv2.imwrite(str(cp),rect,[cv2.IMWRITE_PNG_COMPRESSION,config.PNG_COMPRESSION]); cv2.imwrite(str(lp),lantern,[cv2.IMWRITE_PNG_COMPRESSION,config.PNG_COMPRESSION])
        return ProcessResult(scan_id,op,cp,lp,sorted(det), (rect.shape[1],rect.shape[0]))
