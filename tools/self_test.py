from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
import cv2,numpy as np
from backend import config
from backend.layout import marker_boxes,lantern_roi
from backend.processor import LanternProcessor
OUT=ROOT/'self_test_output';OUT.mkdir(exist_ok=True)
def canonical():
    w,h=config.CANONICAL_WIDTH,config.CANONICAL_HEIGHT;p=np.full((h,w,3),255,np.uint8);d=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for mid,(x,y,s) in marker_boxes(w,h).items():m=cv2.aruco.generateImageMarker(d,mid,s);p[y:y+s,x:x+s]=cv2.cvtColor(m,cv2.COLOR_GRAY2BGR)
    x1,y1,x2,y2=lantern_roi(w,h);rw,rh=x2-x1,y2-y1;art=np.full((rh,rw,3),248,np.uint8)
    for i in range(12):cv2.circle(art,(int(rw*(.12+(i%4)*.25)),int(rh*(.14+(i//4)*.28))),max(12,rw//16),(40+(i*47)%190,50+(i*71)%190,60+(i*91)%190),-1,cv2.LINE_AA)
    cv2.putText(art,'MY LANTERN',(rw//8,rh//2),cv2.FONT_HERSHEY_SIMPLEX,1,(20,20,20),3,cv2.LINE_AA);p[y1:y2,x1:x2]=art;return p
def camera(page):
    h,w=page.shape[:2];cw,ch=1920,1080;out=np.full((ch,cw,3),60,np.uint8);src=np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]]);dst=np.float32([[610,70],[1370,110],[1450,1010],[500,960]]);H=cv2.getPerspectiveTransform(src,dst);warped=cv2.warpPerspective(page,H,(cw,ch),borderValue=(60,60,60));mask=cv2.warpPerspective(np.full((h,w),255,np.uint8),H,(cw,ch));out[mask>0]=warped[mask>0];return out
def main():
    p=canonical();f=camera(p);proc=LanternProcessor();det=proc.detect(f)
    if not set(config.REQUIRED_MARKER_IDS).issubset(det):raise RuntimeError(f'Marker detection failed: {sorted(det)}')
    r=proc.rectify(f,det);l=proc.extract_lantern(r);cv2.imwrite(str(OUT/'01_canonical.png'),p);cv2.imwrite(str(OUT/'02_fake_camera.png'),f);cv2.imwrite(str(OUT/'03_rectified.png'),r);cv2.imwrite(str(OUT/'04_lantern.png'),l);print('SELF TEST PASSED');print('Detected markers:',sorted(det));print('Outputs:',OUT)
if __name__=='__main__':main()
