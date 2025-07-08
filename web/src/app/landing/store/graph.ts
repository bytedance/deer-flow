// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { Edge, Node } from "@xyflow/react";
import {
  Brain,
  FilePen,
  MessageSquareQuote,
  Microscope,
  SquareTerminal,
  UserCheck,
  Users,
  type LucideIcon,
} from "lucide-react";

export type GraphNode = Node<{
  label: string;
  icon?: LucideIcon;
  active?: boolean;
}>;

export type Graph = {
  nodes: GraphNode[];
  edges: Edge[];
};

const ROW_HEIGHT = 85;
const ROW_1 = 0;
const ROW_2 = ROW_HEIGHT;
const ROW_3 = ROW_HEIGHT * 2;
const ROW_4 = ROW_HEIGHT * 2;
const ROW_5 = ROW_HEIGHT * 3;
const ROW_6 = ROW_HEIGHT * 4;

export const graph: Graph = {
  nodes: [
    {
      id: "Start",
      type: "start",
      position: { x: 0, y: 0 },
      data: { label: "Start" },
    },
    {
      id: "Coordinator",
      type: "agent",
      position: { x: 0, y: 100 },
      data: { label: "Coordinator", agent: "coordinator" },
    },
    {
      id: "Planner",
      type: "agent",
      position: { x: 0, y: 200 },
      data: { label: "Planner", agent: "planner" },
    },
    {
      id: "HumanFeedback",
      type: "agent",
      position: { x: -200, y: 200 },
      data: { label: "Human Feedback", agent: "human_feedback" },
    },
    {
      id: "ResearchTeam",
      type: "agent",
      position: { x: 0, y: 300 },
      data: { label: "Research Team", agent: "research_team" },
    },
    {
      id: "Researcher",
      type: "agent",
      position: { x: -200, y: 300 },
      data: { label: "Researcher", agent: "researcher" },
    },
    {
      id: "Coder",
      type: "agent",
      position: { x: 0, y: 400 },
      data: { label: "Coder", agent: "coder" },
    },
    {
      id: "ImageAgent",
      type: "agent",
      position: { x: 200, y: 300 },
      data: { label: "Image Agent", agent: "image_agent" },
    },
    {
      id: "SpeechAgent",
      type: "agent",
      position: { x: 200, y: 400 },
      data: { label: "Speech Agent", agent: "speech_agent" },
    },
    {
      id: "Reporter",
      type: "agent",
      position: { x: 0, y: 500 },
      data: { label: "Reporter", agent: "reporter" },
    },
    {
      id: "End",
      type: "end",
      position: { x: 0, y: 600 },
      data: { label: "End" },
    },
  ],
  edges: [
    {
      id: "Start->Coordinator",
      source: "Start",
      target: "Coordinator",
      sourceHandle: "right",
      targetHandle: "left",
      animated: true,
    },
    {
      id: "Coordinator->Planner",
      source: "Coordinator",
      target: "Planner",
      sourceHandle: "bottom",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "Planner->Reporter",
      source: "Planner",
      target: "Reporter",
      sourceHandle: "right",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "Planner->HumanFeedback",
      source: "Planner",
      target: "HumanFeedback",
      sourceHandle: "left",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "HumanFeedback->Planner",
      source: "HumanFeedback",
      target: "Planner",
      sourceHandle: "right",
      targetHandle: "bottom",
      animated: true,
    },
    {
      id: "HumanFeedback->ResearchTeam",
      source: "HumanFeedback",
      target: "ResearchTeam",
      sourceHandle: "bottom",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "Reporter->End",
      source: "Reporter",
      target: "End",
      sourceHandle: "bottom",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "ResearchTeam->Researcher",
      source: "ResearchTeam",
      target: "Researcher",
      sourceHandle: "left",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "ResearchTeam->Coder",
      source: "ResearchTeam",
      target: "Coder",
      sourceHandle: "bottom",
      targetHandle: "left",
      animated: true,
    },
    {
      id: "ResearchTeam->ImageAgent",
      source: "ResearchTeam",
      target: "ImageAgent",
      sourceHandle: "right",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "ResearchTeam->SpeechAgent",
      source: "ResearchTeam",
      target: "SpeechAgent",
      sourceHandle: "right",
      targetHandle: "top",
      animated: true,
    },
    {
      id: "Researcher->ResearchTeam",
      source: "Researcher",
      target: "ResearchTeam",
      sourceHandle: "bottom",
      targetHandle: "left",
      animated: true,
    },
    {
      id: "Coder->ResearchTeam",
      source: "Coder",
      target: "ResearchTeam",
      sourceHandle: "top",
      targetHandle: "bottom",
      animated: true,
    },
    {
      id: "ImageAgent->ResearchTeam",
      source: "ImageAgent",
      target: "ResearchTeam",
      sourceHandle: "bottom",
      targetHandle: "right",
      animated: true,
    },
    {
      id: "SpeechAgent->ResearchTeam",
      source: "SpeechAgent",
      target: "ResearchTeam",
      sourceHandle: "top",
      targetHandle: "right",
      animated: true,
    },
    {
      id: "ResearchTeam->Planner",
      source: "ResearchTeam",
      target: "Planner",
      sourceHandle: "top",
      targetHandle: "bottom",
      animated: true,
    },
  ],
};
