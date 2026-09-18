"use client";

import { EXPRESSION_GROUPS, EXPRESSION_PRESETS, FACE_LABELS, defaultResponse, expressionChannels, type FaceChannel, type FaceProfile, type FaceValues } from "./face-state";
import styles from "./live-avatar.module.css";

export function ExpressionControls({ profile, morphs, values, running, ready, update, test, preset }: {
  profile: FaceProfile; morphs: string[]; values: FaceValues; running: boolean; ready: boolean;
  update: (patch: Partial<FaceProfile>) => void; test: (key: FaceChannel, value: number) => void;
  preset: (values: Partial<FaceValues>) => void;
}) {
  const channels = expressionChannels(profile);
  const mapped = (key: FaceChannel) => profile.mode === "starter" || morphs.includes(profile.mappings[key]);
  const count = channels.filter(mapped).length;
  return <section>
    <h2>2. 표정 테스트</h2>
    <p>{running ? "감지한 표정을 아바타에 연결하고 있습니다." : "표정 버튼이나 슬라이더로 얼굴 움직임을 확인하세요."} {count}/{channels.length}개 연결됨</p>
    {profile.mode === "native" && <label>표정 범위<select aria-label="표정 범위" value={profile.expressions.preset} disabled={running} onChange={(e) => update({ expressions: { ...profile.expressions, preset: e.target.value as "basic" | "extended" } })}><option value="basic">기본 6개</option><option value="extended">확장 표정 · 눈썹·입술·볼</option></select></label>}
    <div className={styles.expressionPresets}>{EXPRESSION_PRESETS.map((item) => <button type="button" key={item.label} disabled={running || !ready} onClick={() => preset(Object.fromEntries(Object.entries(item.values).filter(([key]) => channels.includes(key as FaceChannel) && mapped(key as FaceChannel))))}>{item.label}</button>)}<button type="button" disabled={running || !ready} onClick={() => preset({})}>무표정</button></div>
    {EXPRESSION_GROUPS.map((group) => {
      const selected = group.channels.filter((key) => channels.includes(key));
      if (!selected.length) return null;
      return <details className={styles.expressionGroup} key={group.label} open={profile.expressions.preset === "basic" || undefined}>
        <summary>{group.label}<small>{selected.filter(mapped).length}/{selected.length}</small></summary>
        {selected.map((key) => {
          const response = profile.expressions.channels[key] ?? defaultResponse();
          return <div className={styles.channel} key={key}>
            <label className={styles.expression}><span>{FACE_LABELS[key]}<b>{mapped(key) ? `${Math.round(values[key] * 100)}%` : "연결 안 됨"}</b></span><input aria-label={FACE_LABELS[key]} type="range" min={0} max={1} step={.01} value={values[key]} disabled={running || !ready || !mapped(key)} onChange={(e) => test(key, Number(e.target.value))} /></label>
            {profile.mode === "native" && <details className={styles.channelSettings}><summary>{FACE_LABELS[key]} 연결·보정</summary>
              <label>모델 표정<select aria-label={`${FACE_LABELS[key]} 매핑`} value={profile.mappings[key] ?? ""} disabled={running} onChange={(e) => update({ mappings: { ...profile.mappings, [key]: e.target.value } })}><option value="">연결 안 함</option>{morphs.map((name) => <option key={name}>{name}</option>)}</select></label>
              {([['gain', '반응 강도', 3], ['deadzone', '미세 움직임 무시', .5], ['max', '최대 변형', 1]] as const).map(([field, label, max]) => <label key={field}>{label} · {response[field].toFixed(2)}<input aria-label={`${FACE_LABELS[key]} ${label}`} type="range" min={0} max={max} step={.01} value={response[field]} onChange={(e) => update({ expressions: { ...profile.expressions, channels: { ...profile.expressions.channels, [key]: { ...response, [field]: Number(e.target.value) } } } })} /></label>)}
            </details>}
          </div>;
        })}
      </details>;
    })}
    {profile.mode === "native" && <p>연결되지 않은 표정은 모델에 해당 변형이 필요합니다. 혀 내밀기는 현재 웹캠 추적에서 제공되지 않아 수동으로 테스트합니다.</p>}
  </section>;
}
