import { describe, expect, it } from "vitest";

import { normalizeDefectWorkflowHistory } from "@/core/defect-workflow/history";

describe("normalizeDefectWorkflowHistory", () => {
  it("builds processed node history from submissions and form data", () => {
    const formJson = JSON.stringify({
      widgetList: [
        {
          type: "switch",
          options: {
            name: "shutdownRequired",
            label: "是否需要停机",
          },
        },
        {
          type: "input",
          options: {
            name: "defectStandard",
            label: "缺陷标准",
          },
        },
      ],
    });

    const history = normalizeDefectWorkflowHistory({
      currentTask: {
        taskId: "90055",
        nodeName: "工程师确认",
      },
      submissions: [
        {
          submissionId: 1,
          taskId: "82516",
          nodeKey: "defect_confirm_leader",
          nodeName: "班长确认",
          action: "SUBMIT",
          comment: "处理意见",
          submittedByName: "user02",
          submittedAt: "2026-06-18T06:15:13.384Z",
          formData:
            JSON.stringify({
              shutdownRequired: false,
              defectStandard: "A",
              formJson,
            }),
        },
      ],
    });

    expect(history).toEqual([
      {
        id: "1",
        taskId: "82516",
        nodeKey: "defect_confirm_leader",
        nodeName: "班长确认",
        action: "SUBMIT",
        actionLabel: "通过",
        operatorName: "user02",
        occurredAt: "2026-06-18T06:15:13.384Z",
        summary: "处理意见",
        formData: [
          { name: "shutdownRequired", label: "是否需要停机", value: "否" },
          { name: "defectStandard", label: "缺陷标准", value: "A" },
        ],
      },
    ]);
  });

  it("uses task form context labels when submission formJson only contains values", () => {
    const history = normalizeDefectWorkflowHistory(
      {
        submissions: [
          {
            submissionId: 2,
            taskId: "90155",
            nodeName: "缺陷处理",
            action: "SUBMIT",
            formData: JSON.stringify({
              maintenanceRecord: [],
              hseControlMeasures: "0620HSE控制措施",
              workHours: 1,
              formJson: JSON.stringify({
                maintenanceRecord: [],
                hseControlMeasures: "0620HSE控制措施",
                workHours: 1,
              }),
            }),
          },
        ],
      },
      {
        contextsByTaskId: {
          "90155": {
            form: {
              widgetList: [
                {
                  type: "textarea",
                  options: {
                    name: "hseControlMeasures",
                    label: "HSE控制措施（低风险）",
                  },
                },
                {
                  type: "number",
                  options: {
                    name: "workHours",
                    label: "工时（小时）",
                  },
                },
                {
                  type: "sub-form",
                  options: {
                    name: "maintenanceRecord",
                    label: "检修过程记录",
                  },
                },
              ],
            },
          },
        },
      },
    );

    expect(history[0]?.formData).toEqual([
      { name: "maintenanceRecord", label: "检修过程记录", value: "" },
      { name: "hseControlMeasures", label: "HSE控制措施（低风险）", value: "0620HSE控制措施" },
      { name: "workHours", label: "工时（小时）", value: "1" },
    ]);
  });

  it("uses labels from string formContent returned by workflow form context", () => {
    const history = normalizeDefectWorkflowHistory(
      {
        submissions: [
          {
            taskId: "90120",
            nodeName: "班长确认",
            action: "SUBMIT",
            formData: JSON.stringify({
              shutdownRequired: true,
              defectStandard: "A",
            }),
          },
        ],
      },
      {
        contextsByTaskId: {
          "90120": {
            formContent: JSON.stringify({
              widgetList: [
                {
                  id: "select-shutdown-required",
                  key: "selectShutdownRequired",
                  type: "select",
                  options: {
                    name: "shutdownRequired",
                    label: "是否需要停机",
                  },
                },
                {
                  id: "select-defect-standard",
                  key: "selectDefectStandard",
                  type: "select",
                  options: {
                    name: "defectStandard",
                    label: "缺陷标准",
                  },
                },
              ],
            }),
          },
        },
      },
    );

    expect(history[0]?.formData).toEqual([
      { name: "shutdownRequired", label: "是否需要停机", value: "是" },
      { name: "defectStandard", label: "缺陷标准", value: "A" },
    ]);
  });

  it("uses labels from nested form.formJson returned by task form context", () => {
    const history = normalizeDefectWorkflowHistory(
      {
        submissions: [
          {
            taskId: "90175",
            nodeName: "缺陷验收",
            action: "SUBMIT",
            formData: JSON.stringify({
              acceptanceResult: "合格",
              treatmentEffect: "运行平稳",
            }),
          },
        ],
      },
      {
        contextsByTaskId: {
          "90175": {
            form: {
              formName: "缺陷管理-验收及后评估",
              formJson: {
                widgetList: [
                  {
                    id: "select-acceptance-result",
                    key: "selectAcceptanceResult",
                    type: "select",
                    options: {
                      name: "acceptanceResult",
                      label: "验收结果",
                    },
                  },
                  {
                    id: "textarea-treatment-effect",
                    key: "textareaTreatmentEffect",
                    type: "textarea",
                    options: {
                      name: "treatmentEffect",
                      label: "处理效果",
                    },
                  },
                ],
              },
            },
          },
        },
      },
    );

    expect(history[0]?.formData).toEqual([
      { name: "acceptanceResult", label: "验收结果", value: "合格" },
      { name: "treatmentEffect", label: "处理效果", value: "运行平稳" },
    ]);
  });
});
