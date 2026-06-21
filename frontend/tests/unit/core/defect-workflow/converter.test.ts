import { describe, expect, it } from "vitest";

import { convertVFormContextToFormModel } from "@/core/defect-workflow";

describe("convertVFormContextToFormModel", () => {
  it("maps supported VForm widgets to form fields with defaults", () => {
    const model = convertVFormContextToFormModel({
      formSchema: {
        widgetList: [
          {
            type: "input",
            options: { name: "defectTitle", label: "缺陷标题", required: true },
          },
          {
            type: "textarea",
            options: { name: "maintenancePlan", label: "维修方案" },
          },
          {
            type: "number",
            options: { name: "riskScore", label: "风险分", min: 0, max: 100 },
          },
          {
            type: "select",
            options: {
              name: "severity",
              label: "严重程度",
              optionItems: [
                { label: "高", value: 3 },
                { label: "低", value: 1 },
              ],
            },
          },
          {
            type: "switch",
            options: { name: "changeRequired", label: "需要变更" },
          },
        ],
      },
      effectiveFormData: {
        defectTitle: "泄漏",
        maintenancePlan: "更换密封",
        riskScore: "42",
        severity: 3,
        changeRequired: true,
      },
    });

    expect(model.fields.map((field) => [field.name, field.type])).toEqual([
      ["defectTitle", "text"],
      ["maintenancePlan", "textarea"],
      ["riskScore", "number"],
      ["severity", "select"],
      ["changeRequired", "checkbox"],
    ]);
    expect(model.fields[0]?.required).toBe(true);
    expect(model.fields[2]?.validation).toEqual({ min: 0, max: 100 });
    expect(model.fields[3]?.options).toEqual([
      { label: "高", value: "3", rawValue: 3 },
      { label: "低", value: "1", rawValue: 1 },
    ]);
    expect(model.defaultValues).toMatchObject({
      defectTitle: "泄漏",
      maintenancePlan: "更换密封",
      riskScore: 42,
      severity: 3,
      changeRequired: true,
    });
    expect(model.hasBlockingUnsupportedRequired).toBe(false);
  });

  it("collects unsupported required widgets as blocking metadata", () => {
    const model = convertVFormContextToFormModel({
      widgetList: [
        {
          type: "upload",
          options: { name: "photo", label: "现场照片", required: true },
        },
      ],
    });

    expect(model.fields).toEqual([]);
    expect(model.unsupportedWidgets).toEqual([
      { type: "upload", name: "photo", label: "现场照片", required: true },
    ]);
    expect(model.hasBlockingUnsupportedRequired).toBe(true);
  });

  it("uses parsed form.formJson from task form context as the current task schema", () => {
    const model = convertVFormContextToFormModel({
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
                optionItems: [
                  { label: "合格", value: "qualified" },
                  { label: "不合格", value: "unqualified" },
                ],
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
      effectiveFormData: {
        acceptanceResult: "qualified",
        treatmentEffect: "运行平稳",
      },
    });

    expect(model.fields.map((field) => [field.name, field.label, field.type])).toEqual([
      ["acceptanceResult", "验收结果", "select"],
      ["treatmentEffect", "处理效果", "textarea"],
    ]);
    expect(model.defaultValues).toMatchObject({
      acceptanceResult: "qualified",
      treatmentEffect: "运行平稳",
    });
  });
});
