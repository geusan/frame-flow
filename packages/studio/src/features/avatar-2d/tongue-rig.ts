import type {TonguePose} from './mouth-rig';
export function tongueShape(mouth:{cx:number;cy:number;jaw:number;aperture:number;lower:[number,number][]},pose:TonguePose){
 const gate=Math.min(1,Math.max(0,mouth.aperture/3)),width=(mouth.lower[8][0]-mouth.lower[0][0])*.22*gate;
 const rootX=mouth.cx+pose.x*width*.6,rootY=mouth.lower[4][1]-.8;
 return {gate,width,rootX,rootY,tipX:rootX+pose.x*3*pose.out*gate,tipY:rootY+pose.y*3+pose.out*9*gate-pose.curl*3*pose.out,extension:pose.out*gate};
}
export function drawExtendedTongue(ctx:CanvasRenderingContext2D,s:ReturnType<typeof tongueShape>,pose:TonguePose){
 if(s.gate<=0||s.extension<=.01)return;const w=s.width*(.65+.2*s.extension);ctx.save();ctx.globalAlpha=s.gate;ctx.beginPath();ctx.moveTo(s.rootX-w,s.rootY-1);ctx.bezierCurveTo(s.rootX-w,s.rootY+3,s.tipX-w,s.tipY+3,s.tipX,s.tipY+3);ctx.bezierCurveTo(s.tipX+w,s.tipY+3,s.rootX+w,s.rootY+3,s.rootX+w,s.rootY-1);ctx.closePath();const color=ctx.createLinearGradient(0,s.rootY-2,0,s.tipY+4);color.addColorStop(0,'#a95768');color.addColorStop(1,'#dc8b98');ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#995564';ctx.lineWidth=.35;ctx.stroke();ctx.beginPath();ctx.moveTo(s.rootX,s.rootY+.8);ctx.quadraticCurveTo(s.tipX,s.tipY-1-pose.curl,s.tipX,s.tipY+1);ctx.stroke();ctx.restore();
}
