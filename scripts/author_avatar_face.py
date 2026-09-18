"""Blender authoring recipe for the inspected Tripo cat avatar.

Run with Blender 4.3+, --background --factory-startup --disable-autoexec
--python-exit-code 1 --python scripts/author_avatar_face.py -- --input source.glb
--output directory. This is an authoring recipe, not a Workflow executor or a
general facial auto-rigger. Source SHA and inspected landmarks are intentional.
All output is new; the input GLB is never modified. No external add-on is used.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

SOURCE_SHA = '46e2f1035e6596156d0137bf21ae1fa5c550fee200651a4d41e855662a69a7ff'
CHANNELS = '''browDownLeft browDownRight browInnerUp browOuterUpLeft browOuterUpRight cheekPuff cheekSquintLeft cheekSquintRight eyeBlinkLeft eyeBlinkRight eyeSquintLeft eyeSquintRight eyeWideLeft eyeWideRight jawForward jawLeft jawOpen jawRight mouthClose mouthDimpleLeft mouthDimpleRight mouthFrownLeft mouthFrownRight mouthFunnel mouthLeft mouthLowerDownLeft mouthLowerDownRight mouthPressLeft mouthPressRight mouthPucker mouthRight mouthRollLower mouthRollUpper mouthShrugLower mouthShrugUpper mouthSmileLeft mouthSmileRight mouthStretchLeft mouthStretchRight mouthUpperUpLeft mouthUpperUpRight noseSneerLeft noseSneerRight tongueOut'''.split()
CY, MZ, D = -.0068, .8394, .0491
EYES = {'Left': (.01743, .8745), 'Right': (-.03166, .87370)}
EYE_RX, EYE_RZ = .0114, .0128
MOUTH_RX, MOUTH_RZ = .010, .00022


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--render', action='store_true')
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:])


def smooth(a, b, value):
    t = max(0., min(1., (value-a)/(b-a)))
    return t*t*(3-2*t)


def gaussian(y, z, cy, cz, ry, rz):
    return math.exp(-2*((y-cy)/ry)**2-2*((z-cz)/rz)**2)


def face_domain(y, z):
    return ((y-CY)/.048)**2+((z-.866)/.055)**2


def in_eye(y, z, scale=1):
    return any(((y-ey)/(EYE_RX*scale))**2+((z-ez)/(EYE_RZ*scale))**2 < 1 for ey, ez in EYES.values())


def mouth_domain(y, z):
    return ((y-CY)/MOUTH_RX)**2+((z-MZ)/MOUTH_RZ)**2


def skin_color(rgb):
    r,g,b=rgb
    return r > .2 and r > g*.99 and g > b*1.09 and r+g+b > .55


def make_material(name, color, roughness=.8, vertex_color=False):
    m=bpy.data.materials.new(name);m.use_nodes=True
    bsdf=m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=roughness
    if vertex_color:
        node=m.node_tree.nodes.new('ShaderNodeVertexColor');node.layer_name='FaceColor'
        m.node_tree.links.new(node.outputs['Color'],bsdf.inputs['Base Color'])
    return m


def make_mesh(name, vertices, faces, material, arm, bone='mixamorig:Head', colors=None):
    data=bpy.data.meshes.new(name);data.from_pydata(vertices,[],faces);data.update()
    obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    data.materials.append(material)
    for poly in data.polygons: poly.use_smooth=True
    if colors is not None:
        attr=data.color_attributes.new(name='FaceColor',type='FLOAT_COLOR',domain='POINT')
        for item,color in zip(attr.data,colors):item.color=(*color,1)
    group=obj.vertex_groups.new(name=bone);group.add(list(range(len(vertices))),1,'REPLACE')
    mod=obj.modifiers.new('Original humanoid skeleton','ARMATURE');mod.object=arm
    obj.parent=arm
    return obj


def displacement(co, key):
    x,y,z=co
    dy,dz=y-CY,z-MZ
    side=1 if key.endswith('Left') else -1
    lateral=(1+math.tanh(dy/.003*side))/2
    local=gaussian(y,z,CY,MZ,.025,.023)
    lower=1-smooth(MZ-.00010,MZ+.00010,z)
    lower_face=gaussian(y,z,CY,MZ-.008,.035,.034)*lower
    lip=gaussian(y,z,CY,MZ,.015,.006)
    corner=gaussian(y,z,CY+side*.010,MZ,.009,.010)
    delta=Vector((0.,0.,0.))
    if key.startswith(('eyeBlink','eyeSquint','eyeWide')):
        ey,ez=EYES['Left' if side==1 else 'Right']
        rel_y,rel_z=y-ey,z-ez
        r=((rel_y/EYE_RX)**2+(rel_z/EYE_RZ)**2)**.5
        w=1-smooth(1.05,1.8,r)
        target=ez-.0012+.0007*max(0,1-(rel_y/EYE_RX)**2)
        if key.startswith('eyeBlink'):delta.z=(target-z)*w
        elif key.startswith('eyeSquint'):delta.z=(target-z)*w*(.2 if rel_z>0 else .6)
        else:delta.z=rel_z*.24*w
        # Lids move slightly in front of the eyeball while closing.
        if key.startswith(('eyeBlink','eyeSquint')):
            moved_z=z+delta.z
            sphere_r=1-((y-ey)/.0135)**2-((moved_z-ez)/.0155)**2
            if sphere_r>0:delta.x=max(0,.0665+.0115*math.sqrt(sphere_r)+.0007-x)
    elif key.startswith('brow'):
        ey,ez=EYES['Left' if side==1 else 'Right']
        if key=='browInnerUp':delta.z=.005*gaussian(y,z,CY,.896,.030,.018)
        elif key.startswith('browDown'):
            w=gaussian(y,z,ey,.896,.023,.018);delta.z=-.004*w;delta.y=-side*.0015*w
        else:delta.z=.005*gaussian(y,z,ey+side*.005,.898,.017,.016)
    elif key=='jawOpen':delta.z=-.014*lower_face;delta.x=-.0015*lower_face
    elif key=='jawForward':delta.x=.0045*lower_face
    elif key in ('jawLeft','jawRight'):delta.y=side*.005*lower_face
    elif key=='mouthClose':delta.z=.013*lower_face
    elif key.startswith('mouthSmile'):
        delta.z=.005*corner;delta.y=side*.0023*corner
    elif key.startswith('mouthFrown'):delta.z=-.004*corner
    elif key.startswith('mouthDimple'):delta.y=side*.0025*corner;delta.x=-.0015*corner
    elif key.startswith('mouthStretch'):delta.y=side*.005*corner
    elif key in ('mouthLeft','mouthRight'):delta.y=side*.004*local
    elif key in ('mouthFunnel','mouthPucker'):
        delta.y=-dy*(.4 if key=='mouthFunnel' else .55)*local
        delta.x=(.004 if key=='mouthFunnel' else .006)*local
        delta.z=(1 if dz>=0 else -1)*(.0035 if key=='mouthFunnel' else .0013)*lip
    elif key.startswith('mouthLowerDown'):delta.z=-.005*lower*lip*lateral
    elif key.startswith('mouthUpperUp'):delta.z=.004*(1-lower)*lip*lateral
    elif key.startswith('mouthPress'):delta.z=-dz*.45*lip*lateral;delta.x=-.0005*lip*lateral
    elif key=='mouthRollLower':delta.x=-.003*lower*lip;delta.z=.001*lower*lip
    elif key=='mouthRollUpper':delta.x=-.003*(1-lower)*lip;delta.z=-.001*(1-lower)*lip
    elif key=='mouthShrugLower':delta.z=.003*lower*lip
    elif key=='mouthShrugUpper':delta.z=.003*(1-lower)*lip
    elif key=='cheekPuff':
        delta.x=.005*(gaussian(y,z,CY+.028,.853,.022,.023)+gaussian(y,z,CY-.028,.853,.022,.023))
    elif key.startswith('cheekSquint'):
        w=gaussian(y,z,CY+side*.026,.860,.022,.021);delta.x=.002*w;delta.z=.003*w
    elif key.startswith('noseSneer'):
        w=gaussian(y,z,CY+side*.006,.855,.014,.014);delta.z=.003*w
    # Anchor the patch boundary under the existing head/hair/neck.
    delta*=1-smooth(.78,1.0,face_domain(y,z))
    return delta


def add_shapes(obj, kind='face'):
    obj.shape_key_add(name='Basis')
    moved={}
    for key in CHANNELS:
        deltas=[]
        for v in obj.data.vertices:
            co=v.co
            if kind in ('face','cavity'):
                delta=displacement(co,key)
                if 'Lid' in obj.name and key.startswith(('eyeBlink','eyeSquint')):
                    delta.x+=.0003
                    if key.startswith('eyeBlink') and v.index%2:delta.z+=.0007 if obj.name.startswith('Upper') else -.00025
            else:
                delta=Vector((0,0,0))
                lower=kind in ('lower_teeth','tongue')
                if lower and key=='jawOpen':delta.z=-.010
                elif key=='jawForward':delta.x=.003 if lower else 0
                elif key in ('jawLeft','jawRight') and lower:delta.y=.004*(1 if key.endswith('Left') else -1)
                elif key=='tongueOut' and kind=='tongue':delta.x=.014;delta.z=.001
            deltas.append(delta)
        maximum=max(d.length for d in deltas)
        if maximum < 1e-7:continue
        shape=obj.shape_key_add(name=key)
        for v,d in zip(shape.data,deltas):v.co+=d
        moved[key]=maximum
    return moved


def main():
    args=arguments();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if hashlib.sha256(args.input.read_bytes()).hexdigest()!=SOURCE_SHA:raise ValueError('This recipe requires the inspected cat avatar. No output was created.')
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(args.input.resolve()))
    source=next(o for o in bpy.context.scene.objects if o.type=='MESH')
    arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    old_bones=[b.name for b in arm.data.bones]
    material=source.data.materials[0]
    bsdf=material.node_tree.nodes.get('Principled BSDF')
    image=bsdf.inputs['Base Color'].links[0].from_node.image
    width,height=image.size;pixels=np.empty(width*height*4,dtype=np.float32);image.pixels.foreach_get(pixels);pixels=pixels.reshape(height,width,4)
    uv=source.data.uv_layers.active.data
    def color_at(poly):
        coord=sum((uv[i].uv for i in poly.loop_indices),Vector((0,0)))/len(poly.loop_indices)
        return pixels[int(coord.y*(height-1))%height,int(coord.x*(width-1))%width,:3].copy()
    samples=[];remove=[]
    for poly in source.data.polygons:
        co=poly.center
        if co.x<.03 or face_domain(co.y,co.z)>1.08:continue
        color=color_at(poly)
        if skin_color(color) and not in_eye(co.y,co.z,1.18):samples.append((co.copy(),color))
        dark_hair=float(np.mean(color))<.19 and (co.z>.875 or abs(co.y-CY)>.035 or co.x>.094)
        if not dark_hair:remove.append(poly.index)
    if len(samples)<80:raise ValueError(f'Insufficient facial surface samples: {len(samples)}')
    base_color=np.median(np.array([color for _,color in samples]),axis=0)**2.2
    print('sampled skin linear color',base_color.tolist(),flush=True)
    def surface(y,z):
        # Smooth fitted front-face shell. The original triangle surface has folds
        # and baked texture shadows, so direct projection would preserve artifacts.
        x=.037+.048*math.sqrt(max(.04,1-((y-CY)/.061)**2-.65*((z-.859)/.061)**2))
        x+=.0118*gaussian(y,z,CY,.853,.010,.012)+.003*gaussian(y,z,CY,.866,.009,.022)
        x+=.0008*gaussian(y,z,CY,MZ,.012,.002)
        color=np.clip(base_color,[.40,.26,.16],[.63,.46,.33])
        blush=gaussian(y,z,CY+.027,.853,.017,.014)+gaussian(y,z,CY-.027,.853,.017,.014)
        color=color+np.array([.015,-.004,-.003])*blush
        lip_tint=gaussian(y,z,CY,MZ,.012,.0010)
        color=color*(1-lip_tint*.08)+np.array([.45,.18,.14])*lip_tint*.08
        return x,tuple(float(c) for c in color)
    print('skin samples',len(samples),'removed polygons',len(remove),'eye surface',[surface(y,z)[0] for y,z in EYES.values()],flush=True)
    bm=bmesh.new();bm.from_mesh(source.data);bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm,geom=[bm.faces[i] for i in remove],context='FACES');bm.to_mesh(source.data);bm.free()
    # A continuous facial surface with constrained loops around eyelids and lips.
    verts2=[];edges=[]
    def ellipse(cy,cz,ry,rz,count=64):
        ids=[]
        for i in range(count):
            t=2*math.pi*i/count;ids.append(len(verts2));verts2.append(Vector((cy+ry*math.cos(t),cz+rz*math.sin(t))))
        edges.extend((ids[i],ids[(i+1)%count]) for i in range(count))
    ellipse(CY,.866,.048,.055,128)
    for y,z in EYES.values():
        for scale in (1,1.12,1.3,1.6):ellipse(y,z,EYE_RX*scale,EYE_RZ*scale)
    for ry,rz in ((.010,.00022),(.0106,.0011),(.012,.0028),(.016,.007),(.023,.016)):ellipse(CY,MZ,ry,rz)
    for y in np.arange(CY-.047,CY+.048,.0017):
        for z in np.arange(.812,.921,.0017):
            if face_domain(y,z)>.99 or in_eye(y,z,1.65) or ((y-CY)/.024)**2+((z-MZ)/.017)**2<1:continue
            verts2.append(Vector((float(y),float(z))))
    coords,_,tris,_,_,_=delaunay_2d_cdt(verts2,edges,[],0,1e-7,False)
    faces=[]
    for tri in tris:
        y,z=sum((coords[i] for i in tri),Vector((0,0)))/len(tri)
        if face_domain(y,z)>1.001 or in_eye(y,z,.999) or mouth_domain(y,z)<.999:continue
        faces.append(tri)
    faceverts=[];colors=[]
    for y,z in coords:
        x,color=surface(y,z)
        # Inner lid rims sit in front of the new separate eyeballs.
        for ey,ez in EYES.values():
            r=(((y-ey)/EYE_RX)**2+((z-ez)/EYE_RZ)**2)**.5
            if r<1.35:x=max(x,.0790-(r-1)*.005)
        faceverts.append((x,y,z));colors.append(color)
    # Join the replacement face to the retained side/back head with a short
    # return surface, including an underside for the jaw above the original neck.
    outer=[min(range(len(coords)),key=lambda i:(coords[i]-point).length_squared) for point in verts2[:128]]
    previous=outer
    for ring in range(1,5):
        t=ring/4;current=[]
        for index in outer:
            x,y,z=faceverts[index];current.append(len(faceverts))
            below=1-smooth(.836,.86,z)
            faceverts.append((x-.037*t,y-(y-CY)*.08*t,z+.009*below*t));colors.append(colors[index])
        for i in range(len(outer)):
            j=(i+1)%len(outer);faces.append((previous[i],current[i],current[j],previous[j]))
        previous=current
    skin=make_material('Face · sampled original skin',(.75,.54,.36),.88,True)
    face=make_mesh('AvatarFace',faceverts,faces,skin,arm,colors=colors)
    shape_report={face.name:add_shapes(face)}
    dark=make_material('Soft black lashes and brows',(.009,.006,.004),.85)
    for side,(ey,ez) in EYES.items():
        # Separate lid-edge ribbons follow the same authored shapes as the skin.
        for upper in (True,False):
            verts=[];faces=[];steps=48
            for i in range(steps+1):
                t=i/steps;angle=(0 if upper else math.pi)+math.pi*t
                y=ey+EYE_RX*math.cos(angle);z=ez+EYE_RZ*math.sin(angle)
                width=(.00125 if upper else .0004)*math.sin(math.pi*t)**.45
                for edge in (0,1):
                    yy=y+(y-ey)/EYE_RX*width*edge;zz=z+(z-ez)/EYE_RZ*width*edge
                    x=surface(yy,zz)[0]+.00025;verts.append((x,yy,zz))
                if i<steps:k=i*2;faces.append((k,k+2,k+3,k+1))
            lashes=make_mesh(('UpperLid' if upper else 'LowerLid')+side,verts,faces,dark,arm)
            shape_report[lashes.name]=add_shapes(lashes)
        verts=[];faces=[]
        for i in range(25):
            t=i/24;y=ey+(t-.5)*.023;z=ez+.019+.002*math.sin(math.pi*t)
            for edge in (0,1):
                zz=z+edge*.0014*math.sin(math.pi*t)**.5
                verts.append((surface(y,zz)[0]+.0005,y,zz))
            if i<24:k=i*2;faces.append((k,k+2,k+3,k+1))
        brow=make_mesh('Brow'+side,verts,faces,dark,arm);shape_report[brow.name]=add_shapes(brow)
    # Add independent eye bones to the original head hierarchy.
    bpy.context.view_layer.objects.active=arm;arm.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
    eye_centers={}
    for side,(y,z) in EYES.items():
        center=Vector((.0665,y,z));eye_centers[side]=center
        bone=arm.data.edit_bones.new('Face'+side+'Eye');bone.head=center;bone.tail=center+Vector((.006,0,0));bone.parent=arm.data.edit_bones['mixamorig:Head']
    bpy.ops.object.mode_set(mode='OBJECT')
    white=make_material('Eye sclera',(.80,.79,.73),.32)
    iris_material=make_material('Amber iris',(.35,.16,.02),.3,True)
    for side,center in eye_centers.items():
        # True volumetric ellipsoid, larger than the lid aperture.
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=32,location=center)
        obj=bpy.context.object;obj.name='Eye'+side;obj.scale=(.0115,.0135,.0155)
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
        obj.data.materials.append(white)
        for poly in obj.data.polygons:poly.use_smooth=True
        obj.parent=arm;g=obj.vertex_groups.new(name='Face'+side+'Eye');g.add(list(range(len(obj.data.vertices))),1,'REPLACE');obj.modifiers.new('Eye rotation','ARMATURE').object=arm
        verts=[];colors=[];faces=[];steps=64;rings=18
        for ring in range(rings+1):
            r=max(.0001,ring/rings)
            for i in range(steps):
                a=i*math.tau/steps;dy=math.cos(a)*.0090*r;dz=math.sin(a)*.0113*r
                x=center.x+.0115*math.sqrt(max(0,1-(dy/.0135)**2-(dz/.0155)**2))+.00013
                verts.append((x,center.y+dy,center.z+dz))
                if r<.38:col=(.008,.005,.003)
                elif r>.93:col=(.035,.015,.004)
                else:
                    fiber=.8+.12*math.sin(a*35)+.08*math.sin(a*57+r*9)
                    lit=.72+.25*(-math.sin(a))
                    col=(.54*fiber*lit,.27*fiber*lit,.035*fiber)
                colors.append(col)
                if ring<rings:
                    k=ring*steps+i;j=ring*steps+(i+1)%steps;faces.append((k,j,j+steps,k+steps))
        iris=make_mesh('Iris'+side,verts,faces,iris_material,arm,'Face'+side+'Eye',colors)
        for i,(dy,dz,size) in enumerate(((.0027,.0055,.0015),(-.0023,.0025,.00055))):
            x=center.x+.0115*math.sqrt(1-(dy/.0135)**2-(dz/.0155)**2)+.00023
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,location=(x,center.y+dy,center.z+dz))
            glint=bpy.context.object;glint.name=f'EyeGlint{side}{i}';glint.scale=(.00025,size,size*1.15)
            bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);glint.data.materials.append(white)
            glint.parent=arm;g=glint.vertex_groups.new(name='Face'+side+'Eye');g.add(list(range(len(glint.data.vertices))),1,'REPLACE');glint.modifiers.new('Eye rotation','ARMATURE').object=arm
    # Real mouth cavity: inner wall rings behind the lip aperture.
    mouth_x=surface(CY,MZ)[0];verts=[];faces=[];steps=64
    for ring in range(7):
        t=ring/6
        for i in range(steps):
            a=i*math.tau/steps;y=CY+math.cos(a)*MOUTH_RX*(1-t*.35);z=MZ+math.sin(a)*MOUTH_RZ*(1-t*.35)
            x=surface(y,z)[0]-.00015-t*.010;verts.append((x,y,z))
            if ring<6:
                k=ring*steps+i;j=ring*steps+(i+1)%steps;faces.append((k,k+steps,j+steps,j))
    faces.append(tuple(range(6*steps,7*steps)))
    cavity=make_mesh('MouthCavity',verts,faces,make_material('Mouth interior',(.035,.006,.009)),arm)
    shape_report[cavity.name]=add_shapes(cavity,'cavity')
    # Rounded tooth strips stay behind the lips; lower teeth follow the jaw.
    toothmat=make_material('Teeth',(.82,.79,.66),.45)
    for lower in (False,True):
        pieces=[]
        for i in range(8):
            y=CY+(i-3.5)*.0021;z=MZ-(.0042 if lower else .0030)
            bpy.ops.mesh.primitive_cube_add(size=1,location=(mouth_x-.0055-abs(i-3.5)*.0001,y,z))
            obj=bpy.context.object;obj.scale=(.0018,.002,.0018 if lower else .0025)
            bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
            bevel=obj.modifiers.new('Rounded tooth edge','BEVEL');bevel.width=.0004;bevel.segments=3;bpy.ops.object.modifier_apply(modifier=bevel.name)
            pieces.append(obj)
        bpy.ops.object.select_all(action='DESELECT')
        for obj in pieces:obj.select_set(True)
        bpy.context.view_layer.objects.active=pieces[0];bpy.ops.object.join();obj=bpy.context.object
        obj.name='LowerTeeth' if lower else 'UpperTeeth';bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
        obj.data.materials.append(toothmat);obj.parent=arm;g=obj.vertex_groups.new(name='mixamorig:Head');g.add(list(range(len(obj.data.vertices))),1,'REPLACE');obj.modifiers.new('Head attachment','ARMATURE').object=arm
        shape_report[obj.name]=add_shapes(obj,'lower_teeth' if lower else 'upper_teeth')
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,location=(mouth_x-.008,CY,MZ-.0058))
    tongue=bpy.context.object;tongue.name='Tongue';tongue.scale=(.004,.0065,.0012);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    tongue.data.materials.append(make_material('Tongue',(.38,.065,.085),.55));tongue.parent=arm
    g=tongue.vertex_groups.new(name='mixamorig:Head');g.add(list(range(len(tongue.data.vertices))),1,'REPLACE');tongue.modifiers.new('Head attachment','ARMATURE').object=arm
    shape_report[tongue.name]=add_shapes(tongue,'tongue')
    profile={'schema_version':'avatar.face_profile.v3','source_sha256':SOURCE_SHA,'mode':'native','mesh':'AvatarFace','head_bone':'mixamorigHead','front_axis':'+x','anchors':{},'eye_radius':.38,'depth':.3,'gain':1.,'smoothing':.09,'mappings':{k:k for k in CHANNELS},'mouth_patch':False,'expressions':{'preset':'extended','channels':{}},'gaze':{'enabled':True,'method':'bones','sensitivity':2.5,'smoothing':.12,'deadzone':.04,'invert_x':False,'invert_y':False,'radius':.32,'range':.065,'max_angle':18,'left_eye_bone':'FaceLeftEye','right_eye_bone':'FaceRightEye'}}
    root=bpy.data.objects.new('AvatarFaceProfile',None);bpy.context.collection.objects.link(root)
    arm.parent=root;root['faceProfilePrepared']=True;root['faceProfile']=profile
    root['faceRigAuthoring']={'schema_version':'avatar.face_authoring.v1','source_sha256':SOURCE_SHA,'recipe':'scripts/author_avatar_face.py','method':'Blender procedural retopology and shape-key authoring','faceit_used':False}
    report={'source_sha256':SOURCE_SHA,'original_bones':old_bones,'bones':[b.name for b in arm.data.bones],'removed_face_polygons':len(remove),'skin_samples':len(samples),'face_vertices':len(faceverts),'face_triangles':len(face.data.polygons),'shape_displacements':shape_report,'limitations':['Model-specific procedural facial authoring; not Faceit output','Facial surface is reconstructed; original body, hair, ears and rig are retained','TongueOut requires manual control; not emitted by the current MediaPipe tracker']}
    (out/'face-profile.json').write_text(json.dumps(profile,indent=2)+'\n');(out/'authoring-report.json').write_text(json.dumps(report,indent=2)+'\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'cat-expressive.blend'))
    bpy.ops.export_scene.gltf(filepath=str(out/'cat-expressive.glb'),export_format='GLB',export_extras=True,export_animations=False,export_morph=True,export_morph_normal=True,export_skins=True)
    portable_profile={**profile,'source_sha256':hashlib.sha256((out/'cat-expressive.glb').read_bytes()).hexdigest()}
    (out/'face-profile.json').write_text(json.dumps(portable_profile,indent=2)+'\n')
    if args.render:render_previews(out)


def render_previews(out):
    scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE_NEXT';scene.eevee.taa_render_samples=16
    scene.render.resolution_x=640;scene.render.resolution_y=640;scene.render.resolution_percentage=100
    scene.world.color=(.28,.28,.28);scene.view_settings.view_transform='AgX'
    bpy.ops.object.camera_add(location=(.5,CY,.864));cam=bpy.context.object
    cam.rotation_euler=(Vector((.06,CY,.864))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=.165;scene.camera=cam
    for loc,power,size in [((.45,-.18,1.2),4,.3),((.3,.3,.9),2,.4)]:
        bpy.ops.object.light_add(type='AREA',location=loc);light=bpy.context.object;light.data.energy=power;light.data.size=size;light.rotation_euler=(Vector((.05,0,.86))-light.location).to_track_quat('-Z','Y').to_euler()
    previews={'neutral':{},'smile':{'mouthSmileLeft':.7,'mouthSmileRight':.7,'cheekSquintLeft':.3,'cheekSquintRight':.3},'laugh':{'jawOpen':.55,'mouthSmileLeft':.7,'mouthSmileRight':.7,'eyeSquintLeft':.35,'eyeSquintRight':.35},'blink':{'eyeBlinkLeft':1,'eyeBlinkRight':1},'pucker':{'mouthPucker':.75,'mouthFunnel':.2},'sad':{'browInnerUp':.6,'mouthFrownLeft':.6,'mouthFrownRight':.6},'three-quarter':{}}
    for name,values in previews.items():
        if name=='three-quarter':
            cam.location=(.45,-.23,.864);cam.rotation_euler=(Vector((.06,CY,.864))-cam.location).to_track_quat('-Z','Y').to_euler()
        for obj in scene.objects:
            if obj.type=='MESH' and obj.data.shape_keys:
                for key in obj.data.shape_keys.key_blocks:key.value=values.get(key.name,0)
        scene.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
    for obj in scene.objects:
        if obj.type=='MESH' and obj.data.shape_keys:
            for key in obj.data.shape_keys.key_blocks:key.value=0
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'cat-expressive.blend'))


if __name__=='__main__':main()
