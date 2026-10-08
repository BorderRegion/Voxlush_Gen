"""Evidence from actual timber-house voxels; no frozen pre-generation plan."""
from collections import Counter
import numpy as np

def inspect(sample,brief):
    components={c['id']:c for c in sample['components']};blocks=sample['blocks'];spec=sample['task_spec']
    structural={'slab','exterior_wall','interior_wall','roof','door','window','column','beam','stair'}
    main=[b for b in blocks if components[b['component_id']]['category'] in structural]
    violations=[];metrics={};req=brief['quality_requirements']
    def minimum(rule,actual,required):
        if actual<required:violations.append({'rule':rule,'actual':actual,'required':required})
    minimum('wooden_main_voxels',len(main),req['minimum_main_voxels'])
    if not main:return violations,metrics
    xyz=np.array([[b[k] for k in ('x','y','z')] for b in main]);dims=xyz.max(axis=0)-xyz.min(axis=0)+1
    materials=Counter(b['type'] for b in main);wood=sum(n for m,n in materials.items() if m.endswith(('_planks','_log','_stem')) or m=='bamboo_block')/len(main)
    cats=Counter(c['category'] for c in components.values())
    minimum('wooden_footprint',int(dims[0]*dims[2]),req['minimum_footprint_bbox_area'])
    minimum('real_timber_fraction',wood,req['minimum_wood_fraction'])
    minimum('meaningful_components',len(components),req['minimum_components'])
    minimum('interior_partitions',cats['interior_wall'],req['minimum_interior_wall_instances'])
    roofs=[c for c in components.values() if c['category']=='roof' and c['geometry']['voxel_count']>=32]
    minimum('meaningful_roof_regions',len(roofs),req['minimum_roof_regions'])
    owned={cid:[] for cid in components}
    points={}
    for b in blocks:
        p=(b['x'],b['y'],b['z']);points[p]=b;owned[b['component_id']].append(p)
    windows=[c['id'] for c in components.values() if c['category']=='window' and sum(points[p]['type']=='glass' for p in owned[c['id']])>=3]
    minimum('real_glazed_window_instances',len(windows),req['minimum_window_instances'])
    rooms=spec.get('spaces',[]);enclosed=[r for r in rooms if r.get('kind','enclosed')=='enclosed']
    minimum('declared_actual_room_spaces',len(enclosed),req['minimum_rooms'])
    bounded=[];bbox_by_room=[]
    for room in rooms:
        bb=room.get('air_bbox',{});lo=bb.get('min');hi=bb.get('max')
        if not lo or not hi:continue
        if hi[0]-lo[0]+1<6 or hi[2]-lo[2]+1<6 or hi[1]-lo[1]+1<4:
            violations.append({'rule':'usable_room_dimensions','room':room.get('id'),'bbox':bb})
        if room.get('kind','enclosed') not in ('enclosed','open_gallery','porch','terrace'):
            violations.append({'rule':'invalid_space_kind','room':room.get('id')})
        coverage=[]
        for axis in (0,2):
            cross=2 if axis==0 else 0
            for edge in (lo[axis]-1,hi[axis]+1):
                hit=0;total=0
                for a in range(lo[cross],hi[cross]+1):
                    for y in range(lo[1],hi[1]+1):
                        p=(edge,y,a) if axis==0 else (a,y,edge);b=points.get(p);total+=1
                        if b and components[b['component_id']]['category'] in ('interior_wall','exterior_wall','door','window','column','beam'):hit+=1
                coverage.append(hit/max(1,total))
        bounded_sides=sum(c>=.35 for c in coverage)
        bounded.append({'id':room.get('id'),'wall_coverage':coverage,'bounded_sides':bounded_sides})
        if room.get('kind','enclosed')=='enclosed' and bounded_sides<3:violations.append({'rule':'room_is_not_bounded_by_real_architecture','room':room.get('id'),'wall_coverage':coverage,'repair':'Report the real interior bounds and build the intended walls/partitions. Do not declare several imaginary rooms in one empty hall.'})
        for other,low,high in bbox_by_room:
            overlap=np.maximum(0,np.minimum(hi,high)-np.maximum(lo,low)+1)
            if np.prod(overlap)>0:violations.append({'rule':'overlapping_room_spaces','rooms':[other,room.get('id')],'overlap_voxels':int(np.prod(overlap))})
        bbox_by_room.append((room.get('id'),np.array(lo),np.array(hi)))
    roof_points={p for c in roofs for p in owned[c['id']]};inside=0
    directions=((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
    for x,y,z in roof_points:
        if all((x+dx,y+dy,z+dz) in roof_points for dx,dy,dz in directions):inside+=1
    if len(roof_points)>500 and inside/len(roof_points)>.15:violations.append({'rule':'solid_roof_mound','interior_roof_fraction':inside/len(roof_points),'repair':'Preserve the roof silhouette but construct a hollow roof shell and individually labeled framing.'})
    floors=spec.get('floors',1)
    if isinstance(floors,int):minimum('stair_connections',cats['stair'],max(0,floors-1))
    metrics.update(main_voxels=len(main),dimensions=dims.tolist(),wood_fraction=wood,window_instances=len(windows),roof_regions=len(roofs),components=len(components),rooms=bounded)
    return violations,metrics
