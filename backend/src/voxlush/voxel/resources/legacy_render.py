"""Two orthographic views rendered exclusively from saved authoritative voxels."""
import json, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

COLORS={'ice':'#9ecae8','stone':'#899098','cobblestone':'#70757a','stone_bricks':'#9a9b9b','bricks':'#a85e49',
 'oak_planks':'#b58b52','oak_log':'#705235','spruce_planks':'#765534','spruce_log':'#513d2c',
 'dark_oak_planks':'#553d2b','dark_oak_log':'#3e2c22','birch_planks':'#d9c997','birch_log':'#d8d3c3',
 'grass_block':'#749a45','dirt':'#886448','sand':'#e5d29a','sandstone':'#d4bd84','smooth_sandstone':'#e4d09a',
 'oak_leaves':'#4e8042','spruce_leaves':'#355b43','water':'#428ac2','glass':'#b1dfe5',
 'white_wool':'#eee8dc','black_wool':'#272a31','red_wool':'#aa3741','blue_wool':'#3b5792',
 'green_wool':'#4a713e','yellow_wool':'#e3b847','orange_wool':'#d77b35','purple_wool':'#865299',
 'brown_wool':'#79533a','gray_wool':'#565c68','light_gray_wool':'#a3a5a2','cyan_wool':'#328b99',
 'pink_wool':'#d89aa5','lime_wool':'#86b545','glowstone':'#efbd62','iron_block':'#d0d2d2',
 'gold_block':'#e7ba39','copper_block':'#b97657','oxidized_copper':'#559786',
 'prismarine':'#639b95','dark_prismarine':'#355f5b','sea_lantern':'#c3eee2','quartz_block':'#e7ded3',
 'smooth_quartz':'#e9e2d8','deepslate':'#454852','deepslate_bricks':'#4a4e57','polished_deepslate':'#525560',
 'blackstone':'#323039','polished_blackstone_bricks':'#3d3742','amethyst_block':'#9673b0',
 'obsidian':'#282437','moss_block':'#647c39','end_stone':'#d7d6a3','purpur_block':'#b694b3',
 'packed_ice':'#83b5db','blue_ice':'#639ace','terracotta':'#a96b51','white_terracotta':'#cfaf9d',
 'red_terracotta':'#99513d','blue_terracotta':'#545276','purple_terracotta':'#845b72',
 'tuff':'#74796a','calcite':'#d6d3c8','basalt':'#55585e','red_sandstone':'#bd7039',
 'nether_bricks':'#482e37','red_nether_bricks':'#6c3034','warped_planks':'#327b77','warped_stem':'#5b6373',
 'crimson_planks':'#773b58','crimson_stem':'#6b334d','cherry_planks':'#d39b95','cherry_log':'#6e4553',
 'mangrove_planks':'#8b463b','mangrove_log':'#68503d','bamboo_planks':'#c5b568'}

def rgb(name):
    h=COLORS.get(name,'#958575').lstrip('#'); return tuple(int(h[i:i+2],16) for i in (0,2,4))

def render(path):
    path=Path(path); s=json.loads((path/'sample.json').read_text(encoding='utf-8'))
    blocks=s['blocks']; positions=np.array([[b['x'],b['y'],b['z']] for b in blocks],dtype=np.int16)
    lo=positions.min(axis=0); hi=positions.max(axis=0); shape=tuple((hi-lo+3).tolist())
    filled=np.zeros(shape,dtype=bool); idx=positions-lo+1;filled[idx[:,0],idx[:,1],idx[:,2]]=True
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',19) if Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf').exists() else ImageFont.load_default()
    for label,sx,sz in [('southwest',-1,1),('northeast',1,-1)]:
        faces=[]
        corners=((0,1,0),(0,1,1),(1,1,1),(1,1,0))
        defs=[(0,sx,[(1 if sx>0 else 0,0,0),(1 if sx>0 else 0,1,0),(1 if sx>0 else 0,1,1),(1 if sx>0 else 0,0,1)],.74),
              (2,sz,[(0,0,1 if sz>0 else 0),(1,0,1 if sz>0 else 0),(1,1,1 if sz>0 else 0),(0,1,1 if sz>0 else 0)],.88),
              (1,1,corners,1.10)]
        for axis,direction,cs,light in defs:
            adjacent=idx.copy(); adjacent[:,axis]+=direction
            visible=np.flatnonzero(~filled[adjacent[:,0],adjacent[:,1],adjacent[:,2]])
            for i in visible:
                p=positions[i].astype(float);q=np.array(cs)+p
                u=(q[:,0]*sx-q[:,2]*sz)*.8660254;v=(q[:,0]*sx+q[:,2]*sz)*.5-q[:,1]
                color=tuple(min(255,int(c*light)) for c in rgb(blocks[int(i)]['type']))
                center=q.mean(axis=0);depth=center[0]*sx+center[2]*sz+center[1]*1.6
                faces.append((depth,list(zip(u,v)),color))
        faces.sort(key=lambda f:f[0]);xy=np.array([p for _,poly,_ in faces for p in poly])
        mn=xy.min(axis=0);mx=xy.max(axis=0);scale=min(1080/(mx[0]-mn[0]),760/(mx[1]-mn[1]))
        im=Image.new('RGB',(1200,900),'#eff1ee');draw=ImageDraw.Draw(im)
        offset=np.array([(1200-(mx[0]-mn[0])*scale)/2,75+(790-(mx[1]-mn[1])*scale)/2])-mn*scale
        for _,poly,c in faces:
            points=[tuple(np.array(p)*scale+offset) for p in poly]
            edge=tuple(int(t*.78) for t in c)
            draw.polygon(points,fill=c,outline=edge if scale>3 else None)
        draw.text((32,22),s['sample_id']+'   /   '+s['building']['name'][:62],font=font,fill='#293b36')
        draw.text((32,866),label+'  |  '+str(len(blocks))+' voxels  |  saved voxel geometry',font=font,fill='#66766f')
        out=path/('preview_'+label+'.png');tmp=out.with_suffix('.tmp.png');im.save(tmp);tmp.replace(out)
    return {'status':'complete','source':'saved_full_voxels','views':['southwest','northeast']}

if __name__=='__main__':
    import sys
    print(json.dumps(render(sys.argv[1])))
