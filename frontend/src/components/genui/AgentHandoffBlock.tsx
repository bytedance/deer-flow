"use client";

import { useRouter } from "next/navigation";
import { ArrowRight, Wrench } from "lucide-react";

// ---------------------------------------------------------------------------
// Types — mirrors the handoff_data sent by the abnormal-judgment agent
// ---------------------------------------------------------------------------

interface AgentHandoffPoint {
  point_id: string;
  point_name: string;
  value_type: string;
  point_type: number;
}

interface AgentHandoffEvent {
  time: number;
  type: string;
  event_level: number;
  desc: string;
  points?: AgentHandoffPoint[];
  time_range_start?: number;
  time_range_end?: number;
}

interface AgentHandoffEquipment {
  mac_id: string;
  component_id: string;
  factory_id: string;
  mac_name: string;
  mac_path: string;
  component_name: string;
  mac_type: number;
}

interface AgentHandoffJudgment {
  conclusion: string;
  confidence: number;
  suspected_fault_type: string;
  severity: string;
  evidence: string[];
  health_score: number;
  run_status: string;
}

interface AgentHandoffData {
  source_agent: string;
  abnormal_id: string;
  equipment: AgentHandoffEquipment;
  events: AgentHandoffEvent[];
  judgment: AgentHandoffJudgment;
}

interface AgentHandoffBlockProps {
  block: {
    block_id?: string;
    props: {
      target_agent: string;
      target_display_name: string;
      target_icon: string;
      message: string;
      handoff_data: AgentHandoffData;
    };
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AgentHandoffBlock({ block }: AgentHandoffBlockProps) {
  const router = useRouter();
  const { target_agent, target_display_name, target_icon, message, handoff_data } =
    block.props;

  const handleJump = () => {
    // ① 暂存 handoff 上下文到 sessionStorage
    sessionStorage.setItem(
      `handoff:${target_agent}`,
      JSON.stringify(handoff_data),
    );
    // ② 跳转到目标Agent的新对话
    router.push(`/workspace/agents/${target_agent}/chats/new?handoff=1`);
  };

  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2 text-sm font-medium">
        <span>{target_icon}</span>
        <span>{target_display_name}</span>
      </div>

      {/* Message */}
      <p className="text-sm text-muted-foreground">{message}</p>

      {/* Action button */}
      <button
        type="button"
        className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        onClick={handleJump}
      >
        <Wrench className="h-4 w-4" />
        跳转到{target_display_name}
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}
