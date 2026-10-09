"""Local geometry evidence, not an aesthetic or engineering certification."""
import json,hashlib,re
from collections import Counter,deque
from pathlib import Path
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from .legacy_render import COLORS
VERSION='architecture-evidence-3.1'

def inspect(s,legacy=False):
    violations=[];warnings=[];evidence={}
    def fail(rule,**details):violations.append({'rule':rule,**details})
    blocks=s.get('blocks',[]);components=s.get('components',[])
    if not blocks:return {'passed':False,'violations':[{'rule':'empty_sample'}],'version':VERSION}
    cs={c['id']:c for c in components}
    if len(cs)!=len(components):fail('duplicate_component_id')
    points={};owned={}
    for b in blocks:
        p=tuple(b.get(k) for k in ('x','y','z'))
        if any(type(n) is not int or not 0<=n<256 for n in p):fail('invalid_coordinate',coordinate=p);continue
        if p in points:fail('duplicate_coordinate',coordinate=p)
        if b.get('type') not in COLORS or b.get('component_id') not in cs:fail('invalid_material_or_owner',coordinate=p);continue
        points[p]=b
        owned.setdefault(b['component_id'],[]).append(b)
    if violations:return {'passed':False,'violation_count':len(violations),'violations':violations,'version':VERSION}
    pos=np.array(list(points),dtype=np.int16);lo=pos.min(axis=0);hi=pos.max(axis=0)
    grid=np.zeros(tuple((hi-lo+3).tolist()),dtype=bool);idx=pos-lo+1;grid[tuple(idx.T)]=True
    labels,n=ndimage.label(grid,structure=np.ones((3,3,3)))
    sizes=np.bincount(labels[grid]);main=int(sizes.argmax())
    # Every new task explicitly forbids detached secondary elements.
    if n>1:
        mainpos=pos[labels[tuple(idx.T)]==main];tree=cKDTree(mainpos)
        details=[]
        for label in range(1,n+1):
            if label==main:continue
            subset=pos[labels[tuple(idx.T)]==label]
            distances,nearest=tree.query(subset);j=int(distances.argmin())
            details.append({'count':len(subset),'component_ids':sorted({points[tuple(p)]['component_id'] for p in subset}),
              'bbox':{'min':subset.min(axis=0).tolist(),'max':subset.max(axis=0).tolist()},
              'detached_coordinate':subset[j].tolist(),'nearest_main_coordinate':mainpos[int(nearest[j])].tolist()})
        if legacy:warnings.append({'rule':'disconnected_geometry_review','groups':details[:12]})
        else:fail('disconnected_geometry',groups=details[:12],repair='Correct misplaced coordinates or physically attach each intended part with its own appropriate support. Do not delete details.')
    for cid,c in cs.items():
        bs=owned.get(cid,[])
        if not bs:fail('empty_component',component_id=cid);continue
        expected={'min':[min(b[a] for b in bs) for a in ('x','y','z')],'max':[max(b[a] for b in bs) for a in ('x','y','z')]}
        g=c.get('geometry',{})
        if len(bs)!=g.get('voxel_count') or expected!=g.get('bbox') or sorted({b['type'] for b in bs})!=c.get('materials'):
            fail('component_statistics_mismatch',component_id=cid)
        if c.get('category')=='environment' and not s['task_spec'].get('allowed_accessories'):
            fail('unapproved_environment',component_id=cid)
        if c['category']=='door':
            dims=[expected['max'][i]-expected['min'][i]+1 for i in range(3)]
            if dims[1]<2:fail('door_label_not_a_doorway',component_id=cid,bbox=expected,repair='A lone keystone is not a door. Restore a real accessible framed opening and assign its actual frame/panel voxels to the door ID.')
        if c['category']=='window' and c.get('orientation') in ('north','south','east','west'):
            axis=2 if c['orientation'] in ('north','south') else 0
            glass=[tuple(b[a] for a in ('x','y','z')) for b in bs if b['type']=='glass'];blocked=[];obstructions=[]
            for p in glass:
                for sign in (-1,1):
                    q=list(p)
                    for step in range(1,5):
                        q[axis]=p[axis]+sign*step;other=points.get(tuple(q))
                        if other is None:break
                        if other['type']!='glass':
                            blocked.append(p)
                            if len(obstructions)<6:
                                obstructions.append({'glazing_coordinate':list(p),'coordinate':list(q),
                                                     'component_id':other['component_id'],'material':other.get('block_state',other['type'])})
                            break
            if blocked:fail('window_backed_by_solid_wall',component_id=cid,coordinates=[list(p) for p in sorted(set(blocked))[:6]],obstructions=obstructions,repair='Cut through the actual wall thickness before glazing. Keep the frame and glass; remove opaque backing only inside the aperture.')
    spec=s['task_spec'];spaces=spec.get('spaces',[]);features=spec.get('features',[])
    if not legacy and not any(c['category']=='slab' for c in cs.values()):fail('missing_floor_semantics',repair='Label the actual occupied floor separately from its foundation.')
    for f in features:
        missing=[cid for cid in f.get('component_ids',[]) if cid not in owned]
        if not f.get('component_ids') or missing:fail('feature_not_built',feature=f.get('id'),missing_ids=missing)
    supported=set()
    for x,y,z in points:
        if y<253 and (x,y+1,z) not in points and (x,y+2,z) not in points:supported.add((x,y+1,z))
    # Detect repeated column instances merged under one owner using their actual XZ footprint.
    for cid,c in cs.items():
        if c['category']!='column':continue
        coords=np.array([[b['x'],b['z']] for b in owned[cid]])
        mn=coords.min(axis=0);shape=coords.max(axis=0)-mn+1
        mask=np.zeros(tuple(shape),dtype=bool);mask[tuple((coords-mn).T)]=True
        _,groups=ndimage.label(mask,structure=np.ones((3,3)))
        if groups>1 and not legacy:fail('merged_column_instances',component_id=cid,footprint_groups=int(groups),repair='Give each physically separate column its own component ID; retain the geometry.')
    # Derive usable floors directly from saved geometry, without speculative pre-code room boxes.
    floors={}
    for cid,c in cs.items():
        text=' '.join(str(c.get(k,'')) for k in ('id','name','name_zh','floor'))
        if c['category'] not in ('slab','foundation') or c.get('attributes',{}).get('role')=='ceiling' or re.search(r'ceiling|roof|vault|顶棚|顶板|屋面',text,re.I):continue
        top={}
        for b in owned[cid]:top[b['x'],b['z']]=max(top.get((b['x'],b['z']),-1),b['y'])
        surface=set()
        for (x,z),y in top.items():
            # A thin finish above a structural slab is part of the walking surface.
            # It must belong to the same declared level, not a separate storey/roof.
            for layer in range(2):
                above=points.get((x,y+1,z))
                if not above:break
                finish=cs[above['component_id']];fb=finish['geometry']['bbox']
                if finish['category'] not in ('slab','decoration') or finish.get('floor')!=c.get('floor') or finish.get('attributes',{}).get('role')=='ceiling' or fb['max'][1]-fb['min'][1]>1:break
                y+=1
            surface.add((x,y+1,z))
        floors[cid]={'surface':surface,'walkable':surface&supported}
    floor_walkable=set().union(*(f['walkable'] for f in floors.values())) if floors else set()
    walk_reached=set()
    unseen=set(floor_walkable);best_weight=0
    while unseen:
        start=min(unseen,key=lambda p:(p[1],-p[2],p[0]));region={start};queue=deque([start])
        while queue:
            x,y,z=queue.popleft()
            for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                for dy in (-1,0,1):
                    p=(x+dx,y+dy,z+dz)
                    if p not in supported or p in region:continue
                    if dy==1 and (x,y+2,z) in points:continue
                    if dy==-1 and (p[0],y+1,p[2]) in points:continue
                    region.add(p);queue.append(p)
        weight=len(region&floor_walkable);unseen.difference_update(region)
        if weight>best_weight:best_weight=weight;walk_reached=region
    floor_records=[]
    for cid,f in floors.items():
        available=len(f['walkable'])/max(1,len(f['surface']));reachable_fraction=len(f['walkable']&walk_reached)/max(1,len(f['walkable']))
        rec={'component_id':cid,'surface_cells':len(f['surface']),'clear_headroom_fraction':round(available,4),'reachable_fraction':round(reachable_fraction,4)};floor_records.append(rec)
        if not legacy and cs[cid]['category']=='slab' and len(f['surface'])>=16 and available<.35:fail('actual_floor_filled_or_no_headroom',**rec,repair='Correct the actual room/roof fill or floor height; do not relabel an occupied floor as ceiling.')
        if not legacy and (cs[cid]['category']=='slab' or cs[cid].get('attributes',{}).get('role')=='floor') and len(f['walkable'])>=8 and reachable_fraction<.8:
            fail('actual_floor_unreachable',**rec,example_unreachable_coordinates=[list(p) for p in sorted(f['walkable']-walk_reached)[:6]],repair='Open the intended doorway or correct stairs/landing continuity and headroom. Keep the designed floor.')
    evidence['actual_floor_surfaces']=floor_records
    reachable=set()
    if spaces:
        entry=tuple(spaces[0].get('entry',[]))
        if entry in supported:
            reachable={entry};q=deque([entry])
            while q:
                x,y,z=q.popleft()
                for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
                    for dy in (-1,0,1):
                        p=(x+dx,y+dy,z+dz)
                        if p not in supported or p in reachable:continue
                        # Headroom along step transition, not just at the endpoints.
                        if dy==1 and (x,y+2,z) in points:continue
                        if dy==-1 and (p[0],y+1,p[2]) in points:continue
                        reachable.add(p);q.append(p)
    spatial=[]
    for sp in spaces:
        bb=sp.get('air_bbox',{});mn=bb.get('min',[]);mx=bb.get('max',[])
        if len(mn)!=3 or len(mx)!=3 or any(type(v) is not int or not 0<=v<256 for v in mn+mx) or any(mx[i]<mn[i] for i in range(3)):
            fail('invalid_space_box',space=sp.get('id'));continue
        volume=np.prod([mx[i]-mn[i]+1 for i in range(3)])
        occupancy=sum(all(mn[i]<=p[i]<=mx[i] for i in range(3)) for p in points)
        air=1-occupancy/volume
        floor_count=sum((x,mn[1]-1,z) in points for x in range(mn[0],mx[0]+1) for z in range(mn[2],mx[2]+1))
        floor_area=(mx[0]-mn[0]+1)*(mx[2]-mn[2]+1)
        entry=tuple(sp.get('entry',[]));record={'id':sp.get('id'),'air_fraction':round(float(air),4),'floor_coverage':round(floor_count/floor_area,4),'entry':list(entry),'entry_walkable':entry in supported,'entry_reachable_from_first':entry in reachable}
        spatial.append(record)
        if air<.85:fail('space_filled_or_wrong_box',**record,repair='Keep intended room and remove accidental solid fill or correct its air box to the actual interior.')
        if floor_count/floor_area<.6:fail('space_missing_floor_or_wrong_level',**record)
        if entry not in supported:fail('entry_blocked_or_unsupported',**record,repair='Give the entry real floor support and two-voxel clear headroom; report its actual standing coordinate.')
        elif entry not in reachable:fail('space_not_accessible',**record,repair='Connect the planned space with real doors and stairs. Each step rises at most one voxel and has headroom.')
        missing=[cid for cid in sp.get('component_ids',[]) if cid not in owned]
        if missing:fail('space_parts_missing',space=sp.get('id'),missing_ids=missing)
    # Opening metadata is tested against saved voxels, including later overdraw.
    opening_evidence=[]
    for cid,c in cs.items():
        for op in c.get('attributes',{}).get('actual_openings',[]):
            oc=cs.get(op['component_id']);bounds=op.get('bounds',[])
            if not oc or len(bounds)!=6:fail('opening_metadata_invalid',wall=cid);continue
            x0,x1,y0,y1,z0,z1=bounds;axis=oc.get('orientation')
            if axis in ('north','south'):
                inner=[(x,y,z) for x in range(x0+1,x1) for y in range(y0+(op['type']=='window'),y1) for z in range(z0,z1+1)]
            else:
                inner=[(x,y,z) for x in range(x0,x1+1) for y in range(y0+(op['type']=='window'),y1) for z in range(z0+1,z1)]
            blocked=[p for p in inner if p in points and not(op.get('glazing_material') and points[p]['type']==op['glazing_material'] and points[p]['component_id']==op['component_id'])]
            record={'id':op['component_id'],'type':op['type'],'orientation':axis,'interior_voxels':len(inner),'blocked_voxels':len(blocked)}
            opening_evidence.append(record)
            if not inner or blocked:fail('opening_filled_by_later_geometry',**record,example_coordinates=[list(p) for p in blocked[:8]],
                obstructions=[{'coordinate':list(p),'component_id':points[p]['component_id'],'material':points[p].get('block_state',points[p]['type'])} for p in blocked[:8]],
                repair='Correct the obstructing component strokes at these saved coordinates. Preserve the intended opening, frame and glazing; do not remove required components or spaces.')
    base=sum(len(owned[cid]) for cid,c in cs.items() if c['category']=='foundation')
    if base/len(points)>.55:fail('foundation_dominates',fraction=round(base/len(points),3))
    flat=[]
    for cid,c in cs.items():
        if c['category'] not in ('exterior_wall','interior_wall'):continue
        bs=owned[cid];bb=c['geometry']['bbox'];dims=[bb['max'][i]-bb['min'][i]+1 for i in range(3)]
        if len(bs)>=180 and dims[1]>=7 and max(dims[0],dims[2])>=16 and not c.get('attributes',{}).get('actual_openings'):
            flat.append(cid)
    if flat:warnings.append({'rule':'large_wall_without_registered_opening','component_ids':flat,'meaning':'Review relief, attached articulation and functional need. Not proof of poor architecture.'})
    scaled=np.floor((pos-lo)/np.maximum(hi-lo,1)*31).astype(int)
    occupancy32=np.zeros((32,32,32),dtype=np.uint8);occupancy32[tuple(scaled.T)]=1
    signatures=[]
    for flip in (False,True):
        a=np.flip(occupancy32,axis=0) if flip else occupancy32
        for k in range(4):signatures.append(hashlib.sha256(np.packbits(np.rot90(a,k,axes=(0,2))).tobytes()).hexdigest())
    evidence.update(blocks=len(points),components=len(cs),dimensions=(hi-lo+1).tolist(),contact_groups=n,
      spaces=spatial,openings=opening_evidence,foundation_fraction=round(base/len(points),4),
      categories=dict(Counter(c['category'] for c in cs.values())),shape_signature=min(signatures),
      independent_aesthetic_review=False)
    return {'version':VERSION,'sample_id':s.get('sample_id'),'passed':not violations,'violation_count':len(violations),'violations':violations,
      'warnings':warnings,'evidence':evidence,'quality_status':'local_checks_passed_not_independently_verified' if not violations else 'held'}

def check(path,legacy=False):
    path=Path(path);report=inspect(json.loads((path/'sample.json').read_text(encoding='utf-8')),legacy)
    (path/'geometry_gate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report
