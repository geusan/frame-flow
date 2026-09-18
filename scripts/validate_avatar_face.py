"""Validate an authored face GLB against its immutable source (stdlib only)."""
import argparse
import hashlib
import json
import math
import struct
from itertools import product
from pathlib import Path


class Glb:
    def __init__(self, path):
        self.raw=Path(path).read_bytes()
        magic,version,length=struct.unpack_from('<4sII',self.raw)
        assert magic==b'glTF' and version==2 and length==len(self.raw)
        offset=12
        while offset<len(self.raw):
            size,kind=struct.unpack_from('<II',self.raw,offset);body=self.raw[offset+8:offset+8+size]
            if kind==0x4e4f534a:self.doc=json.loads(body)
            if kind==0x004e4942:self.bin=body
            offset+=size+8

    def accessor(self,index):
        accessor=self.doc['accessors'][index]
        components={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[accessor['type']]
        component={5120:'b',5121:'B',5122:'h',5123:'H',5125:'I',5126:'f'}[accessor['componentType']]
        fmt='<'+component*components;size=struct.calcsize(fmt)
        if 'bufferView' in accessor:
            view=self.doc['bufferViews'][accessor['bufferView']]
            start=view.get('byteOffset',0)+accessor.get('byteOffset',0);stride=view.get('byteStride',size)
            rows=[struct.unpack_from(fmt,self.bin,start+i*stride) for i in range(accessor['count'])]
        else:rows=[(0,)*components for _ in range(accessor['count'])]
        if 'sparse' in accessor:
            sparse=accessor['sparse'];indices=sparse['indices'];values=sparse['values']
            index_format='<'+{5121:'B',5123:'H',5125:'I'}[indices['componentType']]
            index_start=self.doc['bufferViews'][indices['bufferView']].get('byteOffset',0)+indices.get('byteOffset',0)
            value_start=self.doc['bufferViews'][values['bufferView']].get('byteOffset',0)+values.get('byteOffset',0)
            for i in range(sparse['count']):
                key=struct.unpack_from(index_format,self.bin,index_start+i*struct.calcsize(index_format))[0]
                rows[key]=struct.unpack_from(fmt,self.bin,value_start+i*size)
        return rows

    def positions(self,name):
        mesh=next(m for m in self.doc['meshes'] if m.get('name')==name)
        return [v for p in mesh['primitives'] for v in self.accessor(p['attributes']['POSITION'])]


def validate(source,output):
    old,new=Glb(source),Glb(output)
    digest=hashlib.sha256(old.raw).hexdigest()
    bone_names={new.doc['nodes'][i]['name'] for s in new.doc['skins'] for i in s['joints']}
    original_bones={old.doc['nodes'][i]['name'] for s in old.doc['skins'] for i in s['joints']}
    assert original_bones<=bone_names,'Original body bones were removed'
    assert {'FaceLeftEye','FaceRightEye'}<=bone_names
    profiles=[n['extras']['faceProfile'] for n in new.doc['nodes'] if n.get('extras',{}).get('faceProfilePrepared')]
    assert len(profiles)==1
    profile=profiles[0]
    assert profile['source_sha256']==digest
    assert profile['schema_version']=='avatar.face_profile.v3'
    assert profile['mode']=='native' and profile['expressions']['preset']=='extended'
    assert profile['gaze']['method']=='bones'
    meshes={m.get('name'):m for m in new.doc['meshes']}
    # Blender mesh datablock names are independent of object names; nodes are the
    # portable names used by the browser for face/eye/teeth selection.
    node_meshes={n['name']:new.doc['meshes'][n['mesh']] for n in new.doc['nodes'] if 'mesh' in n}
    for name in ['AvatarFace','MouthCavity','UpperTeeth','LowerTeeth','Tongue','EyeLeft','EyeRight','IrisLeft','IrisRight']:
        assert name in node_meshes,f'Missing facial part: {name}'
    names=set();max_displacement=0
    for mesh in new.doc['meshes']:
        target_names=mesh.get('extras',{}).get('targetNames',[])
        assert len(target_names)==len(set(target_names))
        names.update(target_names)
        assert all(weight==0 for weight in mesh.get('weights',[])),'Export must be neutral'
        for primitive in mesh['primitives']:
            for index in primitive['attributes'].values():
                assert all(math.isfinite(x) for row in new.accessor(index) for x in row)
            assert len(target_names)==len(primitive.get('targets',[]))
            for target in primitive.get('targets',[]):
                offsets=new.accessor(target['POSITION'])
                assert all(math.isfinite(x) for row in offsets for x in row)
                maximum=max(math.sqrt(sum(x*x for x in row)) for row in offsets)
                max_displacement=max(max_displacement,maximum)
                assert maximum<.04,'Unbounded facial deformation'
    assert set(profile['mappings'].values())<=names,'Profile advertises missing shapes'
    assert len(set(profile['mappings'].values()))==44
    original_mesh=old.doc['meshes'][0]['name']
    old_positions={v for v in old.positions(original_mesh) if v[1]<.79 or v[1]>.94}
    tolerance=2e-6;cells={}
    for v in new.positions(original_mesh):cells.setdefault(tuple(math.floor(x/tolerance) for x in v),[]).append(v)
    max_body_error=0
    for v in old_positions:
        cell=tuple(math.floor(x/tolerance) for x in v)
        neighbors=[w for delta in product((-1,0,1),repeat=3) for w in cells.get(tuple(a+b for a,b in zip(cell,delta)),[])]
        error=min((math.dist(v,w) for w in neighbors),default=math.inf)
        assert error<tolerance,'Body/ear geometry changed outside the facial authoring region'
        max_body_error=max(max_body_error,error)
    for side in ('Left','Right'):
        for part in ('Eye','Iris'):
            node=next(n for n in new.doc['nodes'] if n.get('name')==part+side)
            joints=new.doc['skins'][node['skin']]['joints']
            for primitive in node_meshes[part+side]['primitives']:
                indices=new.accessor(primitive['attributes']['JOINTS_0']);weights=new.accessor(primitive['attributes']['WEIGHTS_0'])
                for ids,values in zip(indices,weights):
                    assert abs(sum(values)-1)<1e-5
                    active={new.doc['nodes'][joints[i]]['name'] for i,w in zip(ids,values) if w>.001}
                    assert active=={'Face'+side+'Eye'},'Eye geometry must follow its own bone'
    return {'source_sha256':digest,'output_sha256':hashlib.sha256(new.raw).hexdigest(),'bytes':len(new.raw),'bone_count':len(bone_names),'original_bones_preserved':len(original_bones),'expression_channels':44,'mesh_count':len(meshes),'max_morph_displacement':max_displacement,'body_and_ears_preserved':True,'max_body_export_error':max_body_error,'eye_weights_valid':True,'embedded_profile_valid':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('output');p.add_argument('--report',type=Path)
    args=p.parse_args();result=validate(args.source,args.output)
    text=json.dumps(result,indent=2)+'\n'
    if args.report:args.report.write_text(text)
    print(text)
