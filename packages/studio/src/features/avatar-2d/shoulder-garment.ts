import type { ArtPart } from "./parts";

// Authored tank-top boundary, including the inner edge of the black neckline.
// Hair is already partitioned out before this surface is extracted.
export const SHOULDER_GARMENT: ArtPart = {
  id:"shoulder-garment",paint:"body",chain:["root","chest","neck"],depth:40,radius:128,
  polygon:[[435,315],[454,312],[455,342],[459,357],[467,367],[482,376],[498,378],[517,379],[537,376],[550,366],[557,352],[559,334],[557,313],[580,312],[586,346],[596,379],[608,400],[611,425],[608,446],[596,477],[586,504],[586,541],[558,551],[516,554],[475,552],[437,547],[430,538],[433,504],[421,477],[409,451],[407,423],[411,399],[424,369],[430,338]],
};

/** Runtime surfaces: original clothing above an underpainted shoulder surface.
 * No image is regenerated or saved. Original clothing pixels retain their UVs. */
export function separateShoulderGarment(source: HTMLCanvasElement) {
  const garment=document.createElement("canvas"),skin=document.createElement("canvas");
  garment.width=skin.width=source.width;garment.height=skin.height=source.height;
  const clothing=garment.getContext("2d")!,body=skin.getContext("2d")!;
  const contour=(ctx:CanvasRenderingContext2D)=>{ctx.beginPath();SHOULDER_GARMENT.polygon.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();};
  contour(clothing);clothing.clip();clothing.drawImage(source,0,0);
  body.drawImage(source,0,0);body.globalCompositeOperation="source-atop";
  // Concealed torso underpaint becomes visible only between the lifted armpit
  // and the stationary armhole. It cannot draw beyond the connected skin mesh.
  const tone=body.createLinearGradient(560,350,620,490);
  tone.addColorStop(0,"#fbd0b0");tone.addColorStop(.6,"#f3c6a6");tone.addColorStop(1,"#e8b997");
  contour(body);body.fillStyle=tone;body.fill();
  return {garment,skin};
}
