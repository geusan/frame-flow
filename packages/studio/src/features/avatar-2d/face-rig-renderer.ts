import {drawMouth} from './mouth-renderer';
import {freshMouthRig,type MouthRig} from './mouth-rig';
import {freshEyelidRig,eyelidCurves,type EyelidRig} from './eyelid-rig';
import {freshBrowDetail,browControls,type BrowDetail} from './brow-detail';
import {RIG_HEAD_IMAGE} from './avatar-artwork';
import {BrowRenderer} from './brow-renderer';
import {alignFaceFeatures,DEFAULT_FEATURE_ALIGNMENT,type FeatureAlignment} from './feature-alignment';
import {characterEyes,characterFixation} from './eye-layout';
import {binocularGaze,projectEyeSurface} from './eye-projection';
import {LeftEyeRenderer,DEFAULT_EYE,type EyeAppearance} from './left-eye-renderer';
import * as THREE from 'three';
import {expressionRect,type ExpressionLibrary} from './expression-library';
import {FACE_CROP,FACE_POINT_IDS,FACE_POSE_IDS,FACE_CHANNELS_2D,FACE_MOTION_CHANNELS,RIG_CHANNEL_META,solveFacePoints,neutralRigFace,type FaceRig2D,type FacePoint,type FacePoseId,type RigFaceValues,pointRegion} from './face-rig';
import {triangulateFace,affineTriangle,safeFaceDeformation,type FaceTriangle} from './face-triangulation';

const SCALE=2;
const canvas=()=>{const c=document.createElement('canvas');c.width=FACE_CROP.width*SCALE;c.height=FACE_CROP.height*SCALE;return c;};
const local=(p:FacePoint):FacePoint=>[(p[0]-FACE_CROP.x)*SCALE,(p[1]-FACE_CROP.y)*SCALE];
/** All source textures are warped to ONE interpolated landmark mesh before compositing. */
export class FaceRigRenderer {
  readonly canvas=canvas();readonly texture=new THREE.CanvasTexture(this.canvas);
  ready=false;limited=false;
  private featureAlignment={...DEFAULT_FEATURE_ALIGNMENT};
  setFeatureAlignment(value:FeatureAlignment){this.featureAlignment=value;this.lastSignature="";this.render(this.currentValues,performance.now(),true);}
  private mouthRig=freshMouthRig();
  setMouthRig(value:MouthRig){this.mouthRig=value;this.lastSignature="";this.render(this.currentValues,performance.now(),true);}
  private eyelidRig=freshEyelidRig();
  setEyelidRig(value:EyelidRig){this.eyelidRig=value;this.lastSignature="";this.render(this.currentValues,performance.now(),true);}
  private browDetail=freshBrowDetail();
  setBrowDetail(value:BrowDetail){this.browDetail=value;this.lastSignature="";this.render(this.currentValues,performance.now(),true);}
  private brows=new BrowRenderer();
  private leftEye=new LeftEyeRenderer();
  private eyeAppearance={...DEFAULT_EYE};
  setEyeAppearance(value:EyeAppearance){this.eyeAppearance=value;this.lastSignature="";this.render(this.currentValues,performance.now(),true);}
  private debug=false;
  setDebug(enabled:boolean){if(this.debug===enabled)return;this.debug=enabled;this.lastSignature="";this.render(this.currentValues,performance.now(),true);}
  private profile:FaceRig2D|null=null;
  private plates=new Map<FacePoseId,HTMLCanvasElement>();
  private warped=new Map<FacePoseId,HTMLCanvasElement>();
  private cache=new Map<string,Promise<HTMLCanvasElement>>();
  private triangles:FaceTriangle[]=[];private revision=0;private disposed=false;private last=0;
  private lastSignature='';private currentValues=neutralRigFace();
  constructor(){this.texture.colorSpace=THREE.SRGBColorSpace;this.texture.generateMipmaps=false;this.texture.minFilter=THREE.LinearFilter;}
  async configure(profile:FaceRig2D,library:ExpressionLibrary){
    const revision=++this.revision;
    await Promise.all([this.leftEye.load(),this.brows.load()]);
    const images=await Promise.all(FACE_POSE_IDS.map(async pose=>{
      const entry=library.entries.find(e=>e.id===profile.poses[pose].imageId);if(!entry)throw new Error(`${pose} 기준 이미지가 없습니다. 제작 자료 연결을 확인하세요.`);
      const rect=pose==='neutral'?[0,0,1024,1536]:expressionRect(entry),imageUrl=pose==='neutral'?RIG_HEAD_IMAGE:entry.image,key=JSON.stringify([imageUrl,rect]);
      if(!this.cache.has(key)){this.cache.set(key,(async()=>{const image=new Image();image.src=imageUrl;await image.decode();const c=canvas(),ctx=c.getContext('2d')!;ctx.drawImage(image,(rect[0]-FACE_CROP.x)*SCALE,(rect[1]-FACE_CROP.y)*SCALE,rect[2]*SCALE,rect[3]*SCALE);return c;})().catch(error=>{this.cache.delete(key);throw error;}));}
      return [pose,await this.cache.get(key)!] as const;
    }));
    if(this.disposed||revision!==this.revision)return;
    this.profile=profile;this.plates=new Map(images);this.triangles=triangulateFace(FACE_POINT_IDS.map(id=>profile.poses.neutral.points[id]));
    FACE_POSE_IDS.forEach(id=>{if(!this.warped.has(id))this.warped.set(id,canvas());});this.ready=true;this.last=0;this.lastSignature='';this.render(this.currentValues,performance.now(),true);
  }
  private warp(pose:FacePoseId,points:FacePoint[]){
    const c=this.warped.get(pose)!,ctx=c.getContext('2d')!,source=this.plates.get(pose)!;
    const from=FACE_POINT_IDS.map(id=>local(this.profile!.poses[pose].points[id])),to=points.map(local);
    ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(source,0,0);
    for(const t of this.triangles){const target=t.map(i=>to[i]),matrix=affineTriangle(t.map(i=>from[i]),target);if(!matrix)continue;
      const center:FacePoint=[target.reduce((s,p)=>s+p[0],0)/3,target.reduce((s,p)=>s+p[1],0)/3];
      ctx.save();ctx.beginPath();target.forEach((p,i)=>{const x=p[0]+(p[0]-center[0])*.006,y=p[1]+(p[1]-center[1])*.006;if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);});ctx.closePath();ctx.clip();ctx.setTransform(...matrix);ctx.drawImage(source,0,0);ctx.restore();
    }
    return c;
  }
  render(values:RigFaceValues,now:number,force=false){
    this.currentValues=values;
    if(!this.ready||!this.profile||(!force&&now-this.last<1000/24))return;this.last=now;
    const signature=FACE_MOTION_CHANNELS.map(k=>Math.round(values[k]*1000)).join(',');if(!force&&signature===this.lastSignature)return;this.lastSignature=signature;
    const meshValues={...values};if(this.eyeAppearance.enabled)for(const key of FACE_CHANNELS_2D)if(RIG_CHANNEL_META[key].regions.some(r=>r==='leftEye'||r==='rightEye'))meshValues[key]=0;
    const layout=characterEyes(this.profile.poses.neutral.points,this.eyeAppearance.enabled?this.eyeAppearance.spacing:1);
    const solved=alignFaceFeatures(this.profile.poses.neutral.points,solveFacePoints(this.profile,meshValues),layout,this.featureAlignment),rest=FACE_POINT_IDS.map(id=>this.profile!.poses.neutral.points[id]);
    // Eyebrow control points drive only the separate sprite, never the face/hair mesh.
    const browTargets=structuredClone(solved);
    for(const id of FACE_POINT_IDS)if(id.includes('Brow')||id.startsWith('mouth'))solved[id]=[...this.profile.poses.neutral.points[id]];
    const safe=safeFaceDeformation(rest,FACE_POINT_IDS.map(id=>solved[id]),this.triangles);this.limited=safe.limited;
    const base=this.warp('neutral',safe.points),ctx=this.canvas.getContext('2d')!;ctx.clearRect(0,0,this.canvas.width,this.canvas.height);ctx.drawImage(base,0,0);
    if(this.eyeAppearance.enabled){
      const gaze=binocularGaze(values),layout=characterEyes(this.profile.poses.neutral.points,this.eyeAppearance.spacing),fixation=characterFixation(layout,gaze.x,gaze.y,this.eyeAppearance.focusDistance),source=this.plates.get('neutral')!.getContext('2d')!;
      for(const side of ['left','right'] as const){
        const mirror=side==='right',gx=mirror?-gaze.x:gaze.x;
        const eyeValues={...values,eyeSquintLeft:mirror?values.eyeSquintRight:values.eyeSquintLeft,eyeBlinkLeft:mirror?values.eyeBlinkRight:values.eyeBlinkLeft,eyeWideLeft:mirror?values.eyeWideRight:values.eyeWideLeft,eyeLookOutLeft:Math.max(0,gx),eyeLookInLeft:Math.max(0,-gx),eyeLookDownLeft:Math.max(0,gaze.y),eyeLookUpLeft:Math.max(0,-gaze.y)};
        const eye=this.leftEye.render(eyeValues,this.eyeAppearance,{yaw:mirror?-fixation[side].yaw:fixation[side].yaw,pitch:fixation[side].pitch},this.eyelidRig[side]);if(!eye)continue;
        const cx=mirror?465:550,placement=layout[side];
        const sample=source.getImageData(...local([mirror?466:545,218]),1,1).data;
        ctx.save();ctx.translate(...local([cx,198]));ctx.scale(26*SCALE,21*SCALE);
        const fill=ctx.createRadialGradient(0,0,.82,0,0,1);fill.addColorStop(0,`rgba(${sample[0]},${sample[1]},${sample[2]},1)`);fill.addColorStop(1,`rgba(${sample[0]},${sample[1]},${sample[2]},0)`);ctx.fillStyle=fill;ctx.fillRect(-1,-1,2,2);ctx.restore();
        ctx.save();if(mirror){ctx.translate((placement.x+placement.width-FACE_CROP.x)*SCALE,(placement.y-FACE_CROP.y)*SCALE);ctx.scale(-1,1);}else ctx.translate((placement.x-FACE_CROP.x)*SCALE,(placement.y-FACE_CROP.y)*SCALE);ctx.drawImage(eye,0,0,placement.width*SCALE,placement.height*SCALE);ctx.restore();
      }
    }
    const mouth=drawMouth(ctx,this.plates.get("neutral")!,this.profile.poses.neutral.points,values,this.featureAlignment,this.mouthRig);
    if(this.featureAlignment.browVisible)this.brows.draw(ctx,browTargets,this.featureAlignment.browThickness,this.browDetail,alignFaceFeatures(this.profile.poses.neutral.points,this.profile.poses.neutral.points,layout,this.featureAlignment));
    if(this.debug){
      for(const id of FACE_POINT_IDS)if(id.includes("Brow"))safe.points[FACE_POINT_IDS.indexOf(id)]=browTargets[id];
      if(this.eyeAppearance.enabled){
        const gaze=binocularGaze(values),layout=characterEyes(this.profile.poses.neutral.points,this.eyeAppearance.spacing),fixation=characterFixation(layout,gaze.x,gaze.y,this.eyeAppearance.focusDistance);
        for(const side of ['left','right'] as const){const mirror=side==='right',p=projectEyeSurface(0,0,mirror?-gaze.x:gaze.x,gaze.y,350,{yaw:mirror?-fixation[side].yaw:fixation[side].yaw,pitch:fixation[side].pitch}),placement=layout[side];
          safe.points[FACE_POINT_IDS.indexOf(`${side}Iris`)]=[placement.x+(mirror?1000-p.x:p.x)*placement.width/1000,placement.y+p.y*placement.height/600];
          const b=mirror?values.eyeBlinkRight:values.eyeBlinkLeft,h=330*(1-b),top=340-h*.64;
          safe.points[FACE_POINT_IDS.indexOf(`${side}EyeUpper`)]=[placement.center.x,placement.y+top*placement.height/600];safe.points[FACE_POINT_IDS.indexOf(`${side}EyeLower`)]=[placement.center.x,placement.y+(top+h)*placement.height/600];
        }
      }
      ctx.save();ctx.lineWidth=.55;ctx.strokeStyle='#50dbe6aa';
      for(const t of this.triangles){ctx.beginPath();t.forEach((index,i)=>{const p=local(safe.points[index]);if(i)ctx.lineTo(...p);else ctx.moveTo(...p);});ctx.closePath();ctx.stroke();}
      for(let i=0;i<FACE_POINT_IDS.length;i++){const id=FACE_POINT_IDS[i];if(id.startsWith('frame')||id.includes('Brow'))continue;const p=local(safe.points[i]),origin=local(rest[i]);
        ctx.strokeStyle='#ffffff99';ctx.beginPath();ctx.moveTo(...origin);ctx.lineTo(...p);ctx.stroke();
        const region=pointRegion(id);ctx.fillStyle=id.includes('Iris')?'#77f58d':region==='mouth'?'#ffbe5c':region?.includes('Brow')?'#ef96ff':'#55e3fa';
        ctx.beginPath();ctx.arc(...p,1.65,0,Math.PI*2);ctx.fill();
      }
      if(this.eyeAppearance.enabled){const eyes=characterEyes(this.profile.poses.neutral.points,this.eyeAppearance.spacing);for(const side of ['left','right'] as const){const placement=eyes[side],curves=eyelidCurves(values[side==='left'?'eyeBlinkLeft':'eyeBlinkRight'],values[side==='left'?'eyeWideLeft':'eyeWideRight'],this.eyelidRig[side],values[side==='left'?'eyeSquintLeft':'eyeSquintRight']);for(const p of [...curves.upper,...curves.lower]){ctx.fillStyle='#55e3fa';ctx.beginPath();ctx.arc(...local([placement.x+(side==='right'?1000-p[0]:p[0])*placement.width/1000,placement.y+p[1]*placement.height/600]),1.3,0,Math.PI*2);ctx.fill();}}}
      for(const p of [...mouth.upper,...mouth.lower]){ctx.fillStyle="#ffbe5c";ctx.beginPath();ctx.arc(...local(p),1.3,0,Math.PI*2);ctx.fill();}
      const browNeutral=alignFaceFeatures(this.profile.poses.neutral.points,this.profile.poses.neutral.points,layout,this.featureAlignment);
      for(const side of ['left','right'] as const)for(const p of browControls(browTargets,browNeutral,side,this.browDetail)){ctx.fillStyle='#ef96ff';ctx.beginPath();ctx.arc(...local(p),1.8,0,Math.PI*2);ctx.fill();}
      ctx.restore();
    }
    this.texture.needsUpdate=true;
  }
  dispose(){this.disposed=true;this.revision++;this.texture.dispose();this.cache.clear();this.plates.clear();this.warped.clear();}
}
