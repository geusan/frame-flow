/** Image-supervised 2D face rig. No GLB, expression classification or body rig dependency. */
export type FacePoint = [number, number];
export const FACE_CROP = { x: 420, y: 145, width: 180, height: 145 };
export const FACE_POINT_DEFAULTS = {
  frameTL:[420,145],frameTM:[508,145],frameTR:[600,145],frameRM:[600,218],frameBR:[600,290],frameBM:[508,290],frameBL:[420,290],frameLM:[420,218],
  rightBrowOuter:[447,172],rightBrowMid:[463,169],rightBrowInner:[484,178],
  leftBrowInner:[529,176],leftBrowMid:[549,167],leftBrowOuter:[568,172],
  rightEyeOuter:[443,193],rightEyeUpper:[463,187],rightEyeInner:[485,195],rightEyeLower:[466,209],rightIris:[468,198],
  leftEyeInner:[529,195],leftEyeUpper:[548,186],leftEyeOuter:[570,192],leftEyeLower:[548,209],leftIris:[546,198],
  nose:[507,226],bridge:[507,187],chin:[507,278],
  mouthRight:[497,251],mouthUpper:[507,249],mouthLeft:[518,251],mouthLower:[507,251.8],mouthInnerUpper:[507,250],mouthInnerLower:[507,250.8],
  cheekRight:[453,232],cheekLeft:[563,232],philtrum:[507,234],
} satisfies Record<string,FacePoint>;
export type FacePointId = keyof typeof FACE_POINT_DEFAULTS;
export type FacePoints = Record<FacePointId,FacePoint>;
export const FACE_POINT_IDS = Object.keys(FACE_POINT_DEFAULTS) as FacePointId[];
export const editableFacePoints = FACE_POINT_IDS.filter(id=>!id.startsWith('frame'));
export const FACE_POINT_LABELS: Record<FacePointId,string> = {
  frameTL:'영역 좌상',frameTM:'영역 상단',frameTR:'영역 우상',frameRM:'영역 오른쪽',frameBR:'영역 우하',frameBM:'영역 하단',frameBL:'영역 좌하',frameLM:'영역 왼쪽',
  rightBrowOuter:'오른쪽 눈썹 바깥',rightBrowMid:'오른쪽 눈썹 중앙',rightBrowInner:'오른쪽 눈썹 안쪽',leftBrowOuter:'왼쪽 눈썹 바깥',leftBrowMid:'왼쪽 눈썹 중앙',leftBrowInner:'왼쪽 눈썹 안쪽',
  rightEyeOuter:'오른눈 바깥',rightEyeUpper:'오른눈 위',rightEyeInner:'오른눈 안쪽',rightEyeLower:'오른눈 아래',rightIris:'오른쪽 눈동자',
  leftEyeOuter:'왼눈 바깥',leftEyeUpper:'왼눈 위',leftEyeInner:'왼눈 안쪽',leftEyeLower:'왼눈 아래',leftIris:'왼쪽 눈동자',
  nose:'코',bridge:'미간',chin:'턱 끝',mouthRight:'오른쪽 입꼬리',mouthUpper:'윗입술',mouthLeft:'왼쪽 입꼬리',mouthLower:'아랫입술',mouthInnerUpper:'입 안쪽 위',mouthInnerLower:'입 안쪽 아래',cheekRight:'오른쪽 볼',cheekLeft:'왼쪽 볼',philtrum:'인중',
};
export const FACE_POSE_IDS = ['neutral','smile','laugh','surprise','sad','angry','wink','open'] as const;
export type FacePoseId = typeof FACE_POSE_IDS[number];
export type FaceRegion = 'leftEye'|'rightEye'|'leftBrow'|'rightBrow'|'mouth';
export const FACE_CHANNELS_2D = ['eyeBlinkLeft','eyeBlinkRight','eyeWideLeft','eyeWideRight','jawOpen','mouthSmileLeft','mouthSmileRight','mouthFrownLeft','mouthFrownRight','browInnerUp','browDownLeft','browDownRight','eyeLookInLeft','eyeLookOutLeft','eyeLookUpLeft','eyeLookDownLeft','eyeLookInRight','eyeLookOutRight','eyeLookUpRight','eyeLookDownRight'] as const;
export type RigChannel = typeof FACE_CHANNELS_2D[number];
export const UPPER_LIP_CHANNELS=['mouthUpperUpLeft','mouthUpperUpRight'] as const;
export const EXTRA_MOUTH_CHANNELS=[...UPPER_LIP_CHANNELS,'mouthLowerDownLeft','mouthLowerDownRight','mouthPucker','mouthFunnel','mouthPressLeft','mouthPressRight','mouthRollUpper','mouthRollLower','mouthStretchLeft','mouthStretchRight'] as const;
export const REMAINING_FACE_CHANNELS=['browOuterUpLeft','browOuterUpRight','eyeSquintLeft','eyeSquintRight','jawForward','jawLeft','jawRight','mouthClose','mouthDimpleLeft','mouthDimpleRight','mouthLeft','mouthRight','mouthShrugLower','mouthShrugUpper','cheekPuff','cheekSquintLeft','cheekSquintRight','noseSneerLeft','noseSneerRight'] as const;
export const ADDITIONAL_FACE_CHANNELS=[...EXTRA_MOUTH_CHANNELS,...REMAINING_FACE_CHANNELS] as const;
export const FACE_MOTION_CHANNELS=[...FACE_CHANNELS_2D,...ADDITIONAL_FACE_CHANNELS] as const;
export type FaceMotionChannel=typeof FACE_MOTION_CHANNELS[number];
export type RigFaceValues = Record<FaceMotionChannel,number>;
export const RIG_CHANNEL_META: Record<RigChannel,{label:string;pose:FacePoseId;regions:FaceRegion[];gaze?:boolean}> = {
  eyeBlinkLeft:{label:'왼눈 감기',pose:'wink',regions:['leftEye']},eyeBlinkRight:{label:'오른눈 감기',pose:'laugh',regions:['rightEye']},
  eyeWideLeft:{label:'왼눈 크게 뜨기',pose:'surprise',regions:['leftEye']},eyeWideRight:{label:'오른눈 크게 뜨기',pose:'surprise',regions:['rightEye']},
  jawOpen:{label:'입 벌리기',pose:'open',regions:['mouth']},mouthSmileLeft:{label:'왼쪽 미소',pose:'smile',regions:['mouth']},mouthSmileRight:{label:'오른쪽 미소',pose:'smile',regions:['mouth']},
  mouthFrownLeft:{label:'왼쪽 입꼬리 내리기',pose:'sad',regions:['mouth']},mouthFrownRight:{label:'오른쪽 입꼬리 내리기',pose:'sad',regions:['mouth']},
  browInnerUp:{label:'눈썹 안쪽 올리기',pose:'sad',regions:['leftBrow','rightBrow']},browDownLeft:{label:'왼쪽 눈썹 내리기',pose:'angry',regions:['leftBrow']},browDownRight:{label:'오른쪽 눈썹 내리기',pose:'angry',regions:['rightBrow']},
  eyeLookInLeft:{label:'왼눈 시선 안쪽',pose:'neutral',regions:['leftEye'],gaze:true},eyeLookOutLeft:{label:'왼눈 시선 바깥',pose:'neutral',regions:['leftEye'],gaze:true},eyeLookUpLeft:{label:'왼눈 시선 위',pose:'neutral',regions:['leftEye'],gaze:true},eyeLookDownLeft:{label:'왼눈 시선 아래',pose:'neutral',regions:['leftEye'],gaze:true},
  eyeLookInRight:{label:'오른눈 시선 안쪽',pose:'neutral',regions:['rightEye'],gaze:true},eyeLookOutRight:{label:'오른눈 시선 바깥',pose:'neutral',regions:['rightEye'],gaze:true},eyeLookUpRight:{label:'오른눈 시선 위',pose:'neutral',regions:['rightEye'],gaze:true},eyeLookDownRight:{label:'오른눈 시선 아래',pose:'neutral',regions:['rightEye'],gaze:true},
};
export interface FaceRig2D {
  schema_version:'avatar.face_rig2d.v1';asset:'cat-2d-v1';source_sha256:string;
  poses:Record<FacePoseId,{imageId:string;points:FacePoints}>;
  channels:Record<RigChannel,{pose:FacePoseId;gain:number;deadzone:number;max:number;enabled:boolean}>;
  smoothing:number;
}
const unit=(n:number)=>Number.isFinite(n)?Math.max(0,Math.min(1,n)):0;
export const neutralRigFace=():RigFaceValues=>Object.fromEntries(FACE_MOTION_CHANNELS.map(k=>[k,0])) as RigFaceValues;
export function freshFaceRig(sourceSha:string):FaceRig2D {
  const poses=Object.fromEntries(FACE_POSE_IDS.map(id=>[id,{imageId:id,points:structuredClone(FACE_POINT_DEFAULTS)}])) as FaceRig2D['poses'];
  Object.assign(poses.smile.points,{mouthRight:[493,247],mouthUpper:[507,250],mouthLeft:[521,246],mouthLower:[507,253],mouthInnerUpper:[507,251],mouthInnerLower:[507,252]});
  Object.assign(poses.laugh.points,{rightEyeOuter:[445,199],rightEyeUpper:[463,192],rightEyeInner:[484,200],rightEyeLower:[464,195],rightIris:[468,194],leftEyeInner:[530,199],leftEyeUpper:[548,191],leftEyeOuter:[570,199],leftEyeLower:[548,194],leftIris:[546,193],mouthRight:[490,242],mouthUpper:[508,238],mouthLeft:[526,241],mouthLower:[508,264],mouthInnerUpper:[508,243],mouthInnerLower:[508,260]});
  Object.assign(poses.surprise.points,{rightEyeUpper:[463,182],rightEyeLower:[466,210],leftEyeUpper:[548,181],leftEyeLower:[548,210],mouthRight:[501,250],mouthUpper:[508,243],mouthLeft:[515,250],mouthLower:[508,257],mouthInnerUpper:[508,246],mouthInnerLower:[508,254]});
  Object.assign(poses.sad.points,{rightBrowOuter:[447,179],rightBrowMid:[463,175],rightBrowInner:[484,166],leftBrowInner:[529,165],leftBrowMid:[549,174],leftBrowOuter:[568,178],mouthRight:[496,253],mouthUpper:[507,249],mouthLeft:[518,253],mouthLower:[507,253],mouthInnerUpper:[507,250],mouthInnerLower:[507,252]});
  Object.assign(poses.angry.points,{rightBrowOuter:[446,170],rightBrowMid:[464,177],rightBrowInner:[485,185],leftBrowInner:[529,184],leftBrowMid:[548,176],leftBrowOuter:[570,169]});
  Object.assign(poses.wink.points,structuredClone(poses.smile.points),{leftEyeInner:[530,200],leftEyeUpper:[548,192],leftEyeOuter:[570,199],leftEyeLower:[548,195],leftIris:[546,194]});
  poses.open.imageId='mouth-open';Object.assign(poses.open.points,{mouthRight:[499,254],mouthUpper:[507,246],mouthLeft:[515,254],mouthLower:[507,264],mouthInnerUpper:[507,250],mouthInnerLower:[507,261]});
  return {schema_version:'avatar.face_rig2d.v1',asset:'cat-2d-v1',source_sha256:sourceSha,poses,smoothing:.085,channels:Object.fromEntries(FACE_CHANNELS_2D.map(k=>[k,{pose:RIG_CHANNEL_META[k].pose,gain:1.4,deadzone:.025,max:1,enabled:true}])) as FaceRig2D['channels']};
}
export function parseFaceRig(value:unknown,sourceSha:string):FaceRig2D {
  const p=value as FaceRig2D;
  if(!p || p.schema_version!=='avatar.face_rig2d.v1' || p.asset!=='cat-2d-v1' || p.source_sha256!==sourceSha || !p.poses || !p.channels)throw new Error('이 원화에 맞는 얼굴 리그 파일이 아닙니다.');
  if(p.poses.neutral?.imageId!=='neutral')throw new Error('원본 기준 이미지는 유지해야 합니다.');
  if(!Number.isFinite(p.smoothing)||p.smoothing<.02||p.smoothing>.4)throw new Error('떨림 완화 범위를 확인하세요.');
  for(const poseId of FACE_POSE_IDS){
    const pose=p.poses[poseId];if(!pose || typeof pose.imageId!=='string' || pose.imageId.length>80 || !pose.points)throw new Error('표정 이미지와 기준점이 누락됐습니다.');
    for(const id of FACE_POINT_IDS){const q=pose.points[id];if(!Array.isArray(q)||q.length!==2||q.some(n=>!Number.isFinite(n))||q[0]<420||q[0]>600||q[1]<145||q[1]>290)throw new Error('얼굴 기준점이 편집 영역 밖에 있습니다.');if(id.startsWith('frame')&&q.some((n,i)=>n!==FACE_POINT_DEFAULTS[id][i]))throw new Error('얼굴 외곽 고정점은 이동할 수 없습니다.');}
    if(new Set(FACE_POINT_IDS.map(id=>pose.points[id].join(','))).size!==FACE_POINT_IDS.length)throw new Error('서로 다른 기준점이 겹치지 않게 배치하세요.');
    for(const side of ['left','right'] as const)if(pose.points[`${side}EyeUpper`][1]+.5>=pose.points[`${side}EyeLower`][1])throw new Error('눈 위·아래 기준점 사이에 간격을 두세요.');
    if(pose.points.mouthInnerUpper[1]+.5>=pose.points.mouthInnerLower[1]||pose.points.mouthRight[0]+5>=pose.points.mouthLeft[0])throw new Error('입 기준점의 순서와 간격을 확인하세요.');
  }
  for(const key of FACE_CHANNELS_2D){const c=p.channels[key];if(!c||!FACE_POSE_IDS.includes(c.pose)||typeof c.enabled!=='boolean'||!Number.isFinite(c.gain)||c.gain<0||c.gain>5||!Number.isFinite(c.deadzone)||c.deadzone<0||c.deadzone>.4||!Number.isFinite(c.max)||c.max<0||c.max>1)throw new Error('웹캠 표정 연결 설정을 확인하세요.');}
  return structuredClone(p);
}
export function pointRegion(id:FacePointId):FaceRegion|null {
  if(id.startsWith('leftEye')||id==='leftIris')return 'leftEye';if(id.startsWith('rightEye')||id==='rightIris')return 'rightEye';
  if(id.startsWith('leftBrow'))return 'leftBrow';if(id.startsWith('rightBrow'))return 'rightBrow';if(id.startsWith('mouth'))return 'mouth';return null;
}
export function pointChannelWeight(id:FacePointId,key:RigChannel,point:FacePoint):number {
  if(RIG_CHANNEL_META[key].gaze)return 0;
  const region=pointRegion(id);if(!region||!RIG_CHANNEL_META[key].regions.includes(region))return 0;
  if(region==='mouth'&&key!=='jawOpen'){const left=id==='mouthLeft'?1:id==='mouthRight'?0:(point[0]-487)/40;return unit(key.endsWith('Left')?left:1-left);}
  if(key==='browInnerUp')return id.endsWith('Inner')?1:id.endsWith('Mid')?.5:0;
  return 1;
}
export function solveFacePoints(profile:FaceRig2D,values:RigFaceValues):FacePoints {
  const rest=profile.poses.neutral.points;
  const result=Object.fromEntries(FACE_POINT_IDS.map(id=>{
    let dx=0,dy=0,total=0,jawX=0,jawY=0;
    for(const key of FACE_CHANNELS_2D){if(!profile.channels[key].enabled)continue;const w=unit(values[key])*pointChannelWeight(id,key,rest[id]);const target=profile.poses[profile.channels[key].pose].points[id];if(key==='jawOpen'){jawX=(target[0]-rest[id][0])*w;jawY=(target[1]-rest[id][1])*w;}else{dx+=(target[0]-rest[id][0])*w;dy+=(target[1]-rest[id][1])*w;total+=w;}}
    return [id,[rest[id][0]+jawX+dx/Math.max(1,total),rest[id][1]+jawY+dy/Math.max(1,total)]];
  })) as FacePoints;
  for(const side of ['Left','Right'] as const){
    const prefix=side==='Left'?'left':'right';result[`${prefix}BrowOuter`][1]-=6*unit(values[`browOuterUp${side}`]??0);result[`${prefix}BrowMid`][1]-=2*unit(values[`browOuterUp${side}`]??0);
    const name=side==='Left'?'left':'right',iris=result[`${name}Iris`],fade=1-unit(values[`eyeBlink${side}`]);
    const value=(key:RigChannel)=>profile.channels[key].enabled?unit(values[key]):0;
    const dx=(value(`eyeLookOut${side}`)-value(`eyeLookIn${side}`))*(side==='Left'?1:-1)*4*fade;
    const dy=(value(`eyeLookDown${side}`)-value(`eyeLookUp${side}`))*3*fade;
    iris[0]+=dx;iris[1]+=dy;
  }
  const puff=unit(values.cheekPuff??0),jawX=5*(unit(values.jawLeft??0)-unit(values.jawRight??0)),forward=unit(values.jawForward??0);
  result.chin[0]+=jawX;result.chin[1]+=forward*2;
  result.cheekLeft[0]+=puff*4+forward;result.cheekRight[0]-=puff*4+forward;
  result.cheekLeft[1]-=3*unit(values.cheekSquintLeft??0)+unit(values.noseSneerLeft??0);result.cheekRight[1]-=3*unit(values.cheekSquintRight??0)+unit(values.noseSneerRight??0);
  result.nose[0]+=.8*(unit(values.noseSneerLeft??0)-unit(values.noseSneerRight??0));result.nose[1]-=1.5*Math.max(unit(values.noseSneerLeft??0),unit(values.noseSneerRight??0));
  return result;
}
export function solveFaceValues(raw:Record<string,number>,baseline:Record<string,number>,profile:FaceRig2D):RigFaceValues {
  const result=neutralRigFace();for(const key of FACE_CHANNELS_2D){const c=profile.channels[key];if(!c.enabled||!Number.isFinite(raw[key]))continue;const base=unit(baseline[key]??0);const v=Math.max(0,(unit(raw[key])-base)/Math.max(.12,1-base));result[key]=Math.min(c.max,unit((v-c.deadzone)/(1-c.deadzone)*c.gain));}
  for(const key of ADDITIONAL_FACE_CHANNELS){const base=unit(baseline[key]??0),v=Math.max(0,(unit(raw[key]??0)-base)/Math.max(.12,1-base));result[key]=unit((v-.025)/.975*1.4);}
  result.eyeWideLeft*=1-result.eyeBlinkLeft;result.eyeWideRight*=1-result.eyeBlinkRight;
  return result;
}
export function smoothRigFace(current:RigFaceValues,target:RigFaceValues,dt:number,seconds:number):RigFaceValues {
  const a=1-Math.exp(-Math.max(0,Math.min(.1,dt))/Math.max(.02,seconds));return Object.fromEntries(FACE_MOTION_CHANNELS.map(k=>[k,unit(current[k])+(unit(target[k])-unit(current[k]))*a])) as RigFaceValues;
}
export class FaceRigCapture {
  raw:Record<string,number>={};baseline:Record<string,number>={};lastSeen=-Infinity;detected=false;
  samples:Record<string,number>[]|null=null;calibration:'neutral'|RigChannel='neutral';message='웹캠 연결 후 무표정을 보정하세요.';started=0;
  receive(values:Record<string,number>,hasFace:boolean,now:number,profile:FaceRig2D):Partial<FaceRig2D['channels']>|null {
    this.detected=hasFace&&FACE_MOTION_CHANNELS.some(k=>Number.isFinite(values[k]));this.raw=this.detected?values:{};
    if(!this.detected)return null;this.lastSeen=now;
    if(!this.samples)return null;
    this.samples.push({...values});if(this.samples.length<24)return null;
    const samples=this.samples;this.samples=null;
    if(this.calibration==='neutral'){this.baseline=Object.fromEntries(FACE_MOTION_CHANNELS.map(k=>[k,samples.reduce((sum,s)=>sum+unit(s[k]??0),0)/samples.length]));this.message='무표정 보정 완료. 눈과 입을 움직여 보세요.';return null;}
    const key=this.calibration,base=unit(this.baseline[key]??0);const ordered=samples.map(s=>unit(s[key]??0)).sort((a,b)=>a-b),peak=ordered[Math.floor(ordered.length*.9)];
    if(peak-base<.12){this.message='움직임이 충분히 감지되지 않았습니다. 해당 표정을 더 크게 지어 다시 보정하세요.';return null;}
    this.message=`${RIG_CHANNEL_META[key].label} 최대값 보정 완료.`;return {[key]:{...profile.channels[key],gain:Math.min(5,(1-base)/(peak-base))}};
  }
  begin(mode:'neutral'|RigChannel,now:number){this.calibration=mode;this.samples=[];this.started=now;this.message=mode==='neutral'?'눈을 뜨고 입을 다문 채 정면을 바라봐 주세요.':`${RIG_CHANNEL_META[mode].label} 표정을 크게 유지해 주세요.`;}
  target(now:number,profile:FaceRig2D){if(this.samples&&now-this.started>8000){this.samples=null;this.message='얼굴 감지가 부족해 보정을 종료했습니다. 다시 시도하세요.';}return this.detected&&now-this.lastSeen<500?solveFaceValues(this.raw,this.baseline,profile):neutralRigFace();}
  reset(){this.raw={};this.baseline={};this.lastSeen=-Infinity;this.detected=false;this.samples=null;this.message='웹캠 연결 후 무표정을 보정하세요.';}
}
export const MEDIAPIPE_FACE_POINTS:Partial<Record<FacePointId,number>>={rightEyeOuter:33,rightEyeInner:133,rightEyeUpper:159,rightEyeLower:145,rightIris:468,leftEyeOuter:263,leftEyeInner:362,leftEyeUpper:386,leftEyeLower:374,leftIris:473,rightBrowOuter:70,rightBrowMid:63,rightBrowInner:107,leftBrowOuter:300,leftBrowMid:296,leftBrowInner:336,mouthRight:61,mouthLeft:291,mouthUpper:0,mouthLower:17,mouthInnerUpper:13,mouthInnerLower:14,nose:1,chin:152};
