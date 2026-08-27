"use client";

import { ArrowRight, BadgeCheck, CircleAlert, Film, Rocket, ShieldCheck, X, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { VideoPlayer } from "@/components/ui/video-player";
import type { CanvasOutput } from "@/lib/canvas-model";

export interface CandidateOption {
  id: string;
  label: string;
  output: CanvasOutput;
  artifactIds: string[];
}

interface CompileDialogProps {
  errors: string[];
  nodeCount: number;
  edgeCount: number;
  estimatedCost: number;
  onClose: () => void;
  onRun: () => void;
}

export function CompileDialog({ errors, nodeCount, edgeCount, estimatedCost, onClose, onRun }: CompileDialogProps) {
  const valid = errors.length === 0;
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="modal-card compile-modal" overlayClassName="modal-backdrop">
      <div className="modal-heading"><div><span className="subtle-label">Graph validation</span><DialogTitle asChild><h2>{valid ? "Ready to run" : "Graph needs attention"}</h2></DialogTitle><DialogDescription asChild><p>{valid ? "모든 Step과 포트 연결을 확인했습니다." : "실행 전에 아래 문제를 해결하세요."}</p></DialogDescription></div><DialogClose asChild><Button variant="secondary" size="icon" type="button" aria-label="Close graph validation"><X size={17} /></Button></DialogClose></div>
      {valid ? <div className="compile-checks"><div><BadgeCheck size={17} /><span><strong>Graph contracts valid</strong><small>{nodeCount} nodes · {edgeCount} typed connections · no cycles</small></span></div><div><ShieldCheck size={17} /><span><strong>Reference isolation enforced</strong><small>Generation steps receive structured Format only</small></span></div><div><Zap size={17} /><span><strong>Ready for step execution</strong><small>Steps run in dependency order</small></span></div></div> : <div className="validation-errors">{errors.map((error) => <div key={error}><CircleAlert size={15} /><span>{error}</span></div>)}</div>}
      <div className="compile-summary"><div><small>Steps</small><strong>{nodeCount}</strong></div><div><small>Connections</small><strong>{edgeCount}</strong></div><div><small>Estimated cost</small><strong>${estimatedCost.toFixed(2)}</strong></div><div><small>Execution</small><strong>Dependency DAG</strong></div></div>
      <div className="modal-actions"><DialogClose asChild><Button variant="secondary" type="button">Back to edit</Button></DialogClose>{valid && <Button type="button" onClick={onRun}><Rocket size={15} /> Run {nodeCount} steps</Button>}</div>
    </DialogContent>
  </Dialog>;
}

interface CandidateDialogProps {
  candidates: CandidateOption[];
  selected: number;
  setSelected: (value: number) => void;
  onClose: () => void;
  onApprove: () => void;
}

export function CandidateDialog({ candidates, selected, setSelected, onClose, onApprove }: CandidateDialogProps) {
  const active = candidates[selected];
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="candidate-dialog" overlayClassName="modal-backdrop candidate-backdrop">
      <div className="candidate-dialog-head"><div><span className="subtle-label">Human review · Candidate Select step</span><DialogTitle asChild><h2>Choose a connected video</h2></DialogTitle><DialogDescription asChild><p>연결된 실제 Video Artifact 중 다음 Step으로 전달할 결과를 선택합니다.</p></DialogDescription></div><DialogClose asChild><Button variant="secondary" size="icon" type="button" aria-label="Close candidate selection"><X size={17} /></Button></DialogClose></div>
      <div className="candidate-grid">{candidates.map((candidate, index) => <button type="button" key={candidate.id} onClick={() => setSelected(index)} className={`candidate-card ${selected === index ? "selected" : ""}`}><div className="candidate-video"><VideoPlayer src={candidate.output.url ?? ""} mimeType={candidate.output.mimeType} title={candidate.output.title} controls={false} autoPlay loop />{selected === index && <i className="selected-check"><BadgeCheck size={18} /></i>}</div><div><span><strong>{candidate.label}</strong><small>{candidate.output.title}</small></span><span className="ai-score"><Film size={11} /> Artifact</span></div></button>)}</div>
      {!candidates.length && <div className="candidate-details"><div><span className="subtle-label">No runnable candidates</span><p>Artifact가 저장된 Video 출력 노드를 하나 이상 연결한 뒤 다시 실행하세요.</p></div></div>}
      {active && <div className="candidate-details"><div><span className="subtle-label">Selected output</span><p>{active.output.title} · {active.artifactIds.join(", ")}</p></div></div>}
      <div className="candidate-footer"><span>{active ? <><BadgeCheck size={16} /> {active.label} selected · original Artifact remains immutable</> : "Video Artifact connection required"}</span><div><Button type="button" onClick={onApprove} disabled={!active}>Use candidate & complete step <ArrowRight size={15} /></Button></div></div>
    </DialogContent>
  </Dialog>;
}
