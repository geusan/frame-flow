import {tongueShape,drawExtendedTongue} from './tongue-rig';
import {parseTongue,mouthContours,type MouthRig} from './mouth-rig';
import {traceLid} from './eyelid-rig';
import {FACE_CROP,type FacePoints,type RigFaceValues} from './face-rig';
import type {FeatureAlignment} from './feature-alignment';
export function drawMouth(ctx:CanvasRenderingContext2D,source:HTMLCanvasElement,rest:FacePoints,values:RigFaceValues,alignment:FeatureAlignment,rig:MouthRig){
 const c=mouthContours(rest,values,alignment,rig),sample=source.getContext('2d')!.getImageData((rest.philtrum[0]-420)*2,(rest.philtrum[1]-145)*2,1,1).data;
 const tonguePose=parseTongue(rig.tonguePose),tongue=tongueShape(c,tonguePose);
 ctx.save();ctx.scale(2,2);ctx.translate(-FACE_CROP.x,-FACE_CROP.y);
 // Erase the old neutral mouth only, before drawing the independently rigged aperture.
 const ox=(rest.mouthRight[0]+rest.mouthLeft[0])/2,oy=(rest.mouthUpper[1]+rest.mouthLower[1])/2;
 ctx.save();ctx.translate(ox,oy);ctx.scale((rest.mouthLeft[0]-rest.mouthRight[0])/2+4,5);const skin=ctx.createRadialGradient(0,0,.7,0,0,1);skin.addColorStop(0,`rgba(${sample[0]},${sample[1]},${sample[2]},1)`);skin.addColorStop(1,`rgba(${sample[0]},${sample[1]},${sample[2]},0)`);ctx.fillStyle=skin;ctx.fillRect(-1,-1,2,2);ctx.restore();
 if(c.aperture>.001){ctx.save();ctx.beginPath();traceLid(ctx,c.upper);traceLid(ctx,[...c.lower].reverse(),false);ctx.closePath();ctx.clip();const fill=ctx.createLinearGradient(0,c.cy-4,0,c.cy+13);fill.addColorStop(0,'#341b21');fill.addColorStop(1,'#823b48');ctx.fillStyle=fill;ctx.fillRect(c.cx-40,c.cy-15,80,45);
 if(rig.teeth){ctx.globalAlpha=1-c.funnel*.8;ctx.fillStyle='#f5e8d9';ctx.fillRect(c.cx-30,c.cy-4.5,60,4);if(c.lowerLift>.02)ctx.fillRect(c.cx-30,c.cy+c.jaw*9+.5,60,4);ctx.globalAlpha=1;}
 if(rig.tongue&&c.jaw>.05){ctx.fillStyle='#cc7880';ctx.beginPath();ctx.ellipse(tongue.rootX,tongue.rootY+.5+tonguePose.y*3,tongue.width*1.2,3,0,0,Math.PI*2);ctx.fill();}ctx.restore();}
 ctx.strokeStyle='#684333';ctx.lineWidth=(.65+c.press*.6+c.pucker*.4+c.shrugUpper*.4)*(1-.6*c.rollUpper);ctx.lineCap='round';ctx.beginPath();traceLid(ctx,c.upper);ctx.stroke();if(c.aperture>.01){ctx.strokeStyle='#956258';ctx.lineWidth=(.45+c.pucker*.35+c.shrugLower*.4)*(1-.6*c.rollLower);ctx.beginPath();traceLid(ctx,c.lower);ctx.stroke();}if(rig.tongue)drawExtendedTongue(ctx,tongue,tonguePose);ctx.restore();return c;
}
