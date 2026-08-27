import cv2, numpy as np

def marker_boxes(width:int,height:int):
    side=max(64,round(width*.12)); mx=round(width*.055); my=round(height*.045)
    return {0:(mx,my,side),1:(width-mx-side,my,side),2:(width-mx-side,height-my-side,side),3:(mx,height-my-side,side)}

def expected_marker_corners(width:int,height:int):
    out={}
    for mid,(x,y,s) in marker_boxes(width,height).items():
        out[mid]=np.array([[x,y],[x+s-1,y],[x+s-1,y+s-1],[x,y+s-1]],dtype=np.float32)
    return out

def lantern_roi(width:int,height:int):
    return round(width*.245),round(height*.225),round(width*.755),round(height*.805)

def _poly(width,height):
    p=np.array([[.22,.02],[.78,.02],[.90,.08],[.965,.22],[.99,.45],[.97,.70],[.90,.88],[.78,.98],[.22,.98],[.10,.88],[.03,.70],[.01,.45],[.035,.22],[.10,.08]],dtype=np.float32)
    p[:,0]*=width-1; p[:,1]*=height-1
    return np.round(p).astype(np.int32)

def create_lantern_mask(width:int,height:int,antialias:int=4):
    aa=max(1,antialias); m=np.zeros((height*aa,width*aa),dtype=np.uint8)
    cv2.fillPoly(m,[_poly(width*aa,height*aa)],255,lineType=cv2.LINE_AA)
    if aa>1: m=cv2.resize(m,(width,height),interpolation=cv2.INTER_AREA)
    return m
