from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
import cv2,numpy as np
from PIL import Image
from backend.layout import marker_boxes,lantern_roi,create_lantern_mask
PAGE_W,PAGE_H=2480,3508; OUT=ROOT/'print'/'lantern_template.png'
def main():
    page=np.full((PAGE_H,PAGE_W,3),255,np.uint8); d=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for mid,(x,y,s) in marker_boxes(PAGE_W,PAGE_H).items():
        m=cv2.aruco.generateImageMarker(d,mid,s); page[y:y+s,x:x+s]=cv2.cvtColor(m,cv2.COLOR_GRAY2BGR)
    cv2.putText(page,'LANTERN SKY - DRAWING TEMPLATE',(round(PAGE_W*.22),round(PAGE_H*.16)),cv2.FONT_HERSHEY_SIMPLEX,1.7,(45,45,45),4,cv2.LINE_AA)
    cv2.putText(page,'Draw inside the lantern. Keep all four markers visible.',(round(PAGE_W*.23),round(PAGE_H*.19)),cv2.FONT_HERSHEY_SIMPLEX,.82,(110,110,110),2,cv2.LINE_AA)
    x1,y1,x2,y2=lantern_roi(PAGE_W,PAGE_H); mask=create_lantern_mask(x2-x1,y2-y1,1); cs,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE); shifted=[]
    for c in cs:c=c.copy();c[:,:,0]+=x1;c[:,:,1]+=y1;shifted.append(c)
    cv2.drawContours(page,shifted,-1,(200,200,200),6,cv2.LINE_AA); rgb=cv2.cvtColor(page,cv2.COLOR_BGR2RGB); Image.fromarray(rgb).save(OUT,dpi=(300,300),optimize=True); print('Created:',OUT)
if __name__=='__main__':main()
